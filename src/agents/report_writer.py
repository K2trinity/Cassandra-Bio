"""
Report Writer Agent - Bio-Short-Seller Biomedical Due Diligence Analyst

This agent synthesizes evidence from BioHarvestEngine, ForensicEngine, and EvidenceEngine
into a comprehensive biomedical due diligence report.

Core capabilities:
- Data synthesis using Gemini's long-context capabilities
- Evidence aggregation and risk scoring
- Structured report generation (Markdown/HTML/PDF)
- Investment recommendation generation

Workflow:
1. Aggregate data from three data-gathering engines
2. Synthesize evidence into narrative sections using Gemini
3. Calculate risk scores and recommendations
4. Render final report using src/report_core/
"""

import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from loguru import logger

from src.llms import create_report_client


@dataclass
class ReportData:
    """
    Aggregated data for report generation.
    
    Attributes:
        user_query: Original user query
        project_name: Drug/therapy name
        harvest_results: Data from BioHarvestEngine (PubMed + ClinicalTrials)
        forensic_results: Data from ForensicEngine (image audit)
        evidence_results: Data from EvidenceEngine (dark data mining)
        metadata: Additional report metadata
    """
    user_query: str
    project_name: str
    harvest_results: Dict[str, Any]
    forensic_results: List[Dict[str, Any]]
    evidence_results: List[Dict[str, Any]]
    metadata: Dict[str, Any] = None


@dataclass
class ReportOutput:
    """
    Generated report output.
    
    Attributes:
        markdown_content: Rendered markdown report
        markdown_path: Path to saved markdown file
        html_path: Path to generated HTML (if rendered)
        pdf_path: Path to generated PDF (if rendered)
        recommendation: Final investment recommendation
        confidence_score: Confidence in recommendation (0-10)
        risk_score: Aggregated risk score (0-10)
    """
    markdown_content: str
    markdown_path: Optional[str] = None
    html_path: Optional[str] = None
    pdf_path: Optional[str] = None
    recommendation: str = "AVOID"
    confidence_score: float = 0.0
    risk_score: float = 0.0


