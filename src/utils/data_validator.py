"""
Data Validation Middleware for LLM Outputs
Ensures downstream agents always receive consistent data structures
"""
import json
import re
from typing import Dict, Any, List
from loguru import logger


class DataValidator:
    """
    Standardization Middleware for LLM Outputs.
    Ensures downstream agents (Supervisor/Writer) always receive consistent data structures.
    
    This class acts as a "Customs Officer" - it stops the LLM's raw output,
    cleans it, validates it against a schema, and defaults to safe values if broken.
    Gemini raw output never touches the Supervisor without passing through this validator.
    """

    @staticmethod
    def clean_json_text(text: str) -> str:
        """
        Removes Markdown, comments, and extra whitespace from LLM output.
        
        LLMs often wrap JSON in markdown code blocks or add conversational text.
        This method strips all that away to extract pure JSON.
        
        Args:
            text: Raw LLM output that may contain JSON
            
        Returns:
            Cleaned JSON string, or empty object "{}" if no JSON found
            
        Examples:
            >>> DataValidator.clean_json_text("```json\\n{...}\\n```")
            '...'
            >>> DataValidator.clean_json_text("Here's the result: {...}")
            '...'
        """
        if not text:
            logger.warning("Empty text provided to clean_json_text")
            return "{}"
        
        # Remove ```json ... ``` wrappers
        text = re.sub(r"```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"```\s*", "", text)
        
        # Extract JSON object boundaries
        start = text.find('{')
        end = text.rfind('}')
        
        if start != -1 and end != -1:
            return text[start : end + 1]
        
        logger.warning("No JSON object boundaries found in text")
        return "{}"

    @staticmethod
    def normalize_evidence_payload(raw_llm_output: str, filename: str) -> Dict[str, Any]:
        """
        Validates and standardizes the Miner's output.
        Returns a Guaranteed Dictionary Structure.
        
        This is the "Standardization Algorithm" - it enforces a consistent
        data contract regardless of how the LLM formats its response.
        
        Args:
            raw_llm_output: Raw text output from LLM (may be malformed JSON)
            filename: Source file name for metadata tracking
            
        Returns:
            Dict with guaranteed structure:
            {
                "meta": {
                    "source_file": str,
                    "status": "PROCESSED" | "PARTIAL" | "FAILED"
                },
                "content": {
                    "summary": str (guaranteed non-null),
                    "risk_signals": List (guaranteed, may be empty)
                }
            }
            
        Handles:
            - Malformed JSON (returns safe defaults)
            - Legacy List format (converts to new Dict format)
            - Missing keys (provides fallback values)
            - Type mismatches (coerces to correct types)
        """
        # 1. Clean & Parse
        clean_text = DataValidator.clean_json_text(raw_llm_output)
        
        try:
            data = json.loads(clean_text)
        except json.JSONDecodeError as e:
            logger.warning(f"JSON Parse Failed for {filename}: {e}. Using fallback.")
            data = {}
        except Exception as e:
            logger.error(f"Unexpected error parsing JSON for {filename}: {e}")
            data = {}

        # 2. Enforce Schema (The "Standardization Algorithm")
        # Handle cases where LLM returns a list instead of a dict
        if isinstance(data, list):
            logger.info(f"Legacy List Format detected for {filename}, converting to standard Dict")
            risk_signals = data
            summary = "Summary not provided (Legacy List Format)."
            status = "PARTIAL"
        
        elif isinstance(data, dict):
            # Extract flexible keys to handle schema drift
            summary = (
                data.get("paper_summary") or 
                data.get("summary") or 
                data.get("overview") or 
                data.get("abstract") or
                "Summary extraction failed."
            )
            
            # Handle multiple possible key names for risk signals
            risk_signals = (
                data.get("risk_signals") or 
                data.get("evidence_items") or 
                data.get("findings") or 
                data.get("evidence") or
                data.get("items") or
                data.get("results") or
                []
            )
            
            # Determine status based on content quality
            if summary and len(summary) > 50 and isinstance(risk_signals, list):
                status = "PROCESSED"
            elif summary or risk_signals:
                status = "PARTIAL"
            else:
                status = "FAILED"
        
        else:
            logger.error(f"Unexpected data type for {filename}: {type(data)}")
            risk_signals = []
            summary = "Parsing Error: Unexpected data type"
            status = "FAILED"

        # 3. Construct Standardized Payload
        standardized_payload = {
            "meta": {
                "source_file": filename,
                "status": status
            },
            "content": {
                "summary": summary,  # Guaranteed String
                "risk_signals": risk_signals  # Guaranteed List
            }
        }
        
        # 4. Log validation results
        logger.success(
            f"✅ Data Validated for {filename}: "
            f"Status={status}, "
            f"Summary Length={len(summary)} chars, "
            f"Risk Signals={len(risk_signals)} items"
        )
        
        return standardized_payload

    @staticmethod
    def validate_risk_signal(signal: Dict[str, Any]) -> bool:
        """
        Validates a single risk signal object against expected schema.
        
        Args:
            signal: Risk signal dictionary to validate
            
        Returns:
            True if valid, False otherwise
            
        Expected schema:
            {
                "signal_type": str (or "risk_type"),
                "description": str (or "explanation"),
                "severity": str (or "risk_level"),
                "page_reference": str (optional)
            }
        """
        if not isinstance(signal, dict):
            return False
        
        # Check for required keys (with flexibility for naming variations)
        has_type = any(k in signal for k in ["signal_type", "risk_type", "type"])
        has_description = any(k in signal for k in ["description", "explanation", "quote"])
        has_severity = any(k in signal for k in ["severity", "risk_level", "level"])
        
        return has_type and has_description and has_severity

    @staticmethod
    def sanitize_risk_signals(raw_signals: List[Any]) -> List[Dict[str, Any]]:
        """
        Cleans and standardizes a list of risk signals.
        
        Handles:
            - Invalid signal objects (removes them)
            - Inconsistent key naming (normalizes to standard keys)
            - Missing optional fields (adds defaults)
            
        Args:
            raw_signals: Raw list of risk signal objects from LLM
            
        Returns:
            List of cleaned and standardized risk signal dicts
        """
        if not isinstance(raw_signals, list):
            logger.warning(f"Risk signals is not a list: {type(raw_signals)}")
            return []
        
        sanitized = []
        
        for i, signal in enumerate(raw_signals):
            if not isinstance(signal, dict):
                logger.warning(f"Risk signal {i} is not a dict, skipping")
                continue
            
            # Normalize key names
            standardized_signal = {
                "signal_type": (
                    signal.get("signal_type") or 
                    signal.get("risk_type") or 
                    signal.get("type") or 
                    "UNKNOWN"
                ),
                "description": (
                    signal.get("description") or 
                    signal.get("explanation") or 
                    signal.get("quote") or 
                    "No description provided"
                ),
                "severity": (
                    signal.get("severity") or 
                    signal.get("risk_level") or 
                    signal.get("level") or 
                    "LOW"
                ).upper(),
                "page_reference": (
                    signal.get("page_reference") or 
                    signal.get("page_estimate") or 
                    signal.get("source") or 
                    "Unknown"
                )
            }
            
            # Validate severity is one of allowed values
            if standardized_signal["severity"] not in ["HIGH", "MEDIUM", "LOW"]:
                logger.warning(f"Invalid severity '{standardized_signal['severity']}', defaulting to LOW")
                standardized_signal["severity"] = "LOW"
            
            sanitized.append(standardized_signal)
        
        logger.info(f"Sanitized {len(sanitized)}/{len(raw_signals)} risk signals")
        return sanitized


# Convenience function for one-step validation
def validate_and_normalize(raw_output: str, filename: str) -> Dict[str, Any]:
    """
    One-step validation and normalization for evidence mining outputs.
    
    This is the main entry point for validation in the pipeline.
    
    Args:
        raw_output: Raw LLM output string
        filename: Source file identifier
        
    Returns:
        Standardized payload dictionary
    """
    payload = DataValidator.normalize_evidence_payload(raw_output, filename)
    
    # Additional sanitization of risk signals
    raw_signals = payload["content"]["risk_signals"]
    payload["content"]["risk_signals"] = DataValidator.sanitize_risk_signals(raw_signals)
    
    return payload
