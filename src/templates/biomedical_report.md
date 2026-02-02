# {{project_name}} - Biomedical Due Diligence Report

**Generated:** {{report_date}}  
**Analyst:** Bio-Short-Seller AI  
**Query:** {{user_query}}

---

## Executive Summary

**Investment Recommendation:** {{recommendation}}  
**Confidence Score:** {{confidence_score}}/10  
**Risk Level:** {{risk_level}}

### Key Findings at a Glance

{{executive_summary_text}}

**Red Flags Identified:**
{{red_flags_list}}

**Critical Decision Factors:**
{{decision_factors}}

---

## 1. Project Overview

### Drug/Therapy Profile

**Compound Name:** {{compound_name}}  
**Mechanism of Action (MoA):** {{moa_description}}  
**Molecular Target:** {{target_description}}  
**Development Stage:** {{development_stage}}  
**Sponsor/Developer:** {{sponsor_company}}

### Scientific Rationale

{{scientific_rationale}}

### Market Context

{{market_context}}

---

## 2. Clinical Trial Audit

### Overview
This section analyzes clinical trial history using data harvested from PubMed and ClinicalTrials.gov.

**Total Trials Identified:** {{total_trials}}  
**Failed/Terminated Trials:** {{failed_trials_count}}  
**Success Rate:** {{success_rate}}%

### Failed Trial Analysis