class ReportWriterAgent:
    """
    Biomedical Due Diligence Analyst
    
    Synthesizes evidence from multiple engines into investment-grade reports.
    """
    
    def __init__(self):
        """Initialize Report Writer with Gemini client."""
        
        # Initialize LLM client
        self.llm = create_report_client()
        logger.info("Report Writer Agent initialized with Gemini client")
        
        # Load template
        self.template_path = Path(__file__).parent.parent / "templates" / "biomedical_report.md"
        if not self.template_path.exists():
            logger.warning(f"Template not found: {self.template_path}")
            self.template = None
        else:
            self.template = self.template_path.read_text(encoding='utf-8')
            logger.success(f"Loaded template: {self.template_path}")
        
        # AUDIT FIX: Load system prompt from external file for maintainability
        prompt_path = Path(__file__).parent.parent / "prompts" / "report_writer" / "system.txt"
        if prompt_path.exists():
            self.synthesis_system_prompt = prompt_path.read_text(encoding='utf-8')
            logger.debug("Loaded report writer system prompt from file")
        else:
            logger.warning(f"Prompt file not found: {prompt_path}, using fallback")
            self.synthesis_system_prompt = """You are a Senior Biotech Investment Analyst specializing in forensic due diligence.

Your role is to synthesize disparate data points—failed clinical trials, buried negative results in supplementary materials, and suspicious scientific images—into a cohesive, actionable investment report.

**Core Principles:**
1. **Ruthless Objectivity:** Do not sugarcoat findings. If the data suggests fraud or incompetence, say so explicitly.
2. **Evidence-Based:** Every claim must be backed by specific evidence (quote, trial ID, figure number).
3. **Follow the Money:** Always ask "Why would they hide this?" and "What are the financial incentives?"
4. **Pattern Recognition:** Look for recurring red flags across different data sources (e.g., same issue in trials AND supplementary materials).
5. **Investment Impact:** Translate scientific findings into financial risk (e.g., "This p-value suggests the drug doesn't work, meaning $X billion market cap is at risk").

**CRITICAL CITATION RULES (MANDATORY - AUDIT REQUIREMENT):**
- **Every factual claim MUST be followed by a source citation in brackets**
- **For PubMed articles:** Use format `[Source: PMC1234567]` or `[Source: PMID:1234567]`
- **For clinical trials:** Use format `[Trial: NCT01234567]`
- **For forensic findings:** Use format `[Figure X, Page Y]` or `[Image: figure_003.png]`
- **If no source is available, DO NOT make the claim** - state "Insufficient data" instead
- **NEVER use general biomedical knowledge** - only reference data explicitly provided in the evidence summary below
- **If you're uncertain about a source, err on the side of "Unknown" rather than guessing**

**PROHIBITED (Will cause report rejection):**
- ❌ "Studies suggest..." (vague, no specific source)
- ❌ "Pembrolizumab typically causes..." (generic knowledge, not from evidence)
- ❌ "Research shows..." (no citation)
- ✅ CORRECT: "NCT03456789 reported 8/30 subjects with Grade 3+ cardiac events (p=0.14) [Trial: NCT03456789]"
- ✅ CORRECT: "Table S3 shows statistically insignificant efficacy (p=0.47) [Source: PMC7654321, Supplementary Materials]"

**Analytical Framework:**
- **Clinical Failures:** Terminated trials are harbingers of disaster. Analyze why_stopped fields for euphemisms.
- **Dark Data:** "Data not shown" = "Data that contradicts our narrative". Insignificant p-values buried in appendices are smoking guns.
- **Image Forensics:** Western blot splicing suggests desperation. If they're faking figures, what else are they faking?

**Writing Style:**
- Direct, clinical, unforgiving
- Use financial analyst language ("thesis risk", "downside scenario", "de-risking catalyst")
- Quantify everything (percentages, counts, scores)
- No academic hedging—this is investment analysis, not peer review

**Output Requirements:**
- Return well-structured JSON with synthesized narrative text
- Each section should be 200-500 words
- Include specific evidence citations (see CRITICAL CITATION RULES above)
- Provide quantitative risk scores (0-10 scale)
- Generate actionable recommendations
"""
    
    def write_report(
        self,
        user_query: str,
        harvest_data: Optional[Dict[str, Any]] = None,
        forensic_data: Optional[List[Dict[str, Any]]] = None,
        evidence_data: Optional[List[Dict[str, Any]]] = None,
        project_name: Optional[str] = None,
        output_dir: str = "reports",
        # 🚨 PHASE 2: New parameters for honest reporting
        compiled_evidence_text: str = "",
        failed_count: int = 0,
        total_files: int = 0,
        risk_override: Optional[str] = None,
        analysis_status: str = "UNKNOWN",
        failed_files: Optional[List[str]] = None
    ) -> ReportOutput:
        """
        Generate comprehensive biomedical due diligence report.
        
        🚨 PHASE 2: Now accepts failure metadata to enforce honest reporting
        when PDFs fail to process.
        
        Args:
            user_query: Original user query (e.g., "Analyze CAR-T therapy X")
            harvest_data: Results from BioHarvestEngine (papers + trials)
            forensic_data: Results from ForensicEngine (image audit)
            evidence_data: Results from EvidenceEngine (dark data)
            project_name: Drug/therapy name (auto-extracted if None)
            output_dir: Directory for saving reports
            
            # 🚨 PHASE 2: Honest reporting parameters
            compiled_evidence_text: Aggregated text content of evidence
            failed_count: Number of PDFs that failed to process
            total_files: Total number of PDFs attempted
            risk_override: Forced risk level when data is incomplete
            analysis_status: COMPLETE | PARTIAL_SUCCESS | CRITICAL_FAILURE
            failed_files: List of failed filenames
        
        Returns:
            ReportOutput object with markdown content and paths
        
        Workflow:
            Step A: Data aggregation and validation
            Step B: Gemini-powered evidence synthesis (with failure awareness)
            Step C: Risk scoring and recommendation generation
            Step D: Template rendering (Markdown)
            Step E: Optional HTML/PDF conversion
        
        Example:
            >>> agent = ReportWriterAgent()
            >>> report = agent.write_report(
            ...     user_query="Analyze drug X safety",
            ...     harvest_data=bioharvest_results,
            ...     forensic_data=forensic_results,
            ...     evidence_data=evidence_results,
            ...     failed_count=2,  # 🚨 PHASE 2
            ...     total_files=5,   # 🚨 PHASE 2
            ...     risk_override="UNCERTAIN (40% data missing)"  # 🚨 PHASE 2
            ... )
            >>> print(f"Recommendation: {report.recommendation}")
            >>> print(f"Risk Score: {report.risk_score}/10")
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"📊 Report Generation: {user_query}")
        logger.info(f"{'='*60}")
        
        # 🚨 PHASE 2: Log failure context
        if failed_count > 0:
            logger.warning(f"⚠️ HONEST REPORTING MODE: {failed_count}/{total_files} files failed")
            logger.warning(f"   Analysis Status: {analysis_status}")
            if risk_override:
                logger.warning(f"   Risk Override: {risk_override}")
        
        try:
            # ===== STEP A: Data Aggregation =====
            logger.info("\n[Step A] Aggregating data from engines...")
            
            report_data = self._aggregate_data(
                user_query=user_query,
                harvest_data=harvest_data or {},
                forensic_data=forensic_data or [],
                evidence_data=evidence_data or [],
                project_name=project_name
            )
            
            logger.success(
                f"Aggregated: {len(report_data.harvest_results.get('results', []))} papers/trials, "
                f"{len(report_data.forensic_results)} images, "
                f"{len(report_data.evidence_results)} evidence items"
            )
            
            # ===== STEP A.5: Mathematical Confidence Score =====
            # 🧮 THE FIX: ENFORCE DETERMINISTIC MATH
            if total_files > 0:
                success_count = max(0, total_files - failed_count)
                # Base Score: 10 * (Success Rate)
                raw_score = (success_count / total_files) * 10
                # Cap at 10.0, Floor at 1.0 (unless 0 files processed)
                confidence_score = round(raw_score, 1)
            else:
                confidence_score = 0.0
            
            logger.info(f"🧮 Calculated Confidence: {confidence_score}/10 (Success: {total_files - failed_count}/{total_files})")
            # ----------------------------------------------
            
            # ===== STEP B: Evidence Synthesis =====
            logger.info("\n[Step B] Synthesizing evidence with Gemini...")
            # 🚨 PHASE 2: Pass failure context to synthesis
            # 🧠 THE FIX: Pass mathematical confidence score to prevent AI hallucination
            synthesized_sections = self._synthesize_evidence(
                report_data,
                compiled_evidence_text=compiled_evidence_text,
                failed_count=failed_count,
                total_files=total_files,
                risk_override=risk_override,
                analysis_status=analysis_status,
                failed_files=failed_files or [],
                confidence_score=confidence_score  # 🔥 INJECT MATHEMATICAL SCORE
            )
            
            logger.success(f"Synthesized {len(synthesized_sections)} report sections")
            
            # ===== STEP C: Risk Scoring =====
            logger.info("\n[Step C] Calculating risk scores...")
            # 🚨 PHASE 2: Pass risk_override to scoring
            risk_analysis = self._calculate_risk_scores(
                report_data,
                synthesized_sections,
                risk_override=risk_override,
                failed_count=failed_count,
                total_files=total_files
            )
            
            logger.success(
                f"Risk Score: {risk_analysis['total_risk_score']:.1f}/10 | "
                f"Recommendation: {risk_analysis['recommendation']}"
            )
            
            # ===== STEP D: Template Rendering =====
            logger.info("\n[Step D] Rendering markdown report...")
            markdown_content = self._render_markdown(
                report_data,
                synthesized_sections,
                risk_analysis
            )
            
            # ===== STEP E: Save Report =====
            logger.info("\n[Step E] Saving report...")
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            
            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            project_slug = (project_name or "report").replace(" ", "_").lower()
            markdown_file = output_path / f"{project_slug}_{timestamp}.md"
            pdf_file = output_path / f"{project_slug}_{timestamp}.pdf"
            
            # Save Markdown
            markdown_file.write_text(markdown_content, encoding='utf-8')
            logger.success(f"Markdown saved: {markdown_file}")
            
            # ===== STEP F: Convert to PDF =====
            logger.info("\n[Step F] Converting to PDF...")
            pdf_path = self._convert_markdown_to_pdf(
                markdown_content,
                pdf_file,
                project_name or "Biomedical Due Diligence Report"
            )
            
            if pdf_path:
                logger.success(f"PDF saved: {pdf_path}")
            else:
                logger.warning("PDF conversion failed, Markdown-only output available")
            
            # Create output object
            report_output = ReportOutput(
                markdown_content=markdown_content,
                markdown_path=str(markdown_file),  # PHASE 3.1 FIX: Add markdown path
                html_path=str(pdf_file) if pdf_path else None,  # Store PDF path in html_path for now
                pdf_path=str(pdf_path) if pdf_path else None,
                recommendation=risk_analysis['recommendation'],
                confidence_score=risk_analysis['confidence_score'],
                risk_score=risk_analysis['total_risk_score']
            )
            
            logger.info(f"\n{'='*60}")
            logger.success(f"✅ Report Generation Complete")
            logger.info(f"   Recommendation: {report_output.recommendation}")
            logger.info(f"   Confidence: {report_output.confidence_score:.1f}/10")
            logger.info(f"   Risk Score: {report_output.risk_score:.1f}/10")
            logger.info(f"   Output: {markdown_file}")
            logger.info(f"{'='*60}\n")
            
            return report_output
            
        except Exception as e:
            logger.error(f"Report generation failed: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _aggregate_data(
        self,
        user_query: str,
        harvest_data: Dict[str, Any],
        forensic_data: List[Dict[str, Any]],
        evidence_data: List[Dict[str, Any]],
        project_name: Optional[str]
    ) -> ReportData:
        """
        Aggregate data from all engines into unified structure.
        
        Args:
            user_query: User's original query
            harvest_data: BioHarvestEngine results
            forensic_data: ForensicEngine results
            evidence_data: EvidenceEngine results
            project_name: Optional project name
        
        Returns:
            ReportData object
        """
        # Auto-extract project name if not provided
        if not project_name:
            project_name = user_query.split()[0] if user_query else "Unknown"
        
        return ReportData(
            user_query=user_query,
            project_name=project_name,
            harvest_results=harvest_data,
            forensic_results=forensic_data,
            evidence_results=evidence_data,
            metadata={
                'report_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                'analyst': 'Bio-Short-Seller AI'
            }
        )
    
    def _synthesize_evidence(
        self, 
        report_data: ReportData,
        # 🚨 PHASE 2: Add failure awareness parameters
        compiled_evidence_text: str = "",
        failed_count: int = 0,
        total_files: int = 0,
        risk_override: Optional[str] = None,
        analysis_status: str = "COMPLETE",
        failed_files: List[str] = None,
        confidence_score: float = 0.0  # 🧠 NEW: Mathematical confidence score
    ) -> Dict[str, str]:
        """
        Use Gemini to synthesize evidence into narrative sections.
        
        🚨 PHASE 2: Enforces honest reporting when data is incomplete.
        🧠 THE FIX: confidence_score is now mathematically calculated, not AI-generated.
        
        Args:
            report_data: Aggregated report data
            compiled_evidence_text: Actual text content of evidence
            failed_count: Number of files that failed processing
            total_files: Total files attempted
            risk_override: Forced risk level when data incomplete
            analysis_status: COMPLETE | PARTIAL_SUCCESS | CRITICAL_FAILURE
            failed_files: List of failed filenames
            confidence_score: CALCULATED confidence score (0-10) - DO NOT LET LLM OVERRIDE
        
        Returns:
            Dictionary mapping section names to synthesized text
        """
        # Prepare evidence summary for LLM
        evidence_summary = self._prepare_evidence_summary(report_data)
        
        # 🚨 PHASE 2: Build mandatory failure disclosure
        failure_disclosure = ""
        if failed_count > 0:
            failure_rate = (failed_count / total_files * 100) if total_files > 0 else 0
            failure_disclosure = f"""
