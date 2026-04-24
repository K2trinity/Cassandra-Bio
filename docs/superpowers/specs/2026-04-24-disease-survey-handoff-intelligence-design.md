# Disease Survey Handoff Intelligence Design

Date: 2026-04-24

## Purpose

This design upgrades Cassandra's disease-oriented survey workflow so the final writer consumes structured handoff data instead of generating report data itself. The first gold-standard query is:

```text
conduct a comprehensive survey on Alzheimer disease
```

The first implementation phase focuses on Alzheimer disease style reports. BIIB/company or ticker investigations remain an explicit second regression target, mainly to prevent whole-query entity leakage and wrong disease-survey routing while the disease workflow is upgraded.

## Current Findings

The current backend workflow is a six-node chain:

```text
START -> harvester -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer -> END
```

However, the disease survey report currently succeeds through a writer-side branch:

```text
harvest_data["results"]
  -> aggregate_survey_data(rows, user_query)
  -> DiseaseSurveyState
  -> compose_disease_survey_report_bundle()
  -> markdown / html / pdf
```

That branch works because it does not depend on handoff slots. The writer node passes `extension_payloads` as `synthesis_sections`, but `ReportWriterAgent.write_report()` currently deletes `extra_payload`, so `slot_a`, `slot_b`, and `slot_c` do not affect the final report.

The main defects in the current Alzheimer disease report are not only handoff truncation:

- Company technical-route analysis is not implemented.
- Clinical trial timing fields are harvested but not carried into `TrialRecord`.
- Market landscape is a financial placeholder and does not analyze same-disease, same-target, same-modality, or same-window competition.
- Non-drug interventions are mixed into the pipeline without a clear therapeutic flag.
- Literature review is broad and not restricted to a top-50 journal evidence pool.
- Writer-side disease survey aggregation hides structured report data from the main handoff contract.

The BIIB report reveals a separate entity and intent problem:

- The whole user query can become `project_name` or `drug_name`.
- Query words such as `Generate`, `Summarize`, and `risks` can become graph entities.
- A company or ticker investigation can be routed through the disease survey template if enough harvested rows contain PMIDs or NCT IDs.

## Confirmed Design Decisions

- The first gold-standard report is disease-oriented, using Alzheimer disease.
- Non-drug or non-therapeutic rows remain in the main pipeline table, but are only marked `非药物/非治疗性`; no finer taxonomy is required.
- Company technical route coverage is limited to pharma or biotech sponsors that have therapeutic pipeline assets.
- Universities, hospitals, individual investigators, and non-therapeutic project sponsors do not enter the company technical-route crawl.
- Pipeline timeline risk and market competition risk use qualitative labels only: `低`, `中`, `高`, or `数据不足`.
- Every risk label must include evidence. If evidence is missing, the value is `数据不足`.
- The writer can generate summary prose from existing data, but must not generate data.
- The writer must continue injecting structured tables and charts.
- `slot_a`, `slot_b`, `slot_c`, and the new disease survey slot must not be deleted by the writer.
- The existing disease survey chain should not be removed immediately. It becomes a fallback while the new handoff-authoritative slot is adopted.

## Goals

1. Move disease survey aggregation and data cleaning out of the writer path and into a post-harvest intelligence node.
2. Add a first-class `slot_disease_survey` payload under `extension_payloads`.
3. Preserve and consume all extension slots in the writer.
4. Ensure writer output is grounded in structured data and evidence IDs.
5. Replace `Sponsor Analysis`, `Target Biology`, and `Safety Profile` as independent chapters with a single company technical-route analysis chapter.
6. Restrict Literature Review and CNS Benchmark to a top-50 journal evidence pool.
7. Add a final per-pipeline timeline and competition risk chapter with evidence-backed qualitative labels.
8. Keep chart and table injection in the report.

## Non-Goals

- Do not delete the existing `disease_survey` module in the first phase.
- Do not fully rewrite the generic writer.
- Do not produce success probabilities.
- Do not fabricate market-share percentages for pre-revenue assets.
- Do not ask the writer or LLM to create assets, companies, technical routes, risk labels, or evidence sources.
- Do not over-classify non-drug interventions beyond `非药物/非治疗性`.
- Do not show non-top-50 literature as a fallback in the Literature Review.
- Do not cover every sponsor website. Only pharma or biotech sponsors with therapeutic assets are in scope.

