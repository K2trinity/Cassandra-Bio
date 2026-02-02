"""
Forensic Auditor Agent - Bio-Short-Seller Scientific Image Forensic Analyzer

This agent analyzes images from biomedical research papers to detect potential
data manipulation, image splicing, or fabrication.

Core capabilities:
- Extract figures/charts from PDF research papers
- Apply Gemini Vision for forensic analysis of scientific images
- Detect Western blot splicing, cloned data points, inconsistent error bars
- Flag suspicious patterns indicating potential data fabrication

Workflow:
1. Extract images from PDF using PyMuPDF
2. Filter out small logos/icons (keep only scientific figures)
3. Send each figure to Gemini Vision with forensic analysis prompt
4. Aggregate suspicious findings into audit report
"""

import os
import json as json_module
from pathlib import Path
from typing import List, Dict, Optional
from dataclasses import dataclass
from loguru import logger

from src.llms import create_forensic_client
from src.tools import extract_images_from_pdf


@dataclass
class ImageAuditResult:
    """
    Result of forensic analysis for a single image.
    
    Attributes:
        image_id: Identifier for the image (filename or index)
        image_path: Full path to the image file
        page_num: PDF page number where image was found
        status: 'CLEAN', 'SUSPICIOUS', or 'ERROR'
        tampering_risk_score: Probability of data tampering/manipulation (0.0=clean, 1.0=definitely tampered)
        findings: Detailed description of suspicious patterns
        raw_analysis: Full LLM response for debugging
        model_confidence: Model's certainty about its judgment (optional, for self-reflection)
    """
    image_id: str
    image_path: str
    page_num: int
    status: str  # CLEAN, SUSPICIOUS, ERROR
    tampering_risk_score: float  # 0.0 to 1.0 (0.0 = No tampering detected, 1.0 = Definite tampering)
    findings: str
    raw_analysis: str
    model_confidence: float = 1.0  # Model's self-assessed reliability (default: fully confident)