⚠️ **CRITICAL DATA INTEGRITY NOTICE:**
- **Analysis Status:** {analysis_status}
- **Files Processed:** {total_files - failed_count}/{total_files} succeeded
- **Files Failed:** {failed_count} ({failure_rate:.0f}% failure rate)
- **Failed Files:** {', '.join(failed_files or ['Unknown'])}
- **Data Completeness:** {'CRITICAL FAILURE' if failed_count == total_files else 'PARTIAL'}

🚨 **MANDATORY REPORTING REQUIREMENT:**
You MUST acknowledge this data failure in your Executive Summary with:
- A bold warning at the top: "⚠️ **WARNING: INCOMPLETE ANALYSIS**"
- Explicit statement: "{failed_count} out of {total_files} PDFs failed to process"
- Clear disclaimer: "Risk assessment may be INACCURATE due to missing data"
- If risk_override is provided, YOU MUST use it as the Risk Level instead of calculating your own

**PROHIBITED:**
- DO NOT invent data for missing files
- DO NOT claim "Low Risk" when data is missing
- DO NOT ignore this failure in your analysis
- If evidence_text is empty/minimal, state "Data Extraction Failed" explicitly
"""
        
        # 🧠 THE FIX: Inject Mathematical Confidence Score into System Prompt
        confidence_instruction = f"""

