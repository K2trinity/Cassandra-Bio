"""
Evidence Miner Agent - Bio-Short-Seller Supplementary Material Dark Data Extractor

This agent uses Gemini's long-context window (2M tokens) to read full PDF texts
and extract "negative results" that are often buried in supplementary materials,
appendices, or footnotes.

Core capabilities:
- Extract full text from research PDFs (including all pages)
- Use Gemini's 2M token context to analyze entire papers
- Mine for "dark data": insignificant p-values, "data not shown", early terminations
- Extract toxicity warnings and adverse events from supplementary sections
- Handle token limits gracefully with chunking fallback

Workflow:
1. Extract full text from PDF using PyMuPDF
2. Check token count and chunk if necessary
3. Send to Gemini with dark data mining prompt
4. Parse structured JSON response with risk signals
5. Return list of EvidenceItem objects
"""

import os
import json
import re
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass
from loguru import logger

from src.llms import create_evidence_client
from src.tools import extract_text_from_pdf


# Token limits for safety (Gemini 1.5/2.0 Pro has ~2M input, but be conservative)
MAX_INPUT_TOKENS = 1_800_000  # Leave buffer for system prompt and output
CHARS_PER_TOKEN_ESTIMATE = 4  # Conservative estimate for English text


@dataclass
class EvidenceItem:
    """
    Single piece of extracted dark data evidence.
    
    Attributes:
        source: Section where evidence was found (e.g., "Supplementary Materials", "Methods")
        page_estimate: Estimated page number or range
        quote: Direct quote from the paper
        risk_level: HIGH, MEDIUM, LOW
        risk_type: Category (p-value, data-not-shown, toxicity, termination, etc.)
        explanation: Analysis of why this is a risk signal
    """
    source: str
    page_estimate: str
    quote: str
    risk_level: str  # HIGH, MEDIUM, LOW
    risk_type: str
    explanation: str


