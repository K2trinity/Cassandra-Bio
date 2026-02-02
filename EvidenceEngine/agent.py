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
from pathlib import Path
from typing import List, Dict, Optional
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

**OUTPUT FORMAT:**
Return your findings as a JSON array:
```json
{
  "evidence_items": [
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
- Be thorough - scan the ENTIRE text including all supplementary sections
- Extract EXACT quotes (do not paraphrase)
- Focus on negative/neutral results, not positive claims
- If no significant dark data found, return empty array
"""
    
    def mine_evidence(
        self, 
        pdf_path: str,
        include_metadata: bool = True,
        chunk_if_needed: bool = True
    ) -> List[EvidenceItem]:
        """
        Mine dark data from a research paper PDF.
        
        Args:
            pdf_path: Path to the PDF file to analyze
            include_metadata: Include PDF metadata in extracted text
            chunk_if_needed: If PDF exceeds token limit, process in chunks
        
        Returns:
            List of EvidenceItem objects containing extracted risk signals
        
        Workflow:
            Step A: Extract full text from PDF
            Step B: Check token count and chunk if necessary
            Step C: Mine for dark data using Gemini
            Step D: Parse and structure evidence items
        
        Example:
            >>> agent = EvidenceMinerAgent()
            >>> evidence = agent.mine_evidence("clinical_trial_paper.pdf")
            >>> high_risk = [e for e in evidence if e.risk_level == 'HIGH']
            >>> print(f"Found {len(high_risk)} high-risk signals")
            >>> for e in high_risk:
            ...     print(f"{e.risk_type}: {e.quote[:100]}...")
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"📄 Evidence Mining: {Path(pdf_path).name}")
        logger.info(f"{'='*60}")
        
        try:
            # ===== STEP A: Extract Full Text =====
            logger.info("\n[Step A] Extracting full text from PDF...")
            full_text = extract_text_from_pdf(pdf_path, include_metadata=include_metadata)
            
            if not full_text or len(full_text.strip()) < 100:
                logger.warning("PDF appears to be empty or unreadable")
                return []
            
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
                    return self._mine_evidence_chunked(full_text)
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
            evidence_items = self._extract_evidence_single_pass(full_text)
            
            # ===== STEP D: Summarize Results =====
            logger.info(f"\n{'='*60}")
            logger.success(f"✅ Mining Complete: {len(evidence_items)} risk signals found")
            
            if evidence_items:
                high_risk = sum(1 for e in evidence_items if e.risk_level == "HIGH")
                medium_risk = sum(1 for e in evidence_items if e.risk_level == "MEDIUM")
                low_risk = sum(1 for e in evidence_items if e.risk_level == "LOW")
                
                logger.info(f"   - High Risk: {high_risk}")
                logger.info(f"   - Medium Risk: {medium_risk}")
                logger.info(f"   - Low Risk: {low_risk}")
                
                # Log risk types
                risk_types = {}
                for item in evidence_items:
                    risk_types[item.risk_type] = risk_types.get(item.risk_type, 0) + 1
                
                logger.info("\n   Risk Type Breakdown:")
                for risk_type, count in sorted(risk_types.items(), key=lambda x: x[1], reverse=True):
                    logger.info(f"     - {risk_type}: {count}")
            
            logger.info(f"{'='*60}\n")
            
            return evidence_items
            
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
    
    def _extract_evidence_single_pass(self, full_text: str) -> List[EvidenceItem]:
        """
        Extract evidence in a single LLM call (for PDFs under token limit).
        
        Args:
            full_text: Complete extracted text from PDF
        
        Returns:
            List of EvidenceItem objects
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
            
            # Parse JSON response
            evidence_items = self._parse_evidence_response(response)
            
            logger.success(f"Extracted {len(evidence_items)} evidence items")
            return evidence_items
            
        except Exception as e:
            logger.error(f"Evidence extraction failed: {e}")
            raise
    
    def _mine_evidence_chunked(self, full_text: str) -> List[EvidenceItem]:
        """
        Mine evidence from PDFs that exceed token limit by processing in chunks.
        
        Strategy:
        - Split text into overlapping chunks (to avoid missing evidence at boundaries)
        - Process each chunk separately
        - Deduplicate results across chunks
        
        Args:
            full_text: Complete extracted text from PDF
        
        Returns:
            List of deduplicated EvidenceItem objects
        """
        logger.info("Processing PDF in chunks...")
        
        # Calculate chunk size (leave room for system prompt and response)
        max_chunk_chars = MAX_INPUT_TOKENS * CHARS_PER_TOKEN_ESTIMATE
        overlap_chars = max_chunk_chars // 10  # 10% overlap to catch boundary evidence
        
        chunks = self._split_text_into_chunks(full_text, max_chunk_chars, overlap_chars)
        logger.info(f"Split into {len(chunks)} chunks (overlap: {overlap_chars:,} chars)")
        
        all_evidence = []
        
        for i, chunk in enumerate(chunks, start=1):
            logger.info(f"\nProcessing chunk {i}/{len(chunks)}...")
            
            try:
                chunk_evidence = self._extract_evidence_single_pass(chunk)
                all_evidence.extend(chunk_evidence)
                logger.success(f"Chunk {i}: {len(chunk_evidence)} items found")
                
            except Exception as e:
                logger.error(f"Chunk {i} failed: {e}")
                continue
        
        # Deduplicate evidence items
        deduplicated = self._deduplicate_evidence(all_evidence)
        logger.success(
            f"Deduplication: {len(all_evidence)} items → {len(deduplicated)} unique items"
        )
        
        return deduplicated
    
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
    
    def _parse_evidence_response(self, response: str) -> List[EvidenceItem]:
        """
        Parse LLM JSON response into EvidenceItem objects.
        
        Args:
            response: Raw LLM response text
        
        Returns:
            List of EvidenceItem objects
        """
        try:
            # Extract JSON from markdown code blocks if present
            response_text = response.strip()
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            # Parse JSON
            data = json.loads(response_text)
            
            # Extract evidence items
            evidence_items = []
            for item_data in data.get("evidence_items", []):
                try:
                    evidence_items.append(EvidenceItem(
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
            
            return evidence_items
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON response: {e}")
            logger.debug(f"Raw response: {response[:500]}...")
            return []
        
        except Exception as e:
            logger.error(f"Error parsing evidence response: {e}")
            return []
    
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