🧠 **CONFIDENCE SCORE MANDATE:**
- **CALCULATED CONFIDENCE:** {confidence_score}/10 (Based on {total_files - failed_count}/{total_files} success rate)
- **CRITICAL INSTRUCTION:** You MUST use exactly "{confidence_score}/10" as the Confidence Score in the Executive Summary.
- **STRICTLY PROHIBITED:** DO NOT recalculate, adjust, or hallucinate this number. This is MATHEMATICAL, not subjective.
- **Example Usage in Report:** "Confidence Score: {confidence_score}/10"
"""
        
        # 💉 STEP 2 FIX: Inject compiled evidence text AFTER statistical summary
        evidence_log_section = ""
        if compiled_evidence_text:
            evidence_log_section = f"""

<EVIDENCE_LOG>
### 📝 RAW EVIDENCE EXTRACTED FROM PDFs:
{compiled_evidence_text}
</EVIDENCE_LOG>

🔍 **CRITICAL INSTRUCTION:**
Use the specific findings, quotes, and analyses from the <EVIDENCE_LOG> above to populate:
- "Red Flags Identified" section
- "Dark Data" section  
- Risk assessments
DO NOT use "[Data not available]" if evidence exists in the log above.
If <EVIDENCE_LOG> is empty, explicitly state "PDF extraction failed - no evidence available".
"""
        else:
            evidence_log_section = """

<EVIDENCE_LOG>
⚠️ **NO EVIDENCE TEXT AVAILABLE** - PDF extraction may have failed.
</EVIDENCE_LOG>

🚨 You MUST report this as "CRITICAL DATA GAP" in the Dark Data section.
"""
        
        synthesis_prompt = f"""Analyze the following biomedical due diligence data and synthesize it into structured report sections.

**USER QUERY:** {report_data.user_query}

{failure_disclosure}

{confidence_instruction}

**EVIDENCE SUMMARY (Statistical Overview):**
{evidence_summary}

{evidence_log_section}

**REQUIRED SECTIONS:**

Generate JSON output with these sections:

1. **executive_summary**: 3-5 paragraph overview with Go/No-Go recommendation
   🚨 IF failed_count > 0: START with bold warning about incomplete analysis
   🧮 MUST include: "Confidence Score: {confidence_score}/10" (DO NOT modify this number)