## Target Workflow

The target disease-oriented workflow is:

```text
START
  -> harvester
  -> disease_survey_intelligence
  -> extension_handoff
  -> evidence_synthesizer
  -> clinical_analyzer
  -> quality_assessor
  -> writer
  -> END
```

`harvester` remains responsible for raw source collection only. It should keep emitting:

```text
harvested_data
harvest_data_layers
harvest_source_payloads
harvest_frontend_payload
```

`disease_survey_intelligence` becomes the first post-harvest data cleaning and report-intelligence node. It upgrades the current `aggregate_survey_data()` flow and writes a structured handoff payload:

```python
extension_payloads["slot_disease_survey"] = {...}
```

`extension_handoff` must preserve existing slots rather than overwriting them.

`writer` consumes `slot_disease_survey` when present. The legacy writer-side `aggregate_survey_data()` path remains only as fallback.

## Slot Contract

The new disease survey slot has this top-level shape:

```python
{
    "intent": {...},
    "entity_profile": {...},
    "field_audit": {...},
    "pipeline_assets": [...],
    "company_technical_routes": [...],
    "literature_review": {...},
    "pipeline_timeline_competition_risks": [...],
    "charts": {...},
    "evidence_registry": [...],
}
```

### intent

```python
{
    "report_type": "disease_survey",
    "disease_name": "Alzheimer's Disease",
    "original_query": "conduct a comprehensive survey on Alzheimer disease",
    "confidence": "high",
}
```

### entity_profile

```python
{
    "primary_entity": "Alzheimer's Disease",
    "entity_type": "disease",
    "synonyms": ["Alzheimer disease", "AD"],
    "excluded_query_terms": ["conduct", "comprehensive", "survey"],
}
```

This profile prevents whole-query text from becoming the disease, drug, company, or graph entity.

### pipeline_assets

Each therapeutic asset row includes:

```python
{
    "asset_id": "asset_lecanemab",
    "asset_name": "Lecanemab",
    "company": "Eisai / Biogen",
    "sponsor": "Eisai Inc.",
    "phase": "Phase 3",
    "status": "Completed",
    "modality": "Monoclonal Antibody",
    "targets": ["Aβ"],
    "trial_ids": ["NCT01767311", "NCT03887455"],
    "is_therapeutic": True,
    "asset_note": "",
    "evidence_ids": ["ev_ctgov_NCT01767311"],
}
```

Each non-drug or non-therapeutic row remains visible but is marked simply:

```python
{
    "asset_name": "Questionnaire",
    "company": "Assistance Publique - Hôpitaux de Paris",
    "phase": "Not specified",
    "is_therapeutic": False,
    "asset_note": "非药物/非治疗性",
    "evidence_ids": ["ev_ctgov_NCT05977712"],
}
```

### company_technical_routes

Only pharma or biotech companies with therapeutic assets are included:

```python
{
    "company_name": "Eisai",
    "representative_assets": ["Lecanemab"],
    "technical_route": "anti-Aβ monoclonal antibody",
    "targets": ["Aβ"],
    "modality": "Monoclonal Antibody",
    "route_summary": "Targets amyloid beta pathology in early Alzheimer's disease.",
    "why_it_fits_disease": "Matches the amyloid-pathology disease hypothesis and approved anti-amyloid treatment class.",
    "evidence_ids": ["ev_ctgov_NCT01767311", "ev_company_eisai_pipeline"],
}
```

This section does not output risk labels.

### literature_review

The literature evidence pool is restricted to top-50 journals:

```python
{
    "journal_scope": "top_50_only",
    "year_scope": "last_5_years",
    "search_queries_used": [...],
    "records": [
        {
            "pmid": "...",
            "title": "...",
            "journal": "The Lancet Neurology",
            "year": 2024,
            "matched_targets": ["Aβ", "Tau"],
            "evidence_id": "ev_pubmed_...",
        }
    ],
    "filtered_out_count": 42,
}
```

The retrieval layer should prefer top-50 scope during search where practical. The aggregation layer must enforce the scope again so non-top-50 journals do not appear in the main Literature Review table.

### pipeline_timeline_competition_risks

Only therapeutic assets appear here:

```python
{
    "asset_name": "Lecanemab",
    "company": "Eisai / Biogen",
    "phase": "Phase 3",
    "status": "Completed",
    "timeline_risk": "中",
    "timeline_evidence": "Primary completion and results-posted fields are populated; late-stage or approved use still depends on long-term safety follow-up.",
    "competition_risk": "高",
    "competition_evidence": "Same disease and anti-Aβ class includes donanemab and historical anti-amyloid programs in late-stage or approved settings.",
    "evidence_ids": ["ev_ctgov_NCT01767311", "ev_pubmed_anti_amyloid_review"],
}
```

If required evidence is unavailable:

```python
{
    "timeline_risk": "数据不足",
    "timeline_evidence": "Missing start_date and primary_completion_date in ClinicalTrials.gov payload.",
    "competition_risk": "数据不足",
    "competition_evidence": "Target or modality unavailable, cannot assign competition bucket.",
}
```

The writer must not generate these labels.

### charts

Charts are precomputed payloads:

```python
{
    "phase_distribution": {...},
    "therapeutic_vs_non_therapeutic": {...},
    "target_distribution": {...},
    "company_route_distribution": {...},
    "top50_journal_distribution": {...},
    "literature_year_distribution": {...},
    "cns_target_alignment": {...},
    "timeline_risk_distribution": {...},
    "competition_risk_distribution": {...},
    "competition_bucket_distribution": {...},
}
```

If a chart payload is missing, the report must not invent a chart. The chapter should show a structured data insufficiency message.

### evidence_registry

All tables and paragraphs trace to evidence records:

```python
{
    "evidence_id": "ev_ctgov_NCT01767311",
    "source_type": "ClinicalTrials.gov",
    "source_url": "https://clinicaltrials.gov/study/NCT01767311",
    "title": "Lecanemab Phase 3 trial",
    "fields_used": [
        "phase",
        "status",
        "start_date",
        "primary_completion_date",
        "sponsor",
        "interventions",
    ],
}
```

## Writer Contract

The writer may:

- Generate concise summary prose from existing structured data.
- Render tables.
- Inject charts and widgets from precomputed chart payloads.
- Insert evidence references from `evidence_registry`.
- Write `数据不足` for missing data.

The writer must not:

- Create new assets.
- Create new companies.
- Create technical routes.
- Create risk labels.
- Create evidence sources.
- Fabricate market shares.
- Produce success probabilities.
- Use LLM output as a substitute for missing structured data.

Routing:

```text
If slot_disease_survey exists and validates:
    render disease report from slot_disease_survey
Else if rows look like disease survey:
    use legacy writer-side disease survey aggregation fallback and log warning
Else:
    use generic writer
```

## Report Chapters

The target disease survey report has seven chapters:

```text
1. Executive Summary
2. Drug Pipeline
3. Trial Landscape
4. Company Technical Route Analysis
5. Literature Review
6. CNS Benchmark
7. Pipeline Timeline And Competition Risk
```

The independent chapters below are removed:

```text
Sponsor Analysis
Target Biology
Safety Profile
```

Their data is fused into the company technical-route and risk chapters.

### Executive Summary

Inputs:

- `slot_disease_survey.intent`
- `slot_disease_survey.pipeline_assets`
- `slot_disease_survey.field_audit`
- `slot_a.evidence_synthesis`
- `slot_c.quality_assessment`

The writer can summarize counts and quality warnings but must not generate new facts.

Charts:

- `therapeutic_vs_non_therapeutic`
- `phase_distribution`

### Drug Pipeline

Inputs:

- `slot_disease_survey.pipeline_assets`

Columns:

```text
Asset
Company / Sponsor
Phase
Status
Modality
Targets
Therapeutic Flag
Trial IDs
Evidence
```

Rules:

- Therapeutic assets sort first.
- Non-therapeutic rows remain visible and show `非药物/非治疗性`.
- Every row includes evidence IDs or source fields.

Charts:

- `phase_distribution`
- `target_distribution`
- `therapeutic_vs_non_therapeutic`

### Trial Landscape

Inputs:

- `slot_disease_survey.pipeline_assets`
- `slot_disease_survey.evidence_registry`
- ClinicalTrials.gov timing fields

Columns:

```text
NCT ID
Asset
Company / Sponsor
Phase
Status
Enrollment
Start Date
Primary Completion Date
Completion Date
Results First Posted
Evidence
```

This chapter presents timeline facts only. It does not output risk labels.

Charts:

- `trial_status_distribution`
- `phase_distribution`
- `timeline_availability`

### Company Technical Route Analysis

Inputs:

- `slot_disease_survey.company_technical_routes`
- `slot_disease_survey.pipeline_assets`
- `slot_disease_survey.evidence_registry`

Columns:

```text
Company
Representative Assets
Technical Route
Targets
Modality
Why This Route Fits Disease
Evidence
```

Rules:

- Include only pharma or biotech companies with therapeutic pipeline assets.
- Exclude universities, hospitals, individual investigators, and non-therapeutic project sponsors.
- Do not output risk labels.
- If official source evidence is unavailable, write `数据不足`.

Charts:

- `company_route_distribution`
- `target_distribution`
- `modality_distribution`

### Literature Review

Inputs:

- `slot_disease_survey.literature_review.records`

Required display metadata:

```text
Journal Scope: top_50_only
Year Scope
Search Queries Used
Filtered Out Count
```

Columns:

```text
PMID
Title
Journal
Year
Matched Targets / Mechanisms
Evidence
```

Rules:

- Only top-50 journal records appear in the main table.
- If top-50 evidence is sparse, the chapter states that evidence is sparse under top-50 scope.
- The chapter must not fall back to broad lower-quality literature.

Charts:

- `top50_journal_distribution`
- `literature_year_distribution`
- `matched_target_distribution`

### CNS Benchmark

Inputs:

- `slot_disease_survey.literature_review`
- `slot_disease_survey.pipeline_assets.targets`

Columns:

```text
Target / Mechanism
Pipeline Assets
Top-50 Literature Count
Recent Evidence Direction
Matched
Evidence
```

Rules:

- Still constrained to top-50 journal scope.
- Evaluates target or mechanism alignment with recent high-quality CNS evidence.
- Does not output success probability.
- Does not output risk labels.

Charts:

- `cns_target_alignment`
- `top50_target_hit_distribution`

### Pipeline Timeline And Competition Risk

Inputs:

- `slot_disease_survey.pipeline_timeline_competition_risks`

Columns:

```text
Asset
Company
Phase / Status
Timeline Risk
Timeline Evidence
Competition Risk
Competition Evidence
Evidence Sources
```

Rules:

- Include only therapeutic assets.
- Risk labels are limited to `低`, `中`, `高`, or `数据不足`.
- Every risk label must have evidence.
- Missing evidence yields `数据不足`.
- Do not output success probabilities.
- Do not output fabricated market-share percentages.
- Competition risk is based on same disease, same target, same modality, same phase, or same milestone window buckets.

Charts:

- `timeline_risk_distribution`
- `competition_risk_distribution`
- `competition_bucket_distribution`

## Implementation Scope

### New Files

```text
src/graph/nodes/disease_survey_intelligence_node.py
src/engines/report_engine/disease_survey/intelligence.py
src/engines/report_engine/disease_survey/journal_scope.py
src/engines/report_engine/disease_survey/pipeline_risk.py
src/tools/company_approach_client.py
tests/test_disease_survey_intelligence_node.py
tests/test_literature_top50_scope.py
tests/test_pipeline_risk.py
```

### Modified Files

```text
src/graph/workflow.py
src/graph/state.py
src/graph/nodes/extension_handoff_node.py
src/agents/report_writer.py
src/engines/report_engine/disease_survey/models.py
src/engines/report_engine/disease_survey/aggregator.py
src/engines/report_engine/disease_survey/renderer.py
src/engines/report_engine/disease_survey/composer.py
src/engines/report_engine/disease_survey/__init__.py
tests/test_writer_slot_consumption.py
tests/test_disease_survey_aggregator.py
tests/test_disease_survey_composer.py
tests/test_disease_survey_e2e.py
```

## Migration Strategy

Phase 1:

- Add `disease_survey_intelligence_node`.
- Create `slot_disease_survey`.
- Make `extension_handoff` merge existing slots instead of overwriting them.
- Make the writer preserve and consume `synthesis_sections`.
- Render the new seven-chapter disease report when `slot_disease_survey` exists.
- Keep the old writer-side disease survey aggregation as fallback.

