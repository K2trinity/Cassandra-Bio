# Investigation ClinicalTrials Disease And Company Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let `/investigation` search ClinicalTrials.gov by either disease/condition or company/sponsor, with company mode using Catalyst Tracker, Expansion Map, and Track Record sponsor queries.

**Architecture:** Keep the existing disease report pipeline and add a small target-mode layer. Explicit UI mode is passed through `/api/analyze` into `WorkflowService` and `DiseaseReportOrchestrator`; disease mode keeps condition full-match filtering, while company mode resolves a company name, queries `query.spons`, dedupes NCT IDs across company strata, and renders source-grounded stratum labels.

**Tech Stack:** Flask, Jinja/vanilla JS, Python 3.11, Pydantic, ClinicalTrials.gov API v2, pytest with repo-local `--basetemp`.

---

## Scope Guard

Do not edit K-line, backtest, or portfolio files for this plan.

Out of scope:

- `src/backtest/**`
- `src/kline/**`
- `static/kline/**`
- `tests/test_kline_*`
- `tests/test_backtest_*`
- biotech download or portfolio runner files

The current worktree already has unrelated dirty files. Do not commit from this plan unless the user explicitly requests a commit; commits would risk capturing earlier edits in shared files such as `app.py` and `templates/index.html`.

## File Structure

Modify:

- `templates/index.html` - add disease/company segmented mode control and include `analysis_target_type` in the analyze request.
- `app.py` - parse, validate, store, and forward `analysis_target_type`.
- `src/services/workflow_service.py` - accept and forward target mode.
- `src/reports/disease/models.py` - add target metadata and ClinicalTrials phase/results/strata fields.
- `src/reports/disease/company_routes.py` - replace dormant noop-only extension with company target resolution helpers.
- `src/reports/disease/clinicaltrials_harvester.py` - add company sponsor-layer fetches and layer-preserving dedupe.
- `src/reports/disease/normalizer.py` - normalize phase, has-results, outcomes, enrollment, and strata fields.
- `src/reports/disease/orchestrator.py` - route disease/company modes, skip condition relevance filtering in company mode, and emit target metadata.
- `src/reports/disease/package_builder.py` - sort by stratum-aware keys and preserve stratum counts in source audit details.
- `src/reports/disease/narrative.py` - include target type, stratum summaries, and source-grounding rules in LLM payload/prompt.
- `src/reports/disease/ir_builder.py` - render target-aware title, phase/results/stratum columns, and stratum summary KPI/table.
- `tests/test_investigation_ui.py`
- `tests/reports/disease/test_workflow_service.py`
- `tests/reports/disease/test_models.py`
- `tests/reports/disease/test_normalizer_and_relevance.py`
- `tests/reports/disease/test_clinicaltrials_harvester.py`
- `tests/reports/disease/test_package_builder.py`
- `tests/reports/disease/test_narrative.py`
- `tests/reports/disease/test_ir_builder.py`
- `tests/reports/disease/test_end_to_end_pipeline.py`

Create:

- `tests/reports/disease/test_company_routes.py` - target-mode and company-name resolution tests.

---

## Task 1: UI And API Target Mode Plumbing

**Files:**

- Modify: `templates/index.html`
- Modify: `app.py`
- Modify: `src/services/workflow_service.py`
- Modify: `tests/test_investigation_ui.py`
- Modify: `tests/reports/disease/test_workflow_service.py`

- [ ] **Step 1: Write failing UI/API tests**

Add tests that assert:

- `/investigation` contains `data-testid="analysis-target-mode"`.
- The page includes `value="disease"` and `value="company"` mode controls.
- The JavaScript appends `analysis_target_type` to the `FormData`.
- Flask accepts `analysis_target_type` in JSON and FormData, rejects unknown values with HTTP 400, and forwards valid values to `WorkflowService.stream`.
- `WorkflowService.run()` and `WorkflowService.stream()` forward `analysis_target_type` into the orchestrator.