2. **scientific_rationale**: Analysis of the drug's mechanism and biological plausibility
3. **clinical_trial_analysis**: Detailed analysis of failed/terminated trials
4. **dark_data_synthesis**: Analysis of buried negative results from supplementary materials
   🚨 IF no evidence text available: State "Data extraction failed - unable to analyze"
5. **forensic_findings**: Assessment of suspicious images and their implications
6. **risk_cascade_narrative**: How individual red flags compound into systemic risk
7. **bull_case**: Best-case scenario (be skeptical)
8. **bear_case**: Most likely scenario based on evidence
9. **black_swan_case**: Worst-case catastrophic scenario
10. **analyst_verdict**: Your final professional opinion
    🚨 IF risk_override provided: Use it as final risk level

**OUTPUT FORMAT:**
```json
{{
  "executive_summary": "...",
  "scientific_rationale": "...",
  "clinical_trial_analysis": "...",
  "dark_data_synthesis": "...",
  "forensic_findings": "...",
  "risk_cascade_narrative": "...",
  "bull_case": "...",
  "bear_case": "...",
  "black_swan_case": "...",
  "analyst_verdict": "..."
}}
```

Be specific, cite evidence, and quantify risk wherever possible.
🚨 CRITICAL: Obey the MANDATORY REPORTING REQUIREMENT and CONFIDENCE SCORE MANDATE above.
"""
        
        try:
            response = self.llm.generate_content(
                prompt=synthesis_prompt,
                system_instruction=self.synthesis_system_prompt
            )
            
            # Parse JSON from response
            synthesized = self._parse_synthesis_response(response)
            
            return synthesized
            
        except Exception as e:
            logger.error(f"Evidence synthesis failed: {e}")
            # Return fallback structure
            return {
                'executive_summary': 'Error generating summary.',
                'scientific_rationale': 'Error analyzing rationale.',
                'clinical_trial_analysis': 'Error analyzing trials.',
                'dark_data_synthesis': 'Error synthesizing dark data.',
                'forensic_findings': 'Error analyzing forensics.',
                'risk_cascade_narrative': 'Error analyzing risk cascade.',
                'bull_case': 'Insufficient data.',
                'bear_case': 'Insufficient data.',
                'black_swan_case': 'Insufficient data.',
                'analyst_verdict': 'AVOID - Data quality issues.'
            }
    
    def _prepare_evidence_summary(self, report_data: ReportData) -> str:
        """
        Prepare concise evidence summary for LLM context.
        
        Args:
            report_data: Aggregated report data
        
        Returns:
            Formatted evidence summary text
        """
        summary_lines = []
        
        # Harvest data summary
        harvest_results = report_data.harvest_results.get('results', [])
        summary_lines.append(f"**HARVEST DATA:** {len(harvest_results)} papers/trials")
        
        # Count failed trials
        failed_trials = [
            r for r in harvest_results 
            if r.get('source') == 'ClinicalTrials.gov' 
            and r.get('status') in ['TERMINATED', 'SUSPENDED', 'WITHDRAWN']
        ]
        summary_lines.append(f"  - Failed trials: {len(failed_trials)}")
        
        for trial in failed_trials[:3]:  # Show top 3
            summary_lines.append(
                f"    * {trial.get('title', 'Unknown')}: {trial.get('metadata', {}).get('why_stopped', 'Unknown')}"
            )
        
        # Evidence data summary
        summary_lines.append(f"\n**DARK DATA:** {len(report_data.evidence_results)} risk signals")
        
        high_risk = [e for e in report_data.evidence_results if e.get('risk_level') == 'HIGH']
        summary_lines.append(f"  - High risk signals: {len(high_risk)}")
        
        for item in high_risk[:3]:  # Show top 3
            summary_lines.append(
                f"    * {item.get('risk_type', 'Unknown')}: {item.get('quote', '')[:100]}..."
            )
        
        # Forensic data summary
        suspicious = [f for f in report_data.forensic_results if f.get('status') == 'suspicious']
        summary_lines.append(f"\n**FORENSICS:** {len(suspicious)} suspicious images")
        
        for img in suspicious[:3]:  # Show top 3
            summary_lines.append(
                f"    * {img.get('image_id', 'Unknown')}: {', '.join(img.get('findings', []))}"
            )
        
        return "\n".join(summary_lines)
    
    def _parse_synthesis_response(self, response: str) -> Dict[str, str]:
        """
        Parse LLM JSON response into dictionary.
        
        Args:
            response: Raw LLM response
        
        Returns:
            Dictionary of synthesized sections
        """
        try:
            # Extract JSON from markdown code blocks
            response_text = response.strip()
            if "```json" in response_text:
                response_text = response_text.split("```json")[1].split("```")[0].strip()
            elif "```" in response_text:
                response_text = response_text.split("```")[1].split("```")[0].strip()
            
            data = json.loads(response_text)
            return data
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse synthesis JSON: {e}")
            logger.debug(f"Raw response: {response[:500]}...")
            return {}
    
    def _calculate_risk_scores(
        self,
        report_data: ReportData,
        synthesized_sections: Dict[str, str],
        # 🚨 PHASE 2: Add failure awareness
        risk_override: Optional[str] = None,
        failed_count: int = 0,
        total_files: int = 0
    ) -> Dict[str, Any]:
        """
        Calculate quantitative risk scores and generate recommendation.
        
        🚨 PHASE 2: Respects risk_override when data is incomplete.
        
        Args:
            report_data: Aggregated report data
            synthesized_sections: Synthesized narrative sections
            risk_override: Forced risk level when data incomplete (PHASE 2)
            failed_count: Number of failed files (PHASE 2)
            total_files: Total files attempted (PHASE 2)
        
        Returns:
            Dictionary with risk scores and recommendation
        """
        # Initialize scores
        clinical_score = 0.0
        dark_data_score = 0.0
        forensic_score = 0.0
        literature_score = 0.0
        
        # Clinical trial score (0-10, higher = more risk)
        harvest_results = report_data.harvest_results.get('results', [])
        failed_trials = [
            r for r in harvest_results 
            if r.get('source') == 'ClinicalTrials.gov' 
            and r.get('status') in ['TERMINATED', 'SUSPENDED', 'WITHDRAWN']
        ]
        
        if harvest_results:
            failure_rate = len(failed_trials) / len(harvest_results)
            clinical_score = min(10.0, failure_rate * 20)  # Scale to 0-10
        
        # Dark data score
        high_risk_evidence = [
            e for e in report_data.evidence_results 
            if e.get('risk_level') == 'HIGH'
        ]
        dark_data_score = min(10.0, len(high_risk_evidence) * 2)
        
        # Forensic score
        suspicious_images = [
            f for f in report_data.forensic_results 
            if f.get('status') == 'suspicious'
        ]
        forensic_score = min(10.0, len(suspicious_images) * 3)
        
        # Literature score (placeholder - could analyze sentiment)
        literature_score = 5.0  # Neutral baseline
        
        # Weighted total
        total_risk_score = (
            clinical_score * 0.30 +
            dark_data_score * 0.35 +
            forensic_score * 0.20 +
            literature_score * 0.15
        )
        
        # 🚨 PHASE 2: Override recommendation if data is incomplete
        if risk_override:
            logger.warning(f"🚨 RISK OVERRIDE ACTIVE: {risk_override}")
            recommendation = "INCONCLUSIVE - INCOMPLETE DATA"
            confidence_score = 0.0  # Zero confidence when data is missing
            
            # Add disclaimer to explain the override
            if failed_count == total_files:
                recommendation = "CRITICAL FAILURE - NO ANALYSIS POSSIBLE"
                confidence_score = 0.0
            elif failed_count > 0:
                failure_rate = (failed_count / total_files * 100) if total_files > 0 else 0
                recommendation = f"PARTIAL ANALYSIS ONLY ({failure_rate:.0f}% data missing)"
                confidence_score = max(0.0, 10.0 - (failure_rate / 10))  # Penalize confidence
        else:
            # Normal recommendation logic
            if total_risk_score >= 7.0:
                recommendation = "STRONG AVOID"
                confidence_score = 9.0
            elif total_risk_score >= 5.0:
                recommendation = "AVOID"
                confidence_score = 7.5
            elif total_risk_score >= 3.0:
                recommendation = "PROCEED WITH EXTREME CAUTION"
                confidence_score = 6.0
            else:
                recommendation = "PROCEED WITH CAUTION"
                confidence_score = 5.0
        
        return {
            'clinical_failure_score': clinical_score,
            'dark_data_score': dark_data_score,
            'forensic_score': forensic_score,
            'literature_score': literature_score,
            'total_risk_score': total_risk_score,
            'recommendation': recommendation,
            'confidence_score': confidence_score,
            'clinical_weighted': clinical_score * 0.30,
            'dark_data_weighted': dark_data_score * 0.35,
            'forensic_weighted': forensic_score * 0.20,
            'literature_weighted': literature_score * 0.15,
            # 🚨 PHASE 2: Add failure metadata to risk analysis
            'risk_override': risk_override,
            'failed_count': failed_count,
            'total_files': total_files,
            'data_completeness': f"{total_files - failed_count}/{total_files}" if total_files > 0 else "N/A"
        }
    
    def _render_markdown(
        self,
        report_data: ReportData,
        synthesized_sections: Dict[str, str],
        risk_analysis: Dict[str, Any]
    ) -> str:
        """
        Render final markdown report using template.
        
        Args:
            report_data: Aggregated report data
            synthesized_sections: Synthesized narrative sections
            risk_analysis: Risk scores and recommendation
        
        Returns:
            Rendered markdown content
        """
        # ⚖️ STEP 3 FIX: Determine final risk label with override priority
        risk_override = risk_analysis.get('risk_override')
        calculated_risk = 'HIGH' if risk_analysis['total_risk_score'] >= 7 else 'MEDIUM' if risk_analysis['total_risk_score'] >= 4 else 'LOW'
        
        # Priority: risk_override > calculated_risk
        if risk_override:
            # Extract clean label from override (e.g., "UNCERTAIN (...)" -> "UNCERTAIN")
            final_risk_label = risk_override.split('(')[0].strip()
            logger.info(f"⚖️ Risk Override Active: {risk_override} -> Header displays: {final_risk_label}")
        else:
            final_risk_label = calculated_risk
            logger.debug(f"⚖️ Using calculated risk: {calculated_risk}")
        
        # Prepare template variables
        template_vars = {
            # Header
            'project_name': report_data.project_name,
            'report_date': report_data.metadata.get('report_date', ''),
            'user_query': report_data.user_query,
            
            # Executive Summary
            'recommendation': risk_analysis['recommendation'],
            'confidence_score': f"{risk_analysis['confidence_score']:.1f}",
            'risk_level': final_risk_label,  # ⚖️ STEP 3 FIX: Use unified risk label
            'executive_summary_text': synthesized_sections.get('executive_summary', ''),
            
            # Synthesized sections
            'scientific_rationale': synthesized_sections.get('scientific_rationale', ''),
            'risk_cascade_narrative': synthesized_sections.get('risk_cascade_narrative', ''),
            'bull_case': synthesized_sections.get('bull_case', ''),
            'bear_case': synthesized_sections.get('bear_case', ''),
            'black_swan_case': synthesized_sections.get('black_swan_case', ''),
            'analyst_verdict': synthesized_sections.get('analyst_verdict', ''),
            
            # Risk scores
            'clinical_failure_score': f"{risk_analysis['clinical_failure_score']:.1f}",
            'dark_data_score': f"{risk_analysis['dark_data_score']:.1f}",
            'forensic_score': f"{risk_analysis['forensic_score']:.1f}",
            'literature_score': f"{risk_analysis['literature_score']:.1f}",
            'total_risk_score': f"{risk_analysis['total_risk_score']:.1f}",
            'clinical_weighted': f"{risk_analysis['clinical_weighted']:.2f}",
            'dark_data_weighted': f"{risk_analysis['dark_data_weighted']:.2f}",
            'forensic_weighted': f"{risk_analysis['forensic_weighted']:.2f}",
            'literature_weighted': f"{risk_analysis['literature_weighted']:.2f}",
            
            # Data counts
            'total_trials': len(report_data.harvest_results.get('results', [])),
            'failed_trials_count': len([
                r for r in report_data.harvest_results.get('results', [])
                if r.get('status') in ['TERMINATED', 'SUSPENDED', 'WITHDRAWN']
            ]),
            'total_evidence_items': len(report_data.evidence_results),
            'high_risk_count': len([
                e for e in report_data.evidence_results 
                if e.get('risk_level') == 'HIGH'
            ]),
            'suspicious_images_count': len([
                f for f in report_data.forensic_results 
                if f.get('status') == 'suspicious'
            ]),
        }
        
        # Simple template rendering (replace {{var}} with values)
        if self.template:
            rendered = self.template
            for key, value in template_vars.items():
                rendered = rendered.replace(f"{{{{{key}}}}}", str(value))
            
            # Remove unrendered handlebars sections ({{#each ...}})
            import re
            rendered = re.sub(r'\{\{#each.*?\}\}.*?\{\{/each\}\}', '', rendered, flags=re.DOTALL)
            rendered = re.sub(r'\{\{#if.*?\}\}.*?\{\{/if\}\}', '', rendered, flags=re.DOTALL)
            rendered = re.sub(r'\{\{.*?\}\}', '[Data not available]', rendered)
            
            return rendered
        else:
            # Fallback: basic markdown without template
            return self._generate_basic_markdown(report_data, synthesized_sections, risk_analysis)
    
    def _generate_basic_markdown(
        self,
        report_data: ReportData,
        synthesized_sections: Dict[str, str],
        risk_analysis: Dict[str, Any]
    ) -> str:
        """
        Generate basic markdown report without template (fallback).
        
        Args:
            report_data: Aggregated report data
            synthesized_sections: Synthesized sections
            risk_analysis: Risk analysis
        
        Returns:
            Basic markdown content
        """
        # ⚖️ STEP 3 FIX: Apply same risk override logic in fallback
        risk_override = risk_analysis.get('risk_override')
        calculated_risk = 'HIGH' if risk_analysis['total_risk_score'] >= 7 else 'MEDIUM' if risk_analysis['total_risk_score'] >= 4 else 'LOW'
        final_risk_label = risk_override.split('(')[0].strip() if risk_override else calculated_risk
        
        lines = [
            f"# {report_data.project_name} - Biomedical Due Diligence Report",
            "",
            f"**Generated:** {report_data.metadata.get('report_date', '')}",
            f"**Query:** {report_data.user_query}",
            "",
            "## Executive Summary",
            "",
            f"**Risk Level:** {final_risk_label}",  # ⚖️ STEP 3 FIX: Use unified label
            f"**Recommendation:** {risk_analysis['recommendation']}",
            f"**Risk Score:** {risk_analysis['total_risk_score']:.1f}/10",
            "",
            synthesized_sections.get('executive_summary', ''),
            "",
            "## Analysis",
            "",
            synthesized_sections.get('analyst_verdict', ''),
            ""
        ]
        
        return "\n".join(lines)
    
    def _convert_markdown_to_pdf(
        self,
        markdown_content: str,
        output_path: Path,
        title: str
    ) -> Optional[str]:
        """
        Convert Markdown report to professional PDF.
        
        Args:
            markdown_content: Markdown text to convert
            output_path: Target PDF file path
            title: Report title for PDF metadata
        
        Returns:
            Path to generated PDF or None if conversion fails
        """
        try:
            import markdown
            import pdfkit
            
            # Convert Markdown to HTML
            html_body = markdown.markdown(
                markdown_content,
                extensions=['extra', 'codehilite', 'tables', 'toc']
            )
            
            # Professional Research Paper CSS
            css_style = """
            <style>
                @page {
                    size: A4;
                    margin: 2.5cm;
                }
                body {
                    font-family: 'Georgia', 'Times New Roman', serif;
                    font-size: 11pt;
                    line-height: 1.6;
                    color: #2c3e50;
                    max-width: 800px;
                    margin: 0 auto;
                }
                h1 {
                    font-size: 24pt;
                    font-weight: bold;
                    color: #1a252f;
                    border-bottom: 3px solid #3498db;
                    padding-bottom: 10px;
                    margin-top: 30px;
                    margin-bottom: 20px;
                }
                h2 {
                    font-size: 18pt;
                    font-weight: bold;
                    color: #2c3e50;
                    margin-top: 25px;
                    margin-bottom: 15px;
                    border-bottom: 1px solid #bdc3c7;
                    padding-bottom: 8px;
                }
                h3 {
                    font-size: 14pt;
                    font-weight: bold;
                    color: #34495e;
                    margin-top: 20px;
                    margin-bottom: 10px;
                }
                p {
                    text-align: justify;
                    margin-bottom: 12px;
                }
                ul, ol {
                    margin-left: 20px;
                    margin-bottom: 15px;
                }
                li {
                    margin-bottom: 8px;
                }
                code {
                    font-family: 'Courier New', monospace;
                    background-color: #ecf0f1;
                    padding: 2px 6px;
                    border-radius: 3px;
                    font-size: 10pt;
                }
                pre {
                    background-color: #f8f9fa;
                    border-left: 4px solid #3498db;
                    padding: 15px;
                    margin: 15px 0;
                    overflow-x: auto;
                    font-size: 9pt;
                }
                blockquote {
                    border-left: 4px solid #95a5a6;
                    padding-left: 20px;
                    margin: 15px 0;
                    font-style: italic;
                    color: #7f8c8d;
                }
                table {
                    width: 100%;
                    border-collapse: collapse;
                    margin: 20px 0;
                    font-size: 10pt;
                }
                th {
                    background-color: #34495e;
                    color: white;
                    padding: 12px;
                    text-align: left;
                    font-weight: bold;
                }
                td {
                    border: 1px solid #ddd;
                    padding: 10px;
                }
                tr:nth-child(even) {
                    background-color: #f8f9fa;
                }
                .risk-high {
                    color: #e74c3c;
                    font-weight: bold;
                }
                .risk-medium {
                    color: #f39c12;
                    font-weight: bold;
                }
                .risk-low {
                    color: #27ae60;
                    font-weight: bold;
                }
            </style>
            """
            
            # Complete HTML document
            html_document = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <title>{title}</title>
                {css_style}
            </head>
            <body>
                {html_body}
            </body>
            </html>
            """
            
            # PDF conversion options
            pdf_options = {
                'page-size': 'A4',
                'margin-top': '2.5cm',
                'margin-right': '2.5cm',
                'margin-bottom': '2.5cm',
                'margin-left': '2.5cm',
                'encoding': 'UTF-8',
                'no-outline': None,
                'enable-local-file-access': None,
                'print-media-type': None,
            }
            
            # Convert HTML to PDF
            pdfkit.from_string(html_document, str(output_path), options=pdf_options)
            
            return str(output_path)
            
        except ImportError as e:
            logger.warning(f"PDF conversion libraries not installed: {e}")
            logger.info("💡 Install with: pip install markdown pdfkit")
            logger.info("💡 Ensure wkhtmltopdf is installed: https://wkhtmltopdf.org/downloads.html")
            return None
        except Exception as e:
            logger.error(f"PDF conversion failed: {e}")
            return None


def create_agent() -> ReportWriterAgent:
    """
    Factory function to create a ReportWriterAgent instance.
    
    Returns:
        ReportWriterAgent: Initialized agent ready for use
    
    Example:
        >>> agent = create_agent()
        >>> report = agent.write_report(
        ...     user_query="Analyze drug X",
        ...     harvest_data=harvest_results,
        ...     forensic_data=forensic_results,
        ...     evidence_data=evidence_results
        ... )
    """
    return ReportWriterAgent()