class ForensicAuditorAgent:
    """
    Scientific Image Forensic Auditor
    
    Uses Gemini Vision to analyze scientific figures from biomedical papers
    for signs of data manipulation or fabrication.
    """
    
    def __init__(self):
        """Initialize Forensic Auditor with Gemini Vision-capable client."""
        
        # Initialize LLM client (Gemini Pro with vision capabilities)
        self.llm = create_forensic_client()
        logger.info("Forensic Auditor initialized with Gemini Vision")
        
        # AUDIT FIX: Load system prompt from external file for maintainability
        from pathlib import Path
        prompt_path = Path(__file__).parent.parent / "src" / "prompts" / "forensic_auditor" / "system.txt"
        if prompt_path.exists():
            self.forensic_system_prompt = prompt_path.read_text(encoding='utf-8')
            logger.debug("Loaded forensic auditor system prompt from file")
        else:
            logger.warning(f"Prompt file not found: {prompt_path}, using fallback")
            self.forensic_system_prompt = """You are a world-class scientific image forensic expert specializing in detecting data manipulation in biomedical research papers.

Your task is to analyze scientific figures and charts for signs of fabrication or manipulation. Focus on:

**Western Blots & Gel Images:**
- Image splicing or copy-pasting (look for repeated patterns, identical bands)
- Inconsistent backgrounds or lighting between lanes
- Sharp edges or discontinuities suggesting digital manipulation
- Duplicated or mirrored sections

**Data Charts & Graphs:**
- Error bars that are suspiciously identical across different groups
- Data points that don't match the claimed trend line or statistical fit
- Inconsistent resolution or quality between different parts of the figure
- Impossible or mathematically inconsistent values

**Microscopy Images:**
- Cloned or duplicated regions (copy-paste artifacts)
- Inconsistent magnification scales
- Suspiciously perfect alignment or symmetry
- Digital enhancement artifacts

**OUTPUT FORMAT:**
Return your analysis in this exact JSON format:
```json
{
  "status": "CLEAN" or "SUSPICIOUS",
  "confidence": 0.0 to 1.0,
  "findings": "Detailed description of what you found (or 'No suspicious patterns detected' if clean)"
}
```

**CRITICAL RULES:**
- Only mark as SUSPICIOUS if you have HIGH confidence (≥0.7)
- Be conservative - scientific figures can have legitimate patterns
- Provide specific, actionable descriptions for suspicious findings
- If you're uncertain, mark as CLEAN with lower confidence
"""
    
    def audit_paper(
        self, 
        pdf_path: str,
        min_image_size: int = 200,
        output_dir: Optional[str] = None
    ) -> List[ImageAuditResult]:
        """
        Perform forensic audit on a scientific paper PDF.
        
        Args:
            pdf_path: Path to the PDF file to audit
            min_image_size: Minimum width/height in pixels for images to analyze (default: 200)
            output_dir: Directory to save extracted images (default: temp directory)
        
        Returns:
            List of ImageAuditResult objects containing forensic analysis for each figure
        
        Workflow:
            Step A: Extract images from PDF
            Step B: Filter small icons/logos
            Step C: Analyze each significant figure with Gemini Vision
            Step D: Aggregate suspicious findings
        
        Example:
            >>> agent = ForensicAuditorAgent()
            >>> results = agent.audit_paper("suspicious_paper.pdf")
            >>> suspicious = [r for r in results if r.status == 'SUSPICIOUS']
            >>> print(f"Found {len(suspicious)} suspicious figures")
            >>> for r in suspicious:
            ...     print(f"Figure {r.image_id}: {r.findings}")
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🔬 Forensic Audit: {Path(pdf_path).name}")
        logger.info(f"{'='*60}")
        
        try:
            # ===== STEP A: Extract Images =====
            logger.info("\n[Step A] Extracting images from PDF...")
            image_paths = extract_images_from_pdf(
                pdf_path,
                output_dir=output_dir,
                min_width=min_image_size,
                min_height=min_image_size
            )
            
            if not image_paths:
                logger.warning("No significant images found in PDF")
                return []
            
            # ===== STEP B: Filter (already done by extract_images_from_pdf) =====
            logger.info(f"\n[Step B] Analyzing {len(image_paths)} significant figures...")
            
            # ===== STEP C: Vision Analysis =====
            audit_results = []
            
            for idx, image_path in enumerate(image_paths, start=1):
                logger.info(f"\n  Analyzing figure {idx}/{len(image_paths)}: {Path(image_path).name}")
                
                try:
                    result = self._analyze_single_image(image_path, idx)
                    audit_results.append(result)
                    
                    # Log result with unambiguous terminology
                    if result.status == "SUSPICIOUS":
                        logger.warning(
                            f"    ⚠️  SUSPICIOUS (tampering risk: {result.tampering_risk_score:.2f})\n"
                            f"    Findings: {result.findings[:150]}..."
                        )
                    elif result.status == "CLEAN":
                        if result.tampering_risk_score == 0.0:
                            # 🎯 Perfect clean - zero anomalies detected
                            logger.success(f"    ✅ CLEAN (tampering risk: 0.00 - zero anomalies detected)")
                        else:
                            # Clean but with minor anomalies
                            logger.success(f"    ✅ CLEAN (tampering risk: {result.tampering_risk_score:.2f} - below threshold)")
                    else:
                        logger.info(f"    ℹ️  {result.status} (tampering risk: {result.tampering_risk_score:.2f})")
                    
                except Exception as e:
                    logger.error(f"    ❌ Analysis failed: {e}")
                    audit_results.append(ImageAuditResult(
                        image_id=f"figure_{idx:03d}",
                        image_path=image_path,
                        page_num=self._extract_page_num(image_path),
                        status="ERROR",
                        tampering_risk_score=0.0,
                        findings=f"Analysis failed: {str(e)}",
                        raw_analysis="",
                        model_confidence=0.0  # Error state = no confidence
                    ))
            
            # ===== STEP D: Aggregation =====
            logger.info(f"\n{'='*60}")
            suspicious_count = sum(1 for r in audit_results if r.status == "SUSPICIOUS")
            logger.info(f"✅ Audit Complete: {len(audit_results)} figures analyzed")
            logger.info(f"   - Clean: {len(audit_results) - suspicious_count}")
            logger.info(f"   - Suspicious: {suspicious_count}")
            logger.info(f"{'='*60}\n")
            
            return audit_results
            
        except Exception as e:
            logger.error(f"Forensic audit failed: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _analyze_single_image(self, image_path: str, image_id: int) -> ImageAuditResult:
        """
        Analyze a single image using Gemini Vision.
        
        Args:
            image_path: Path to the image file
            image_id: Numeric identifier for the image
        
        Returns:
            ImageAuditResult with forensic analysis
        """
        # --- FIX: Guard Clause for Image Loading (Fail-Fast Pattern) ---
        try:
            # 1. Attempt to load image
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            # 2. Validate image data is not empty
            if image_bytes is None or len(image_bytes) == 0:
                logger.warning(f"⚠️ Skipping analysis for {image_path}: Image data is empty")
                return ImageAuditResult(
                    image_id=f"figure_{image_id:03d}",
                    image_path=image_path,
                    page_num=self._extract_page_num(image_path),
                    status="ERROR",
                    tampering_risk_score=0.0,
                    findings="Analysis Skipped: Image data is empty (Load Failed)",
                    raw_analysis="Image loading failed - no data",
                    model_confidence=0.0
                )
        except (FileNotFoundError, IOError, OSError) as e:
            logger.warning(f"⚠️ Skipping analysis for {image_path}: {type(e).__name__}: {e}")
            return ImageAuditResult(
                image_id=f"figure_{image_id:03d}",
                image_path=image_path,
                page_num=self._extract_page_num(image_path),
                status="ERROR",
                tampering_risk_score=0.0,
                findings=f"Analysis Skipped: Image Load Failed ({type(e).__name__})",
                raw_analysis=str(e),
                model_confidence=0.0
            )
        # ---------------------------------------------------------------
        
        # Construct user prompt
        user_prompt = """Analyze this scientific figure for signs of data manipulation or fabrication.