class EvidenceMinerAgent:
    """
    Supplementary Material Dark Data Miner
    
    Uses Gemini's long-context capabilities to read entire research papers
    and extract negative signals that authors may have buried in appendices.
    """
    
    def __init__(self):
        """Initialize Evidence Miner with long-context Gemini client."""
        
        # Initialize LLM client (Gemini Pro with 2M token context)
        self.llm = create_evidence_client()
        logger.info("Evidence Miner initialized with Gemini Long Context")
        
        # AUDIT FIX: Load system prompt from external file for maintainability
        from pathlib import Path
        prompt_path = Path(__file__).parent.parent / "src" / "prompts" / "evidence_miner" / "system.txt"
        if prompt_path.exists():
            self.mining_system_prompt = prompt_path.read_text(encoding='utf-8')
            logger.debug("Loaded evidence miner system prompt from file")
        else:
            logger.warning(f"Prompt file not found: {prompt_path}, using fallback")
            self.mining_system_prompt = """You are a ruthless scientific auditor specializing in uncovering "dark data" - negative results that researchers often bury in supplementary materials or footnotes.

Your task is to thoroughly analyze this biomedical research paper and extract ALL risk signals, especially:

**Statistical Red Flags:**
- p-values > 0.05 (statistically insignificant results)
- Wide confidence intervals suggesting unreliable data
- Missing or suspiciously rounded p-values
- Post-hoc analysis or p-hacking indicators

**Data Suppression:**
- Phrases like "data not shown", "results omitted for brevity"
- Missing negative controls
- Experiments mentioned but not detailed
- Selective reporting of outcomes

**Study Integrity Issues:**
- Experiments terminated early without clear justification
- Changes in primary endpoints mid-study
- Unexplained dropouts or exclusions
- Funding conflicts of interest

**Safety Signals:**
- Adverse events (even if "not statistically significant")
- Toxicity warnings or safety monitoring changes
- Dose reductions due to tolerability
- Subject withdrawals due to side effects

**Supplementary Materials Focus:**
Pay EXTRA attention to:
- Supplementary figures and tables (often contain failed experiments)
- Appendices
- Methods sections (may reveal protocol deviations)
- Acknowledgments/Disclosures (funding conflicts)

**CRITICAL OUTPUT INSTRUCTION:**
You MUST return a JSON Object with exactly two keys:

1. **paper_summary**: A 300-word detailed summary of the study, including:
   - Study design and methodology
   - Primary and secondary outcomes
   - Key findings and results
   - Statistical significance and confidence
   - Study limitations and conflicts of interest
   
2. **risk_signals**: A list of evidence items (or an empty list if clean)

**OUTPUT FORMAT:**
```json
{
  "paper_summary": "Detailed 300-word study overview covering methodology, outcomes, results, and context...",
  "risk_signals": [
    {
      "source": "Supplementary Table 3",
      "page_estimate": "p. 45 (appendix)",
      "quote": "Cardiac biomarker elevations (not statistically significant, p=0.14) were observed in 8/30 subjects",
      "risk_level": "HIGH",
      "risk_type": "toxicity",
      "explanation": "Cardiac toxicity signal dismissed as insignificant, but 27% incidence is clinically concerning"
    }
  ]
}
```

**RISK LEVELS:**
- HIGH: Clear safety concerns, statistically weak primary outcomes, major data omissions
- MEDIUM: Suspicious patterns, inconvenient secondary outcomes, minor protocol deviations
- LOW: Minor statistical issues, minor transparency problems

**CRITICAL RULES:**
- ALWAYS include both paper_summary and risk_signals in your output
- paper_summary must be comprehensive (300 words minimum)
- Be thorough - scan the ENTIRE text including all supplementary sections
- Extract EXACT quotes (do not paraphrase)
- Focus on negative/neutral results, not positive claims
- If no significant dark data found, return empty array for risk_signals
"""
    
    def mine_evidence(
        self, 
        pdf_path: str,
        include_metadata: bool = True,
        chunk_if_needed: bool = True
    ) -> Dict[str, Any]:
        """
        Mine dark data from a research paper PDF.
        
        Args:
            pdf_path: Path to the PDF file to analyze
            include_metadata: Include PDF metadata in extracted text
            chunk_if_needed: If PDF exceeds token limit, process in chunks
        
        Returns:
            Dict with:
                - paper_summary: str (comprehensive study overview)
                - risk_signals: List[EvidenceItem] (risk findings)
                - filename: str (PDF filename for tracking)
        
        Workflow:
            Step A: Extract full text from PDF
            Step B: Check token count and chunk if necessary
            Step C: Mine for dark data using Gemini
            Step D: Parse and structure evidence items
        
        Example:
            >>> agent = EvidenceMinerAgent()
            >>> result = agent.mine_evidence("clinical_trial_paper.pdf")
            >>> print(f"Summary: {result['paper_summary'][:100]}...")
            >>> print(f"Found {len(result['risk_signals'])} risk signals")
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"📄 Evidence Mining: {Path(pdf_path).name}")
        logger.info(f"{'='*60}")
        
        # ===== GATEKEEPER CHECK: Prevent Null Pointer Crashes =====
        if pdf_path is None or not Path(pdf_path).exists():
            logger.critical("⚠️ CRITICAL FAILURE: Analysis Skipped (PDF Path Invalid or Missing)")
            return {
                "paper_summary": "Error: PDF path invalid or missing",
                "risk_signals": [],
                "filename": "unknown"
            }
        
        try:
            # ===== STEP A: Extract Full Text =====
            logger.info("\n[Step A] Extracting full text from PDF...")
            full_text = extract_text_from_pdf(pdf_path, include_metadata=include_metadata)
            
            # ===== GATEKEEPER: Prevent None/Empty from reaching Gemini =====
            if not full_text or len(full_text.strip()) < 100:
                logger.critical("⚠️ CRITICAL FAILURE: PDF appears to be empty or unreadable (Data Missing)")
                return {
                    "paper_summary": "Error: PDF empty or unreadable",
                    "risk_signals": [],
                    "filename": Path(pdf_path).name
                }
            
            char_count = len(full_text)
            word_count = len(full_text.split())
            logger.success(f"Extracted {char_count:,} characters ({word_count:,} words)")
            
            # ===== STEP B: Token Limit Check =====
            logger.info("\n[Step B] Checking token limits...")
            estimated_tokens = self._estimate_token_count(full_text)
            logger.info(f"Accurate token count: {estimated_tokens:,} (limit: {MAX_INPUT_TOKENS:,})")
            
            # AUDIT FIX: Truncate if exceeds limit instead of only chunking
            if estimated_tokens > MAX_INPUT_TOKENS:
                if chunk_if_needed:
                    logger.warning(
                        f"⚠️ PDF exceeds token limit by {estimated_tokens - MAX_INPUT_TOKENS:,} tokens"
                    )
                    logger.info("Splitting into chunks for processing...")
                    return self._mine_evidence_chunked(full_text, Path(pdf_path).name)
                else:
                    # AUDIT FIX: Truncate instead of failing completely
                    logger.warning("PDF exceeds limit and chunking disabled. Truncating to fit.")
                    # Calculate safe character limit (leave 200K tokens for output)
                    safe_token_limit = MAX_INPUT_TOKENS - 200_000
                    safe_char_limit = safe_token_limit * 3  # Conservative estimate
                    full_text = full_text[:safe_char_limit]
                    logger.warning(f"Truncated to {len(full_text):,} characters")
                    estimated_tokens = self._estimate_token_count(full_text)
                    logger.info(f"New token count after truncation: {estimated_tokens:,}")
            
            # ===== STEP C: Mine Dark Data =====
            logger.info("\n[Step C] Mining for dark data...")
            evidence_data = self._extract_evidence_single_pass(full_text)
            
            # Add filename for tracking
            evidence_data["filename"] = Path(pdf_path).name
            
            # ===== STEP D: Summarize Results =====
            logger.info(f"\n{'='*60}")
            risk_signals = evidence_data.get("risk_signals", [])
            logger.success(f"✅ Mining Complete: {len(risk_signals)} risk signals found")
            
            if risk_signals:
                high_risk = sum(1 for e in risk_signals if e.risk_level == "HIGH")
                medium_risk = sum(1 for e in risk_signals if e.risk_level == "MEDIUM")
                low_risk = sum(1 for e in risk_signals if e.risk_level == "LOW")
                
                logger.info(f"   - High Risk: {high_risk}")
                logger.info(f"   - Medium Risk: {medium_risk}")
                logger.info(f"   - Low Risk: {low_risk}")
                
                # Log risk types
                risk_types = {}
                for item in risk_signals:
                    risk_types[item.risk_type] = risk_types.get(item.risk_type, 0) + 1
                
                logger.info("\n   Risk Type Breakdown:")
                for risk_type, count in sorted(risk_types.items(), key=lambda x: x[1], reverse=True):
                    logger.info(f"     - {risk_type}: {count}")
            
            logger.info(f"{'='*60}\n")
            
            return evidence_data
            
        except Exception as e:
            logger.error(f"Evidence mining failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "paper_summary": f"Error: {str(e)}",
                "risk_signals": [],
                "filename": Path(pdf_path).name
            }
            
        except Exception as e:
            logger.error(f"Evidence mining failed: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _estimate_token_count(self, text: str) -> int:
        """
        Estimate token count for text using Gemini's native tokenizer.
        
        AUDIT FIX: Replaced naive character-based estimation with accurate
        Gemini API tokenization to prevent API errors on large PDFs.
        
        Args:
            text: Text to estimate
        
        Returns:
            Accurate token count from Gemini tokenizer
        """
        try:
            # Use Gemini's built-in tokenizer for accurate count
            count = self.llm.count_tokens(text)
            logger.debug(f"Accurate token count: {count:,} tokens")
            return count
            
        except Exception as e:
            logger.warning(f"Token counting failed: {e}. Using conservative fallback.")
            # More conservative fallback than original (was //4, now //3)
            return len(text) // 3
    
    def _extract_evidence_single_pass(self, full_text: str) -> Dict[str, Any]:
        """
        Extract evidence in a single LLM call (for PDFs under token limit).
        
        Args:
            full_text: Complete extracted text from PDF
        
        Returns:
            Dict with 'paper_summary' and 'risk_signals' keys
        """
        user_prompt = f"""Analyze this complete biomedical research paper and extract ALL dark data risk signals.