Run:

```powershell
New-Item -ItemType Directory -Force -Path '.pytest_tmp' | Out-Null
pytest tests/test_investigation_ui.py tests/reports/disease/test_workflow_service.py -q --basetemp .pytest_tmp\investigation-target-ui
```

Expected: FAIL because target mode controls and backend plumbing do not exist.

- [ ] **Step 2: Implement the UI control**

Add a compact segmented control inside the Research Query form, between the textarea and launch buttons:

- Radio value `disease`, checked by default, label `Disease landscape`.
- Radio value `company`, label `Company pipeline`.
- Container test marker `data-testid="analysis-target-mode"`.

Update submit JS to read the checked radio and append:

```javascript
formData.append('analysis_target_type', analysisTargetType);
```

Update the quick-query buttons so one example is company-oriented, for example `Analyze Vertex Pharmaceuticals clinical pipeline`.

- [ ] **Step 3: Implement API and workflow forwarding**

In `app.py`, parse `analysis_target_type` from JSON/FormData, normalize missing values to `auto`, allow only `auto`, `disease`, and `company`, save it in `active_analysis`, pass it to `_workflow_service.stream()` and `_workflow_service.run()`, and include it in the completion payload.

In `src/services/workflow_service.py`, add `analysis_target_type: str = "auto"` to `run()` and `stream()` and forward it to the orchestrator.

- [ ] **Step 4: Run target-mode plumbing tests**

Run:

```powershell
pytest tests/test_investigation_ui.py tests/reports/disease/test_workflow_service.py -q --basetemp .pytest_tmp\investigation-target-ui
```

Expected: PASS.

---

## Task 2: Target Resolution And Company Profile Metadata

**Files:**

- Modify: `src/reports/disease/models.py`
- Modify: `src/reports/disease/company_routes.py`
- Modify: `tests/reports/disease/test_models.py`
- Create: `tests/reports/disease/test_company_routes.py`

- [ ] **Step 1: Write failing model/resolver tests**

Add tests for:

- `DiseaseProfile(target_type="disease")` remains backwards compatible.
- A company profile can carry `target_type="company"` and `company_name="Vertex Pharmaceuticals"`.
- Explicit mode wins over inference.
- `auto` infers company for `conduct a comprehensive survey on Vertex Pharmaceuticals`.
- `auto` infers company for `company pipeline for Eli Lilly and Company`.
- `auto` stays disease for `conduct a comprehensive survey on Alzheimer disease`.
- Disease cues override company suffix-like text unless explicit company mode is supplied.

Run:

```powershell
pytest tests/reports/disease/test_models.py tests/reports/disease/test_company_routes.py -q --basetemp .pytest_tmp\target-resolution
```

Expected: FAIL because company profile fields and target resolver do not exist.

- [ ] **Step 2: Extend models**

Add to `DiseaseProfile`:

```python
target_type: Literal["disease", "company"] = "disease"
company_name: str | None = None
target_name: str | None = None
```

Add to `ClinicalTrialRecord`:

```python
phases: list[str] = Field(default_factory=list)
has_results: bool = False
study_results: str = "No posted results"
results_url: str = ""
enrollment: int | None = None
primary_outcome_measures: list[str] = Field(default_factory=list)
secondary_outcome_measures: list[str] = Field(default_factory=list)
results_first_posted: date | None = None
strata: list[str] = Field(default_factory=list)
primary_stratum: str = "unclassified"
```

- [ ] **Step 3: Implement target resolution**

In `company_routes.py`, add:

- `VALID_ANALYSIS_TARGET_TYPES = {"auto", "disease", "company"}`
- `normalize_analysis_target_type(value: str | None) -> str`
- `resolve_analysis_target(user_query: str, requested_target_type: str | None, disease_resolver: DiseaseResolver | None = None) -> DiseaseProfile`

For company mode, return a `DiseaseProfile` with:

- `target_type="company"`
- `company_name` and `target_name` set to the parsed company
- disease/condition compatibility fields set to the company name with empty `condition_terms` and `normalized_terms`
- ClinicalTrials.gov expert URLs using sponsor search terms for traceability

- [ ] **Step 4: Run target resolution tests**

Run:

```powershell
pytest tests/reports/disease/test_models.py tests/reports/disease/test_company_routes.py -q --basetemp .pytest_tmp\target-resolution
```

Expected: PASS.

---

## Task 3: Company Sponsor-Layer ClinicalTrials Fetch

**Files:**

- Modify: `src/reports/disease/clinicaltrials_harvester.py`
- Modify: `tests/reports/disease/test_clinicaltrials_harvester.py`

- [ ] **Step 1: Write failing company harvester tests**

Add tests that assert company mode issues exactly these layer queries:

- Catalyst: `query.spons=Vertex Pharmaceuticals`, `filter.overallStatus=ACTIVE_NOT_RECRUITING`, `filter.advanced=AREA[Phase](PHASE2 OR PHASE3)`, `sort=PrimaryCompletionDate:asc`, `pageSize=30`.
- Expansion: `query.spons=Vertex Pharmaceuticals`, `filter.overallStatus=RECRUITING`, `sort=StudyFirstPostDate:desc`, `pageSize=50`.
- Track Record: `query.spons=Vertex Pharmaceuticals`, `filter.advanced=AREA[HasResults]true`, `sort=LastUpdatePostDate:desc`, `pageSize=30`.

Also assert duplicated NCT IDs preserve all strata and choose primary stratum in order `catalyst`, `track_record`, `expansion`.

Run:

```powershell
pytest tests/reports/disease/test_clinicaltrials_harvester.py -q --basetemp .pytest_tmp\company-harvester
```

Expected: FAIL because company-layer fetching does not exist.

- [ ] **Step 2: Implement company fetch**

Add `ClinicalTrialsCompanyHarvester.fetch_raw_studies(profile, max_records=80)`.

Use the same pagination, token-loop protection, `raw_count`, and `RawClinicalTrialsResult` shape as disease fetching. Copy each retained study before attaching metadata:

```python
study.setdefault("metadata", {})
study["metadata"]["strata"] = sorted_strata
study["metadata"]["primary_stratum"] = primary_stratum
study["metadata"]["analysis_target_type"] = "company"
study["metadata"]["company_name"] = profile.company_name
```

Use `sort=PrimaryCompletionDate:asc`, not `@PrimaryCompletionDate:asc`.

- [ ] **Step 3: Run company harvester tests**

Run:

```powershell
pytest tests/reports/disease/test_clinicaltrials_harvester.py -q --basetemp .pytest_tmp\company-harvester
```

Expected: PASS.

---

## Task 4: Normalize Fields And Report Strata

**Files:**

- Modify: `src/reports/disease/normalizer.py`
- Modify: `src/reports/disease/package_builder.py`
- Modify: `src/reports/disease/narrative.py`
- Modify: `src/reports/disease/ir_builder.py`
- Modify: `tests/reports/disease/test_normalizer_and_relevance.py`
- Modify: `tests/reports/disease/test_package_builder.py`
- Modify: `tests/reports/disease/test_narrative.py`
- Modify: `tests/reports/disease/test_ir_builder.py`

- [ ] **Step 1: Write failing propagation/rendering tests**

Add tests that assert:

- `normalize_trial_payload()` preserves `phases`, `hasResults`, `resultsFirstPostDateStruct`, enrollment count, outcome measures, and metadata strata.
- Package audit details include stratum counts and target metadata.
- Narrative payload includes target type and stratum summaries without mutating the package.
- IR landscape table includes `Stratum`, `Phase`, and `Results` visible columns.

Run:

```powershell
pytest tests/reports/disease/test_normalizer_and_relevance.py tests/reports/disease/test_package_builder.py tests/reports/disease/test_narrative.py tests/reports/disease/test_ir_builder.py -q --basetemp .pytest_tmp\clinical-field-propagation
```

