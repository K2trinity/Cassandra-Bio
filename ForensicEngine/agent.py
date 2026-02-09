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
from src.utils.stream_validator import StreamValidator


@dataclass
class ImageAuditResult:
    """
    Result of forensic analysis for a single image.
    
    Attributes:
        image_id: Identifier for the image (filename or index)
        image_path: Full path to the image file
        page_num: PDF page number where image was found
        status: 'CLEAN', 'SUSPICIOUS', or 'ERROR'
        tampering_risk_score: Probability of data tampering/manipulation (0.0=clean, 1.0=definitely tampered, None=analysis failed)
        findings: Detailed description of suspicious patterns
        raw_analysis: Full LLM response for debugging
        model_confidence: Model's certainty about its judgment (optional, for self-reflection)
    """
    image_id: str
    image_path: str
    page_num: int
    status: str  # CLEAN, SUSPICIOUS, ERROR, FAILURE
    tampering_risk_score: Optional[float]  # 0.0 to 1.0 OR None if analysis failed
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
        
        # ===== GATEKEEPER CHECK: Prevent Null Pointer Crashes =====
        if pdf_path is None or not Path(pdf_path).exists():
            logger.critical("⚠️ CRITICAL FAILURE: Analysis Skipped (PDF Path Invalid or Missing)")
            return [ImageAuditResult(
                image_id="N/A",
                image_path="",
                page_num=0,
                status="FAILURE",
                tampering_risk_score=None,  # None = Analysis Never Happened
                findings="CRITICAL: PDF path is invalid or file does not exist",
                raw_analysis="",
                model_confidence=0.0
            )]
        
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
            ssl_error_count = 0  # 🔥 Track SSL failures
            consecutive_failures = 0  # 🔥 Circuit breaker
            
            for idx, image_path in enumerate(image_paths, start=1):
                logger.info(f"\n  Analyzing figure {idx}/{len(image_paths)}: {Path(image_path).name}")
                
                # 🔥 Circuit breaker: Skip remaining if too many consecutive SSL failures
                if consecutive_failures >= 5:
                    logger.warning(f"⚠️ Skipping remaining {len(image_paths) - idx + 1} images due to network instability")
                    break
                
                try:
                    result = self._analyze_single_image(image_path, idx)
                    audit_results.append(result)
                    consecutive_failures = 0  # Reset on success
                    
                    # Log result with unambiguous terminology
                    if result.status == "SUSPICIOUS":
                        # 🔥 FIX: Handle None tampering_risk_score
                        risk_str = f"{result.tampering_risk_score:.2f}" if result.tampering_risk_score is not None else "N/A"
                        logger.warning(
                            f"    ⚠️  SUSPICIOUS (tampering risk: {risk_str})\n"
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
                        # 🔥 FIX: Handle None tampering_risk_score
                        risk_str = f"{result.tampering_risk_score:.2f}" if result.tampering_risk_score is not None else "N/A"
                        logger.info(f"    ℹ️  {result.status} (tampering risk: {risk_str})")
                    
                except Exception as e:
                    error_msg = str(e)
                    
                    # 🔥 Detect SSL errors for circuit breaker
                    if "SSL" in error_msg or "EOF" in error_msg or "Connection" in error_msg:
                        ssl_error_count += 1
                        consecutive_failures += 1
                        logger.error(f"    ❌ Network error ({ssl_error_count} total): {error_msg[:100]}")
                    else:
                        consecutive_failures = 0  # Reset for non-network errors
                        logger.critical(f"    ❌ CRITICAL FAILURE: Analysis Skipped (Data Missing) - {e}")
                    
                    audit_results.append(ImageAuditResult(
                        image_id=f"figure_{idx:03d}",
                        image_path=image_path,
                        page_num=self._extract_page_num(image_path),
                        status="ERROR",
                        tampering_risk_score=None,  # None = Analysis Failed, NOT "Zero Risk"
                        findings=f"CRITICAL: Analysis failed: {str(e)}",
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
                logger.critical(f"⚠️ CRITICAL FAILURE: Analysis Skipped (Image Data Missing) - {image_path}")
                return ImageAuditResult(
                    image_id=f"figure_{image_id:03d}",
                    image_path=image_path,
                    page_num=self._extract_page_num(image_path),
                    status="ERROR",
                    tampering_risk_score=None,  # None = Analysis Failed, NOT "Zero Risk"
                    findings="CRITICAL: Image data is empty (Load Failed)",
                    raw_analysis="Image loading failed - no data",
                    model_confidence=0.0
                )
        except (FileNotFoundError, IOError, OSError) as e:
            logger.critical(f"⚠️ CRITICAL FAILURE: Analysis Skipped (File Error) - {image_path}: {type(e).__name__}: {e}")
            return ImageAuditResult(
                image_id=f"figure_{image_id:03d}",
                image_path=image_path,
                page_num=self._extract_page_num(image_path),
                status="ERROR",
                tampering_risk_score=None,  # None = Analysis Failed, NOT "Zero Risk"
                findings=f"CRITICAL: Image Load Failed ({type(e).__name__})",
                raw_analysis=str(e),
                model_confidence=0.0
            )
        # ---------------------------------------------------------------
        
        # Construct user prompt
        user_prompt = """Analyze this scientific figure for signs of data manipulation or fabrication.

Follow the forensic analysis guidelines in the system prompt and return your analysis in the specified JSON format."""
        
        try:
            # 🔥 ENHANCED: Use structured JSON output for reliable parsing
            # Define expected schema inline to avoid import issues
            output_schema = {
                "type": "object",
                "properties": {
                    "image_id": {"type": "string"},
                    "status": {
                        "type": "string",
                        "enum": ["SUSPICIOUS", "CLEAN", "INCONCLUSIVE", "ERROR"]
                    },
                    "tampering_probability": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0
                    },
                    "findings": {"type": "string"},
                    "page_number": {"type": "integer"}
                },
                "required": ["image_id", "status", "tampering_probability", "findings"]
            }
            
            # Call Gemini Vision API with forced JSON output
            # Note: GeminiClient.generate_json() guarantees JSON response
            response_data = self.llm.generate_json(
                prompt=user_prompt,
                images=[image_bytes],  # Pass image as bytes (not base64)
                response_schema=output_schema,
                system_instruction=self.forensic_system_prompt
            )
            
            # === PROTOCOL UPGRADE: Use StreamValidator Middleware ===
            # Since generate_json returns dict, we still validate it for safety
            validated_payload = StreamValidator.validate_forensic_payload(response_data)
            
            # Extract validated fields
            status = validated_payload["status"]
            tampering_risk_score = validated_payload["score"]
            findings = validated_payload["findings"]
            page_num = validated_payload.get("page_number") or self._extract_page_num(image_path)
            
            # 🔥 FIX: Save JSON response for raw_analysis
            import json as json_module
            raw_response = json_module.dumps(response_data, indent=2)
            
            # Model confidence defaults to 1.0 (high confidence)
            model_confidence = 1.0
            
            # 🛡️ Validation: Check for inconsistent forensic results
            if status == "CLEAN" and tampering_risk_score == 0.0:
                logger.debug(f"✓ Model found zero anomalies (tampering_risk_score=0.0)")
            elif status == "CLEAN" and tampering_risk_score > 0.5:
                logger.warning(f"⚠️ Inconsistent: CLEAN status but high tampering risk: {tampering_risk_score:.2f}")
            elif status == "SUSPICIOUS" and tampering_risk_score < 0.3:
                logger.warning(f"⚠️ Inconsistent: SUSPICIOUS status but low tampering risk: {tampering_risk_score:.2f}")
            
            return ImageAuditResult(
                image_id=f"figure_{image_id:03d}",
                image_path=image_path,
                page_num=page_num,
                status=status,
                tampering_risk_score=tampering_risk_score,
                findings=findings,
                raw_analysis=raw_response,
                model_confidence=model_confidence
            )
            
        except Exception as e:
            # StreamValidator should catch most errors, but handle edge cases
            logger.error(f"Vision analysis failed: {e}")
            return ImageAuditResult(
                image_id=f"figure_{image_id:03d}",
                image_path=image_path,
                page_num=self._extract_page_num(image_path),
                status="ERROR",
                tampering_risk_score=None,
                findings=f"Analysis error: {str(e)}",
                raw_analysis="",
                model_confidence=0.0
            )
    
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