Focus especially on supplementary materials, appendices, and methods sections.

PAPER TEXT:
{full_text}

Return your findings in the specified JSON format."""
        
        try:
            # Call Gemini with long-context prompt
            response = self.llm.generate_content(
                prompt=user_prompt,
                system_instruction=self.mining_system_prompt
            )
            
            # Parse JSON response (returns Dict with paper_summary and risk_signals)
            evidence_data = self._parse_evidence_response(response)
            
            logger.success(
                f"Extracted summary ({len(evidence_data.get('paper_summary', ''))} chars) "
                f"and {len(evidence_data.get('risk_signals', []))} risk signals"
            )
            return evidence_data
            
        except Exception as e:
            logger.error(f"Evidence extraction failed: {e}")
            raise
    
    def _mine_evidence_chunked(self, full_text: str, filename: str) -> Dict[str, Any]:
        """
        Mine evidence from PDFs that exceed token limit by processing in chunks.
        
        Strategy:
        - Split text into overlapping chunks (to avoid missing evidence at boundaries)
        - Process each chunk separately
        - Deduplicate results across chunks
        - Merge summaries from chunks
        
        Args:
            full_text: Complete extracted text from PDF
            filename: PDF filename for tracking
        
        Returns:
            Dict with merged 'paper_summary' and deduplicated 'risk_signals'
        """
        logger.info("Processing PDF in chunks...")
        
        # Calculate chunk size (leave room for system prompt and response)
        max_chunk_chars = MAX_INPUT_TOKENS * CHARS_PER_TOKEN_ESTIMATE
        overlap_chars = max_chunk_chars // 10  # 10% overlap to catch boundary evidence
        
        chunks = self._split_text_into_chunks(full_text, max_chunk_chars, overlap_chars)
        logger.info(f"Split into {len(chunks)} chunks (overlap: {overlap_chars:,} chars)")
        
        all_risks = []
        all_summaries = []
        
        for i, chunk in enumerate(chunks, start=1):
            logger.info(f"\nProcessing chunk {i}/{len(chunks)}...")
            
            try:
                chunk_data = self._extract_evidence_single_pass(chunk)
                all_risks.extend(chunk_data.get("risk_signals", []))
                
                # Collect summary from each chunk
                chunk_summary = chunk_data.get("paper_summary", "")
                if chunk_summary and chunk_summary not in ["Summary extraction failed.", "Parsing Error"]:
                    all_summaries.append(f"[Chunk {i}] {chunk_summary}")
                
                logger.success(f"Chunk {i}: {len(chunk_data.get('risk_signals', []))} risks found")
                
            except Exception as e:
                logger.error(f"Chunk {i} failed: {e}")
                continue
        
        # Deduplicate evidence items
        deduplicated_risks = self._deduplicate_evidence(all_risks)
        logger.success(
            f"Deduplication: {len(all_risks)} items → {len(deduplicated_risks)} unique items"
        )
        
        # Merge summaries from chunks
        merged_summary = "\n\n".join(all_summaries) if all_summaries else "Summary unavailable (chunked processing)"
        
        return {
            "paper_summary": merged_summary,
            "risk_signals": deduplicated_risks,
            "filename": filename
        }
    
    def _split_text_into_chunks(
        self, 
        text: str, 
        max_chunk_size: int, 
        overlap: int
    ) -> List[str]:
        """
        Split text into overlapping chunks.
        
        Args:
            text: Full text to split
            max_chunk_size: Maximum characters per chunk
            overlap: Number of overlapping characters between chunks
        
        Returns:
            List of text chunks
        """
        chunks = []
        start = 0
        text_length = len(text)
        
        while start < text_length:
            end = min(start + max_chunk_size, text_length)
            chunks.append(text[start:end])
            start += max_chunk_size - overlap
        
        return chunks
    
    def _clean_json_text(self, text: str) -> str:
        """
        Sanitizes LLM output to extract only the valid JSON object.
        Removes Markdown backticks, language identifiers, and surrounding text.
        
        Args:
            text: Raw LLM response text
        
        Returns:
            Cleaned JSON string ready for parsing
        """
        if not text:
            return "{}"
        
        # 1. Strip Markdown code block wrappers (```json ... ```)
        text = re.sub(r"```[a-zA-Z]*\s*", "", text)  # Remove ```json, ```python, etc.
        text = re.sub(r"```\s*", "", text)           # Remove closing ```
        
        # 2. Strip generic whitespace
        text = text.strip()
        
        # 3. Extract the outermost JSON object (Find first '{' and last '}')
        # This ignores any preamble text like "Here is the JSON:"
        start_idx = text.find('{')
        end_idx = text.rfind('}')
        
        if start_idx != -1 and end_idx != -1:
            text = text[start_idx : end_idx + 1]
        
        return text
    
    def _parse_evidence_response(self, response: str) -> Dict[str, Any]:
        """
        Parse LLM JSON response into standardized Dict format.
        
        PROTOCOL UPGRADE: Returns Dict with 'paper_summary' and 'risk_signals' keys.
        Handles legacy List format for backward compatibility.
        
        Args:
            response: Raw LLM response text
        
        Returns:
            Dict with:
                - paper_summary: str (comprehensive study overview)
                - risk_signals: List[EvidenceItem] (risk findings)
        """
        try:
            # --- THE FIX: IRONCLAD JSON CLEANER ---
            # Use the new regex-based cleaner to remove all Markdown formatting
            cleaned_text = self._clean_json_text(response)
            
            # Parse JSON
            data = json.loads(cleaned_text)
            # ---------------------------------------
            
            # --- PROTOCOL FIX: STANDARDIZE OUTPUT ---
            # Ensure output is always a Dictionary with 'paper_summary' and 'risk_signals'
            standardized_data = {
                "paper_summary": "",
                "risk_signals": []
            }

            if isinstance(data, list):
                # Legacy/Fallback handling: If LLM returns a list, assume it's just risks
                logger.warning("⚠️ Legacy List Format Detected - Converting to Protocol")
                standardized_data["risk_signals"] = data
                standardized_data["paper_summary"] = "Summary not provided by LLM (Legacy List Format)."
            
            elif isinstance(data, dict):
                # Extract flexible keys to handle schema drift
                standardized_data["paper_summary"] = (
                    data.get("paper_summary") or 
                    data.get("summary") or 
                    data.get("overview") or 
                    "Summary extraction failed."
                )
                
                # Handle multiple possible key names for risk signals
                raw_risks = (
                    data.get("risk_signals") or 
                    data.get("evidence_items") or 
                    data.get("findings") or 
                    data.get("evidence") or
                    data.get("items") or
                    data.get("results") or
                    []
                )
                
                # Convert raw risk dicts to EvidenceItem objects
                for item_data in raw_risks:
                    try:
                        standardized_data["risk_signals"].append(EvidenceItem(
                            source=item_data.get("source", "Unknown"),
                            page_estimate=item_data.get("page_estimate", "Unknown"),
                            quote=item_data.get("quote", ""),
                            risk_level=item_data.get("risk_level", "LOW"),
                            risk_type=item_data.get("risk_type", "other"),
                            explanation=item_data.get("explanation", "")
                        ))
                    except Exception as e:
                        logger.warning(f"Failed to parse evidence item: {e}")
                        continue
            
            else:
                logger.error(f"Unexpected data type: {type(data)}")
                standardized_data["paper_summary"] = "Parsing Error: Unexpected data type"
            
            # Log extraction success
            logger.success(
                f"✅ Protocol Extraction: Summary={len(standardized_data['paper_summary'])} chars, "
                f"Risks={len(standardized_data['risk_signals'])} items"
            )
            
            return standardized_data
            # --------------------

        except json.JSONDecodeError as e:
            logger.critical(f"⚠️ CRITICAL FAILURE: Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {response[:500]}...")
            # Return safe default to prevent pipeline crash
            return {"paper_summary": "JSON Parsing Error", "risk_signals": []}
        
        except Exception as e:
            logger.critical(f"⚠️ CRITICAL FAILURE: Error parsing evidence response: {e}")
            # Return safe default to prevent pipeline crash
            return {"paper_summary": "Parsing Error", "risk_signals": []}
    
    def _deduplicate_evidence(self, evidence_items: List[EvidenceItem]) -> List[EvidenceItem]:
        """
        Remove duplicate evidence items (from overlapping chunks).
        
        Uses quote text as deduplication key.
        
        Args:
            evidence_items: List of possibly duplicate items
        
        Returns:
            List of unique items
        """
        seen_quotes = set()
        unique_items = []
        
        for item in evidence_items:
            # Use first 100 chars of quote as fingerprint
            quote_fingerprint = item.quote[:100].lower().strip()
            
            if quote_fingerprint not in seen_quotes:
                seen_quotes.add(quote_fingerprint)
                unique_items.append(item)
        
        return unique_items
    
    def generate_evidence_report(
        self, 
        evidence_items: List[EvidenceItem],
        pdf_path: Optional[str] = None
    ) -> str:
        """
        Generate human-readable dark data evidence report.
        
        Args:
            evidence_items: List of EvidenceItem objects
            pdf_path: Optional path to source PDF for report header
        
        Returns:
            Formatted markdown report
        """
        report_lines = [
            "# Supplementary Material Dark Data Report",
            ""
        ]
        
        if pdf_path:
            report_lines.append(f"**Source:** {Path(pdf_path).name}")
            report_lines.append("")
        
        report_lines.extend([
            f"**Total Risk Signals:** {len(evidence_items)}",
            f"**High Risk:** {sum(1 for e in evidence_items if e.risk_level == 'HIGH')}",
            f"**Medium Risk:** {sum(1 for e in evidence_items if e.risk_level == 'MEDIUM')}",
            f"**Low Risk:** {sum(1 for e in evidence_items if e.risk_level == 'LOW')}",
            "",
            "---",
            ""
        ])
        
        # Group by risk level
        high_risk = [e for e in evidence_items if e.risk_level == "HIGH"]
        medium_risk = [e for e in evidence_items if e.risk_level == "MEDIUM"]
        low_risk = [e for e in evidence_items if e.risk_level == "LOW"]
        
        # Report high risk items first
        if high_risk:
            report_lines.append("## 🚨 High Risk Signals")
            report_lines.append("")
            
            for i, item in enumerate(high_risk, 1):
                report_lines.append(f"### {i}. {item.risk_type.upper()}")
                report_lines.append(f"**Source:** {item.source} ({item.page_estimate})")
                report_lines.append(f"**Quote:**")
                report_lines.append(f"> {item.quote}")
                report_lines.append(f"**Analysis:** {item.explanation}")
                report_lines.append("")
        
        # Medium risk
        if medium_risk:
            report_lines.append("## ⚠️ Medium Risk Signals")
            report_lines.append("")
            
            for i, item in enumerate(medium_risk, 1):
                report_lines.append(f"### {i}. {item.risk_type.upper()}")
                report_lines.append(f"**Source:** {item.source} ({item.page_estimate})")
                report_lines.append(f"**Quote:**")
                report_lines.append(f"> {item.quote}")
                report_lines.append(f"**Analysis:** {item.explanation}")
                report_lines.append("")
        
        # Low risk summary
        if low_risk:
            report_lines.append("## ℹ️ Low Risk Signals")
            report_lines.append("")
            report_lines.append(f"Found {len(low_risk)} minor issues:")
            report_lines.append("")
            for item in low_risk:
                report_lines.append(f"- **{item.risk_type}** ({item.source}): {item.explanation}")
            report_lines.append("")
        
        return "\n".join(report_lines)


def create_agent() -> EvidenceMinerAgent:
    """
    Factory function to create an EvidenceMinerAgent instance.
    
    Returns:
        EvidenceMinerAgent: Initialized agent ready for use
    
    Example:
        >>> agent = create_agent()
        >>> evidence = agent.mine_evidence("research_paper.pdf")
    """
    return EvidenceMinerAgent()