{{#each failed_trials}}
#### Trial {{@index}}: {{this.nct_id}} - {{this.title}}

**Status:** {{this.status}}  
**Phase:** {{this.phase}}  
**Termination Reason:** {{this.why_stopped}}  
**Sponsor:** {{this.sponsor}}

**Red Flag Analysis:**
{{this.red_flag_analysis}}

**Source:** [ClinicalTrials.gov]({{this.link}})

---
{{/each}}

### Literature Evidence

{{#each pubmed_papers}}
#### {{this.title}}

**Authors:** {{this.authors}}  
**Journal:** {{this.journal}} ({{this.pub_date}})  
**Key Finding:** {{this.key_finding}}

**Relevance to Risk Assessment:**
{{this.risk_relevance}}

**Link:** [PubMed]({{this.pubmed_link}})

---
{{/each}}

---

## 3. Dark Data Mining (Supplementary Materials Analysis)

### Overview
This section exposes "negative results" buried in supplementary materials, appendices, and footnotes—the data authors hoped you wouldn't read.

**PDFs Analyzed:** {{pdfs_analyzed_count}}  
**Risk Signals Found:** {{total_evidence_items}}  
**High-Risk Signals:** {{high_risk_count}}

### 🚨 High-Risk Dark Data

{{#each high_risk_evidence}}
#### Signal {{@index}}: {{this.risk_type_display}}

**Source:** {{this.source}} ({{this.page_estimate}})  
**Risk Level:** HIGH  
**Category:** {{this.risk_type}}

**Buried Evidence:**
> {{this.quote}}

**Analyst Commentary:**
{{this.explanation}}

**Why This Matters:**
{{this.investment_impact}}

---
{{/each}}

### ⚠️ Medium-Risk Dark Data

{{#each medium_risk_evidence}}
#### Signal {{@index}}: {{this.risk_type_display}}

**Source:** {{this.source}}  
**Category:** {{this.risk_type}}

**Finding:**
> {{this.quote}}

**Analysis:** {{this.explanation}}

---
{{/each}}

### Statistical Red Flags Summary

**Insignificant p-values (>0.05) found:** {{insignificant_pvalues_count}}  
**"Data not shown" mentions:** {{data_not_shown_count}}  
**Unexplained dropouts:** {{dropout_mentions_count}}

---

## 4. Forensic Image Audit

### Overview
This section identifies potential image manipulation in scientific figures using AI-powered forensic analysis.

**Images Analyzed:** {{total_images_analyzed}}  
**Suspicious Images:** {{suspicious_images_count}}  
**Confidence Threshold:** ≥0.7

### 🔍 Suspicious Figures

{{#each suspicious_images}}
#### Figure {{@index}}: {{this.image_id}}

**Page:** {{this.page_num}}  
**Suspicion Level:** {{this.confidence}} ({{this.status}})

**Forensic Findings:**
{{#each this.findings}}
- {{this}}
{{/each}}

**Detailed Analysis:**
{{this.raw_analysis}}

**Image Location:** `{{this.image_path}}`

**Investor Interpretation:**
{{this.investor_impact}}

---
{{/each}}

### Image Integrity Summary

**Western Blots Analyzed:** {{western_blot_count}}  
**Microscopy Images Analyzed:** {{microscopy_count}}  
**Charts/Graphs Analyzed:** {{chart_count}}

**Manipulation Types Detected:**
{{#each manipulation_types}}
- {{this.type}}: {{this.count}} instances
{{/each}}

---

## 5. Risk Graveyard: The Failure Path Visualization

### Timeline of Red Flags

```
{{failure_timeline}}
```

### Aggregated Risk Score Breakdown

| Risk Category | Weight | Score | Weighted Score |
|---------------|--------|-------|----------------|
| Clinical Failures | 30% | {{clinical_failure_score}}/10 | {{clinical_weighted}} |
| Dark Data Signals | 35% | {{dark_data_score}}/10 | {{dark_data_weighted}} |
| Image Forensics | 20% | {{forensic_score}}/10 | {{forensic_weighted}} |
| Literature Concerns | 15% | {{literature_score}}/10 | {{literature_weighted}} |
| **TOTAL RISK** | **100%** | - | **{{total_risk_score}}/10** |

### Risk Cascade Analysis

{{risk_cascade_narrative}}

### Comparative Benchmarking

**Similar Failed Compounds:**
{{#each similar_failures}}
- {{this.compound}} ({{this.company}}): Failed at {{this.stage}} - Reason: {{this.reason}}
{{/each}}

---

## 6. Evidence Synthesis & Investment Thesis

### Bull Case (Best-Case Scenario)

{{bull_case}}

### Bear Case (Base-Case Scenario)

{{bear_case}}

### Black Swan Case (Worst-Case Scenario)

{{black_swan_case}}

### Analyst's Verdict

{{analyst_verdict}}

**Probability-Weighted Expected Value:**
- Bull Case ({{bull_probability}}%): {{bull_outcome}}
- Bear Case ({{bear_probability}}%): {{bear_outcome}}
- Black Swan ({{black_swan_probability}}%): {{black_swan_outcome}}

**Expected Outcome:** {{expected_outcome}}

---

## 7. Conclusion & Actionable Recommendations

### Final Investment Recommendation

**Decision:** {{final_recommendation}}

**Rationale:**
{{final_rationale}}

### Risk Mitigation Strategies (If Proceeding)

{{#if proceed_with_caution}}
{{#each mitigation_strategies}}
{{@index}}. {{this}}
{{/each}}
{{else}}
**Not Applicable** - Recommend avoiding this investment.
{{/if}}

### Key Questions for Management

{{#each management_questions}}
{{@index}}. {{this}}
{{/each}}

### Monitoring Triggers

**Watch for these developments:**
{{#each monitoring_triggers}}
- {{this}}
{{/each}}

---

## Appendices

### Appendix A: Methodology

**Data Sources:**
- PubMed (NCBI E-utilities API)
- ClinicalTrials.gov (API v2)
- Scientific PDFs (full-text analysis)
- Image forensic analysis (Gemini Vision API)

**Analysis Tools:**
- BioHarvestEngine: Literature & trial harvester
- ForensicEngine: Image manipulation detector
- EvidenceEngine: Supplementary material dark data miner

**LLM Infrastructure:**
- Google Gemini Pro (2M token context window)
- Temperature: 0.4 (balanced analysis)

### Appendix B: Data Quality Disclaimer

This report is generated by AI-assisted analysis and should be validated by human experts before making investment decisions. The forensic image analysis detects patterns consistent with manipulation but cannot definitively prove fraud without expert human review.

### Appendix C: Risk Definitions

- **HIGH RISK:** Clear safety concerns, weak statistical evidence, or confirmed manipulation patterns
- **MEDIUM RISK:** Suspicious patterns requiring further investigation
- **LOW RISK:** Minor transparency issues or statistical oddities

---

**Report End**

*Generated by Bio-Short-Seller AI - Biomedical Due Diligence Platform*  
*Powered by Google Gemini Pro*