Follow the forensic analysis guidelines in the system prompt and return your analysis in the specified JSON format."""
        
        try:
            # Call Gemini Vision API
            # Note: GeminiClient.generate_content() accepts image bytes directly
            response = self.llm.generate_content(
                prompt=user_prompt,
                images=[image_bytes],  # Pass image as bytes (not base64)
                system_instruction=self.forensic_system_prompt
            )
            
            # Parse JSON response
            # Extract JSON from response (handle markdown code blocks)
            response_text = response.strip()
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            parsed_analysis = json_module.loads(response_text)
            
            # Extract tampering risk score and status (with robust parsing)
            raw_risk_score = parsed_analysis.get("confidence", 0.0)  # API still uses "confidence" field
            tampering_risk_score = self._parse_risk_score(raw_risk_score)
            status = parsed_analysis.get("status", "ERROR")
            
            # Extract model's self-assessed reliability (if provided)
            raw_model_confidence = parsed_analysis.get("model_confidence", 1.0)
            model_confidence = self._parse_risk_score(raw_model_confidence)  # Use same parser
            
            # 🛡️ Self-Reflection Logic: Validate tampering risk scores
            if status == "CLEAN" and tampering_risk_score == 0.0:
                logger.debug(f"✓ Model found zero anomalies (tampering_risk_score=0.0)")
            elif status == "CLEAN" and tampering_risk_score > 0.5:
                logger.warning(f"⚠️ Inconsistent: CLEAN status but high tampering risk: {tampering_risk_score:.2f}")
                logger.debug(f"Raw response (first 500 chars): {response[:500]}")
                logger.debug(f"Parsed JSON: {parsed_analysis}")
            elif status == "SUSPICIOUS" and tampering_risk_score < 0.3:
                logger.warning(f"⚠️ Inconsistent: SUSPICIOUS status but low tampering risk: {tampering_risk_score:.2f}")
                logger.debug(f"Raw response (first 500 chars): {response[:500]}")
            
            # Log model confidence separately if provided
            if "model_confidence" in parsed_analysis:
                logger.debug(f"Model self-reflection: {model_confidence:.2f} certainty in its judgment")
            
            return ImageAuditResult(
                image_id=f"figure_{image_id:03d}",
                image_path=image_path,
                page_num=self._extract_page_num(image_path),
                status=status,
                tampering_risk_score=tampering_risk_score,
                findings=parsed_analysis.get("findings", "No analysis provided"),
                raw_analysis=response,
                model_confidence=model_confidence
            )
            
        except json_module.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            # Fallback: treat as error if parsing fails
            return ImageAuditResult(
                image_id=f"figure_{image_id:03d}",
                image_path=image_path,
                page_num=self._extract_page_num(image_path),
                status="ERROR",
                tampering_risk_score=0.0,
                findings=f"JSON parsing error: {str(e)}",
                raw_analysis=response if 'response' in locals() else "",
                model_confidence=0.0  # Parsing error = no confidence
            )
        
        except Exception as e:
            logger.error(f"Vision analysis failed: {e}")
            raise
    
    def _parse_risk_score(self, raw_score) -> float:
        """
        Robustly parse risk score from LLM output.
        
        Handles both numeric values and text labels ("high", "medium", "low").
        
        Args:
            raw_score: Raw score from LLM (can be float, int, or string)
        
        Returns:
            Float between 0.0 and 1.0
        """
        # 1. Try direct float conversion
        try:
            return float(str(raw_score).strip())
        except (ValueError, TypeError, AttributeError):
            pass
        
        # 2. Handle Text Labels (The "High" case)
        clean_text = str(raw_score).lower().strip()
        if 'high' in clean_text:
            return 0.9
        if 'medium' in clean_text or 'moderate' in clean_text:
            return 0.5
        if 'low' in clean_text:
            return 0.1
        if 'clean' in clean_text or 'safe' in clean_text or 'none' in clean_text:
            return 0.0
        
        # 3. Fallback
        logger.warning(f"Could not parse risk score: '{raw_score}', defaulting to 0.0")
        return 0.0
    
    def _extract_page_num(self, image_path: str) -> int:
        """
        Extract page number from image filename.
        
        Expected format: figure_001_p3.png -> page 3
        """
        import re
        filename = Path(image_path).name
        match = re.search(r'_p(\d+)', filename)
        if match:
            return int(match.group(1))
        return 0
    
    def generate_audit_report(self, audit_results: List[ImageAuditResult]) -> str:
        """
        Generate human-readable forensic audit report.
        
        Args:
            audit_results: List of ImageAuditResult objects
        
        Returns:
            Formatted markdown report
        """
        report_lines = [
            "# Scientific Image Forensic Audit Report",
            "",
            f"**Total Figures Analyzed:** {len(audit_results)}",
            f"**Suspicious Findings:** {sum(1 for r in audit_results if r.status == 'SUSPICIOUS')}",
            f"**Clean Figures:** {sum(1 for r in audit_results if r.status == 'CLEAN')}",
            "",
            "---",
            ""
        ]
        
        # Group by status
        suspicious = [r for r in audit_results if r.status == "SUSPICIOUS"]
        clean = [r for r in audit_results if r.status == "CLEAN"]
        errors = [r for r in audit_results if r.status == "ERROR"]
        
        # Report suspicious findings first
        if suspicious:
            report_lines.append("## ⚠️ Suspicious Figures")
            report_lines.append("")
            
            for result in sorted(suspicious, key=lambda x: x.confidence, reverse=True):
                report_lines.append(f"### {result.image_id} (Page {result.page_num})")
                report_lines.append(f"**Confidence:** {result.confidence:.2f}")
                report_lines.append(f"**Findings:** {result.findings}")
                report_lines.append(f"**Image:** `{result.image_path}`")
                report_lines.append("")
        
        # Summary of clean figures
        if clean:
            report_lines.append("## ✅ Clean Figures")
            report_lines.append("")
            report_lines.append(f"The following {len(clean)} figures showed no signs of manipulation:")
            report_lines.append("")
            for result in clean:
                report_lines.append(f"- {result.image_id} (Page {result.page_num}) - Confidence: {result.confidence:.2f}")
            report_lines.append("")
        
        # Errors
        if errors:
            report_lines.append("## ❌ Analysis Errors")
            report_lines.append("")
            for result in errors:
                report_lines.append(f"- {result.image_id}: {result.findings}")
            report_lines.append("")
        
        return "\n".join(report_lines)


def create_agent() -> ForensicAuditorAgent:
    """
    Factory function to create a ForensicAuditorAgent instance.
    
    Returns:
        ForensicAuditorAgent: Initialized agent ready for use
    
    Example:
        >>> agent = create_agent()
        >>> results = agent.audit_paper("research_paper.pdf")
    """
    return ForensicAuditorAgent()
