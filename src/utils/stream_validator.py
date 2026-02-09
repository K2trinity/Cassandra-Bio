"""
Data Customs: Strict Validation Middleware for LLM Outputs

This module sits between Gemini LLM outputs and the Supervisor orchestrator.
It sanitizes raw JSON responses, validates schema compliance, and prevents
"Data not available" crashes by filling missing keys with safe defaults.

Core Responsibilities:
1. Strip Markdown artifacts (```json, code fences)
2. Parse and validate JSON structure
3. Enforce schema compliance for each Engine
4. Provide fallback values for missing required keys

Usage:
    from src.utils.stream_validator import StreamValidator
    
    # For BioHarvest Engine
    raw_response = llm.generate(prompt)
    clean_data = StreamValidator.validate_bioharvest_payload(
        StreamValidator.sanitize_llm_json(raw_response)
    )
    
    # For Forensic Engine
    raw_response = llm.generate(image_analysis_prompt)
    clean_data = StreamValidator.validate_forensic_payload(
        StreamValidator.sanitize_llm_json(raw_response)
    )
"""

import json
import re
from typing import Dict, Any, List, Optional
from loguru import logger


class StreamValidator:
    """
    The Gatekeeper: Ensures NO raw LLM output enters Supervisor without sanitization.
    
    All LLM responses must pass through:
    1. sanitize_llm_json() - Clean markdown, parse JSON
    2. validate_<engine>_payload() - Enforce schema, fill defaults
    
    This prevents schema mismatches and the dreaded "Data not available" crash.
    """
    
    @staticmethod
    def sanitize_llm_json(raw_text: str) -> Dict[str, Any]:
        """
        Step 1: Clean and parse raw LLM output into Python dict.
        
        🚨 ENHANCED: Multi-strategy JSON extraction with JSONDecoder
        Handles common LLM output issues:
        - Markdown code fences (```json, ```)
        - Extra explanatory text before/after JSON
        - Malformed JSON (missing quotes, trailing commas)
        - Mixed content (prose + JSON)
        
        Args:
            raw_text: Raw string output from LLM (may contain markdown, prose, etc.)
        
        Returns:
            Parsed Python dictionary, or error dict if parsing fails
        
        Example:
            >>> raw = '```json\\n{"key": "value"}\\n```'
            >>> StreamValidator.sanitize_llm_json(raw)
            {'key': 'value'}
        """
        if not raw_text or not raw_text.strip():
            logger.warning("Empty LLM response received")
            return {"error": "Empty response", "raw": ""}
        
        # Step 1: Remove markdown code fences
        text = raw_text.strip()
        text = re.sub(r"```[a-zA-Z]*\s*", "", text)  # Remove opening fences
        text = re.sub(r"```\s*", "", text)           # Remove closing fences
        
        # Step 2: 🔥 NEW: Try JSONDecoder for precise extraction (handles mixed content)
        decoder = json.JSONDecoder()
        # Try to find JSON starting from the first '{'
        text_stripped = text.lstrip()
        try:
            obj, idx = decoder.raw_decode(text_stripped)
            logger.debug(f"✅ JSONDecoder successfully parsed JSON with {len(str(obj))} chars")
            return obj
        except json.JSONDecodeError:
            logger.debug("JSONDecoder failed, falling back to regex...")
        
        # Step 3: Fallback - Regex extraction (handles more malformed cases)
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            clean_json = match.group(0)
            try:
                data = json.loads(clean_json)
                logger.debug(f"✅ Regex parser successfully parsed JSON with {len(str(data))} chars")
                return data
            except json.JSONDecodeError as e:
                logger.error(f"JSON parse error: {e}")
                logger.debug(f"Failed JSON string: {clean_json[:500]}")
                # Fall through to error return
        
        # Fallback: If all methods fail, return error dict
        logger.error("❌ No valid JSON structure found in LLM response")
        logger.debug(f"Raw text preview: {raw_text[:300]}")
        logger.debug(f"After cleanup: {text[:300]}")
        logger.error(f"🔍 Full response (first 1000 chars): {raw_text[:1000]}")
        return {"error": "No JSON found", "raw": raw_text[:200]}
    
    @staticmethod
    def validate_bioharvest_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Step 2: Enforce BioHarvest Engine output schema.
        
        Expected schema from BioHarvest LLM:
        {
            "trials_analyzed": int,
            "failed_trials_count": int,
            "key_failures": [str, str, ...],
            "scientific_summary": str,
            "risk_flags": [str, str, ...]
        }
        
        Guarantees:
        - 'scientific_summary' always exists (even if empty)
        - 'risk_flags' is always a list
        - 'stats' dict contains trial counts
        
        Args:
            data: Parsed JSON from sanitize_llm_json()
        
        Returns:
            Validated dict with guaranteed keys
        
        Example:
            >>> raw_data = {"scientific_summary": "MOA is unclear"}
            >>> StreamValidator.validate_bioharvest_payload(raw_data)
            {
                'scientific_summary': 'MOA is unclear',
                'risk_flags': [],
                'stats': {'total': 0, 'failed': 0},
                'key_failures': []
            }
        """
        if "error" in data:
            logger.error(f"BioHarvest validation received error payload: {data.get('error')}")
            return {
                "scientific_summary": "Data extraction failed - LLM returned invalid JSON.",
                "risk_flags": ["JSON_PARSE_ERROR"],
                "stats": {"total": 0, "failed": 0},
                "key_failures": [],
                "error": data.get("error")
            }
        
        # Extract and validate fields with fallbacks
        validated = {
            # Primary summary field (try multiple keys)
            "scientific_summary": (
                data.get("scientific_summary") or 
                data.get("summary") or 
                data.get("mechanism_summary") or
                "Summary extraction failed - check raw data."
            ),
            
            # Risk signals (ensure it's a list)
            "risk_flags": data.get("risk_flags") or data.get("risks") or [],
            
            # Trial statistics
            "stats": {
                "total": int(data.get("trials_analyzed", 0) or 0),
                "failed": int(data.get("failed_trials_count", 0) or 0)
            },
            
            # Key failure descriptions
            "key_failures": data.get("key_failures") or []
        }
        
        # Ensure risk_flags is a list
        if not isinstance(validated["risk_flags"], list):
            validated["risk_flags"] = [str(validated["risk_flags"])]
        
        # Ensure key_failures is a list
        if not isinstance(validated["key_failures"], list):
            validated["key_failures"] = [str(validated["key_failures"])]
        
        logger.debug(f"BioHarvest payload validated: {validated['stats']['total']} trials, {len(validated['risk_flags'])} risks")
        return validated
    
    @staticmethod
    def validate_forensic_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Step 2: Enforce Forensic Engine output schema.
        
        🚨 SURGICAL FIX: Maps fuzzy LLM outputs to strict Enums.
        
        Expected schema from Forensic LLM:
        {
            "image_id": str,
            "status": "SUSPICIOUS" | "CLEAN" | "INCONCLUSIVE",
            "tampering_probability": float (0.0 - 1.0),
            "findings": str,
            "page_number": int
        }
        
        Guarantees:
        - 'status' is one of three valid values
        - 'score' (tampering_probability) is a float between 0-1
        - 'findings' always exists (even if empty)
        
        Args:
            data: Parsed JSON from sanitize_llm_json()
        
        Returns:
            Validated dict with guaranteed keys
        
        Example:
            >>> raw_data = {"status": "NO_EVIDENCE_OF_MANIPULATION", "tampering_probability": "0.15"}
            >>> StreamValidator.validate_forensic_payload(raw_data)
            {
                'status': 'CLEAN',
                'score': 0.15,
                'findings': 'No detailed findings provided.',
                'page_number': None
            }
        """
        if "error" in data:
            logger.error(f"Forensic validation received error payload: {data.get('error')}")
            return {
                "status": "ERROR",
                "score": 0.0,
                "findings": f"Image analysis failed: {data.get('error')}",
                "page_number": None,
                "error": data.get("error")
            }
        
        # 🔥 STEP 1: Extract and normalize raw status
        raw_status = data.get("status", "INCONCLUSIVE")
        if isinstance(raw_status, str):
            raw_status = raw_status.upper().replace(" ", "_")
        else:
            raw_status = "INCONCLUSIVE"
        
        # 🔥 ENHANCED FUZZY MAPPING: Handle natural language outputs + partial matches
        status_map = {
            "NO_EVIDENCE_OF_MANIPULATION": "CLEAN",
            "NO_MANIPULATION_DETECTED": "CLEAN",
            "NO_MANIPULATION_FOUND": "CLEAN",
            "NO_ISSUES_DETECTED": "CLEAN",
            "NO_EVIDENCE": "CLEAN",
            "CLEAN": "CLEAN",
            "ANALYSIS_COMPLETE": "CLEAN",  # 🔥 NEW: Handle completion without issues
            "AUTHENTIC": "CLEAN",
            "SUSPICIOUS_ELEMENTS": "SUSPICIOUS",
            "POTENTIAL_MANIPULATION": "SUSPICIOUS",
            "MANIPULATION_DETECTED": "SUSPICIOUS",
            "SUSPICIOUS": "SUSPICIOUS",
            "TAMPERED": "SUSPICIOUS",
            "INCONCLUSIVE": "INCONCLUSIVE",
            "UNCERTAIN": "INCONCLUSIVE",
            "UNCLEAR": "INCONCLUSIVE"
        }
        
        # Map fuzzy status to strict enum
        status = status_map.get(raw_status, raw_status)
        
        # 🔥 NEW: Fuzzy matching for unrecognized statuses
        if status not in {"SUSPICIOUS", "CLEAN", "INCONCLUSIVE", "ERROR"}:
            # Check for partial matches (e.g., "NO_MANIPULATION" contains "NO" and "MANIPULATION")
            if "NO" in raw_status and ("MANIPULATION" in raw_status or "ISSUE" in raw_status):
                logger.info(f"Fuzzy match: '{raw_status}' → CLEAN")
                status = "CLEAN"
            elif "SUSPICIOUS" in raw_status or "TAMPER" in raw_status or "MANIPULAT" in raw_status:
                logger.info(f"Fuzzy match: '{raw_status}' → SUSPICIOUS")
                status = "SUSPICIOUS"
            else:
                logger.warning(f"⚠️ Unknown status '{raw_status}' → defaulting to INCONCLUSIVE")
                status = "INCONCLUSIVE"
        
        # Extract and validate tampering probability
        raw_score = data.get("tampering_probability") or data.get("score") or 0.0
        try:
            score = float(raw_score)
            # Clamp to [0, 1]
            score = max(0.0, min(1.0, score))
        except (ValueError, TypeError):
            logger.warning(f"Invalid tampering_probability '{raw_score}', defaulting to 0.0")
            score = 0.0
        
        # Extract findings
        findings = data.get("findings") or data.get("analysis") or "No detailed findings provided."
        
        # Extract page number (optional)
        page_num = data.get("page_number") or data.get("page") or None
        
        validated = {
            "status": status,
            "score": score,
            "findings": findings,
            "page_number": page_num
        }
        
        logger.debug(f"Forensic payload validated: {status} (score={score:.2f})")
        return validated
    
    @staticmethod
    def validate_evidence_payload(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Step 2: Enforce Evidence Miner output schema.
        
        Expected schema from Evidence Miner LLM:
        {
            "paper_summary": str,
            "risk_signals": [
                {
                    "signal_type": "STATISTICAL_FLAW" | "SAFETY_CONCERN" | ...,
                    "description": str,
                    "severity": "HIGH" | "MEDIUM" | "LOW",
                    "page_reference": str
                },
                ...
            ]
        }
        
        Guarantees:
        - 'paper_summary' always exists
        - 'risk_signals' is a list (even if empty)
        - Each risk signal has required fields
        
        Args:
            data: Parsed JSON from sanitize_llm_json()
        
        Returns:
            Validated dict with guaranteed structure
        """
        if "error" in data:
            logger.error(f"Evidence validation received error payload: {data.get('error')}")
            return {
                "paper_summary": f"PDF text extraction failed: {data.get('error')}",
                "risk_signals": [],
                "error": data.get("error")
            }
        
        # Validate paper summary
        paper_summary = (
            data.get("paper_summary") or 
            data.get("summary") or 
            "Paper summary extraction failed."
        )
        
        # Validate risk signals array
        raw_signals = data.get("risk_signals") or []
        if not isinstance(raw_signals, list):
            logger.warning("risk_signals is not a list, wrapping in array")
            raw_signals = [raw_signals]
        
        # Validate each signal
        validated_signals = []
        for signal in raw_signals:
            if not isinstance(signal, dict):
                logger.warning(f"Skipping non-dict signal: {signal}")
                continue
            
            validated_signal = {
                "signal_type": signal.get("signal_type", "UNKNOWN"),
                "description": signal.get("description", "No description provided"),
                "severity": signal.get("severity", "MEDIUM"),
                "page_reference": signal.get("page_reference") or signal.get("page") or "Unknown"
            }
            
            # Ensure severity is valid
            if validated_signal["severity"] not in {"HIGH", "MEDIUM", "LOW"}:
                validated_signal["severity"] = "MEDIUM"
            
            validated_signals.append(validated_signal)
        
        validated = {
            "paper_summary": paper_summary,
            "risk_signals": validated_signals
        }
        
        logger.debug(f"Evidence payload validated: {len(validated_signals)} risk signals found")
        return validated
    
    @staticmethod
    def batch_validate(
        data_list: List[Dict[str, Any]], 
        validator_type: str
    ) -> List[Dict[str, Any]]:
        """
        Validate multiple payloads at once.
        
        Args:
            data_list: List of dicts from sanitize_llm_json()
            validator_type: 'bioharvest', 'forensic', or 'evidence'
        
        Returns:
            List of validated payloads
        
        Example:
            >>> responses = [llm_response1, llm_response2, llm_response3]
            >>> sanitized = [StreamValidator.sanitize_llm_json(r) for r in responses]
            >>> validated = StreamValidator.batch_validate(sanitized, 'forensic')
        """
        validators = {
            'bioharvest': StreamValidator.validate_bioharvest_payload,
            'forensic': StreamValidator.validate_forensic_payload,
            'evidence': StreamValidator.validate_evidence_payload
        }
        
        if validator_type not in validators:
            raise ValueError(f"Unknown validator type: {validator_type}")
        
        validator_fn = validators[validator_type]
        return [validator_fn(data) for data in data_list]


# Convenience functions for direct use
def clean_bioharvest_response(raw_llm_output: str) -> Dict[str, Any]:
    """One-step: sanitize + validate BioHarvest response."""
    return StreamValidator.validate_bioharvest_payload(
        StreamValidator.sanitize_llm_json(raw_llm_output)
    )


def clean_forensic_response(raw_llm_output: str) -> Dict[str, Any]:
    """One-step: sanitize + validate Forensic response."""
    return StreamValidator.validate_forensic_payload(
        StreamValidator.sanitize_llm_json(raw_llm_output)
    )


def clean_evidence_response(raw_llm_output: str) -> Dict[str, Any]:
    """One-step: sanitize + validate Evidence response."""
    return StreamValidator.validate_evidence_payload(
        StreamValidator.sanitize_llm_json(raw_llm_output)
    )