Expected: FAIL because field propagation and visible columns are incomplete.

- [ ] **Step 2: Implement propagation**

Normalize nested ClinicalTrials.gov v2 fields from:

- `protocolSection.designModule.phases`
- top-level `hasResults`
- `protocolSection.statusModule.resultsFirstPostDateStruct.date`
- `protocolSection.designModule.enrollmentInfo.count`
- `protocolSection.outcomesModule.primaryOutcomes[].measure`
- `protocolSection.outcomesModule.secondaryOutcomes[].measure`
- `metadata.strata`
- `metadata.primary_stratum`

Update package/narrative/IR builders to use these fields directly. Do not let narrative generation overwrite source fields.

- [ ] **Step 3: Run propagation/rendering tests**

Run:

```powershell
pytest tests/reports/disease/test_normalizer_and_relevance.py tests/reports/disease/test_package_builder.py tests/reports/disease/test_narrative.py tests/reports/disease/test_ir_builder.py -q --basetemp .pytest_tmp\clinical-field-propagation
```

Expected: PASS.

---

## Task 5: Orchestrator Company Mode Integration

**Files:**

- Modify: `src/reports/disease/orchestrator.py`
- Modify: `tests/reports/disease/test_end_to_end_pipeline.py`
- Modify: `tests/reports/disease/test_workflow_service.py`

- [ ] **Step 1: Write failing integration tests**

Add an end-to-end company test that runs:

```python
orchestrator.run(
    "conduct a comprehensive survey on Vertex Pharmaceuticals",
    analysis_target_type="company",
    output_dir=tmp_path,
)
```

Assert:

- `analysis_focus == "COMPANY_CLINICALTRIALS_PIPELINE"`.
- `biomedical_profile.target_type == "company"` or equivalent target metadata is present.
- The fake ClinicalTrials getter sees `query.spons`.
- No disease condition full-match rejection removes sponsor-matched records.
- Final report contains `Catalyst Tracker`, `Expansion Map`, `Track Record`, phase, results, and retained NCT IDs.

Run:

```powershell
pytest tests/reports/disease/test_end_to_end_pipeline.py tests/reports/disease/test_workflow_service.py -q --basetemp .pytest_tmp\company-integration
```

Expected: FAIL because the orchestrator still always uses the disease harvester and relevance gate.

- [ ] **Step 2: Implement orchestrator branch**

In `DiseaseReportOrchestrator.stream()`:

- Resolve target with `resolve_analysis_target(user_query, analysis_target_type, self.resolver)`.
- Use `ClinicalTrialsDiseaseHarvester` plus relevance gate for disease mode.
- Use `ClinicalTrialsCompanyHarvester` and skip disease relevance gate for company mode.
- Build risk records from retained company trials, using company target metadata.
- Emit target metadata in `harvest_state`, `clinical_data`, `biomedical_profile`, and completion payload fields already consumed by the UI.

- [ ] **Step 3: Run company integration tests**

Run:

```powershell
pytest tests/reports/disease/test_end_to_end_pipeline.py tests/reports/disease/test_workflow_service.py -q --basetemp .pytest_tmp\company-integration
```

Expected: PASS.

---

## Final Verification

Run:

```powershell
pytest tests/test_investigation_ui.py tests/reports/disease/test_company_routes.py tests/reports/disease/test_models.py tests/reports/disease/test_normalizer_and_relevance.py tests/reports/disease/test_clinicaltrials_harvester.py tests/reports/disease/test_package_builder.py tests/reports/disease/test_narrative.py tests/reports/disease/test_ir_builder.py tests/reports/disease/test_end_to_end_pipeline.py tests/reports/disease/test_workflow_service.py -q --basetemp .pytest_tmp\investigation-clinicaltrials-company-final
```

Expected: all selected tests pass.