Phase 2:

- Add intent and entity gate for company or ticker investigations.
- Prevent BIIB/company queries from routing through the disease survey template.
- Prevent whole-query text from becoming drug, company, or graph entity.

Phase 3:

- Move legacy disease survey internals behind the handoff contract or rename them as disease intelligence internals.
- Remove writer-side aggregation fallback when the slot path is stable.

## Acceptance Criteria

### Core Gold Standard

For:

```text
conduct a comprehensive survey on Alzheimer disease
```

The workflow must generate and consume `slot_disease_survey`.

### Report Chapters

The report must contain:

```text
Executive Summary
Drug Pipeline
Trial Landscape
Company Technical Route Analysis
Literature Review
CNS Benchmark
Pipeline Timeline And Competition Risk
```

The report must not contain independent chapters:

```text
Sponsor Analysis
Target Biology
Safety Profile
```

### Writer

The writer must:

- Preserve `synthesis_sections`.
- Preserve `slot_a`, `slot_b`, `slot_c`, and `slot_disease_survey`.
- Use `slot_disease_survey` before legacy writer-side aggregation.
- Generate only summary prose and rendering output from structured data.

Tests should prove `aggregate_survey_data()` is not called in the primary writer path when a valid disease slot exists.

### Pipeline

The Drug Pipeline table must:

- Retain therapeutic assets.
- Retain non-drug or non-therapeutic projects.
- Mark non-therapeutic rows as `非药物/非治疗性`.
- Sort therapeutic assets first.
- Carry evidence IDs or source fields.

### Trial Timing

The Trial Landscape table must include:

```text
Start Date
Primary Completion Date
Completion Date
Results First Posted
```

If source payloads contain these fields, they must reach the report layer.

### Company Technical Route

The chapter must:

- Include pharma or biotech sponsors with therapeutic assets.
- Exclude universities, hospitals, individual investigators, and non-therapeutic sponsors.
- Show technical route, targets, modality, disease fit, and evidence.
- Output `数据不足` when official technical-route evidence is unavailable.
- Avoid risk labels.

### Literature Review

The chapter must:

- Display `journal_scope = top_50_only`.
- Show search queries used.
- Show filtered-out count.
- Exclude non-top-50 journals from the main table.
- Avoid broad literature fallback.

### CNS Benchmark

The chapter must:

- Use the same top-50 literature scope.
- Align targets or mechanisms with high-quality CNS evidence.
- Avoid risk labels and success probabilities.

### Pipeline Risk

The final chapter must:

- Include only therapeutic assets.
- Output timeline risk and competition risk as `低`, `中`, `高`, or `数据不足`.
- Include evidence for every risk label.
- Output `数据不足` when evidence is missing.
- Avoid fabricated market share and success probabilities.

### Charts

The report must support chart injection from the slot:

```text
phase_distribution
therapeutic_vs_non_therapeutic
target_distribution
company_route_distribution
top50_journal_distribution
timeline_risk_distribution
competition_risk_distribution
competition_bucket_distribution
```

Missing chart payloads must not produce fake charts or block report generation.

## Fallback Behavior

- Missing `slot_disease_survey`: fall back to legacy writer-side disease survey aggregation and log a warning.
- Failed company website crawl: write `数据不足` for the route and record the missing source in evidence or field audit.
- Empty top-50 literature pool: state evidence is insufficient under top-50 scope and do not show non-top-50 fallback records.
- Missing ClinicalTrials timing fields: set timeline risk to `数据不足`.
- Missing target or modality: set competition risk to `数据不足`.
- Missing `slot_a`, `slot_b`, or `slot_c`: generate the report without those summaries and record missing slots in field audit.

## Self-Review

- Scope is focused on disease-oriented reports first, with BIIB/company investigation deferred to the entity and intent gate phase.
- The design keeps current report generation available through fallback, so existing runnable behavior is not removed before replacement.
- The writer-data boundary is explicit: writer renders and summarizes but does not generate report data.
- Risk labels require evidence and degrade to `数据不足` when evidence is missing.
- Literature Review and CNS Benchmark share the top-50 journal constraint.
- No section requires fabricated probabilities, market shares, or ungrounded route analysis.
