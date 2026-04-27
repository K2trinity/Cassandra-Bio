# Disease Report Single-Pipeline Redesign

Date: 2026-04-27

## Purpose

Redesign Cassandra into one clear disease report generation pipeline. The new
pipeline replaces the current mixture of generic harvest, extension handoff,
disease survey side branches, writer fallback logic, and report-time data
guessing.

The target report can investigate any disease, starting with Alzheimer Disease
as the first regression case. Harvested ClinicalTrials.gov records must be
directly relevant to the target disease, source fields must flow into the
handoff contract without being dropped, and the final report must consume the
structured data rather than reconstructing it inside the writer.

The new report focuses on ClinicalTrials.gov disease pipeline intelligence.
Literature review, CNS benchmark, and company technical route chapters are out
of scope for the first implementation. The company route interface remains as a
future extension point but does not render in the report.

## Current Architecture

The current backend behaves like a stateful agent graph:

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

The graph stores broad harvested records in shared state, then later attaches
extension payloads such as `slot_disease_survey`. The writer inspects the state,
detects disease-survey-like input, and chooses between a slot-based renderer or
a legacy harvest-based fallback.

This is effectively a hybrid architecture:

- Pipeline orchestration through graph nodes.
- Shared mutable state as the integration contract.
- Generic harvest data reused by multiple downstream consumers.
- Writer-side report routing and fallback behavior.
- Disease survey aggregation living beside the generic flow rather than owning a
  first-class pipeline.

This architecture made the first structured report possible, but it now causes
core quality failures:

- Disease-specific harvest is not enforced at the source boundary.
- ClinicalTrials.gov fields can be parsed upstream but dropped during disease
  survey aggregation.
- The writer can silently fall back to legacy aggregation, so there is no single
  authoritative data contract.
- Report chapters still reflect old generic disease survey concepts such as
  drug pipeline, trial landscape, literature review, CNS benchmark, and company
  route analysis.
- Risk logic depends on missing target or modality fields even when the new
  report should be trial-oriented.
- PDF table layout is treated as a renderer problem rather than a report IR
  design constraint.

## Architecture Decision

Use a single-purpose report pipeline with typed handoff contracts and
ports/adapters boundaries.

The new architecture is closer to a clean pipeline plus hexagonal adapters:

```text
User Query
  -> DiseaseReportOrchestrator
  -> DiseaseResolver
  -> ClinicalTrialsConditionDiscovery
  -> ClinicalTrialsDiseaseHarvester
  -> SourceFieldNormalizer
  -> DiseaseRelevanceGate
  -> DiseaseReportPackageBuilder
  -> RuleBasedRiskEngine
  -> ReportIRBuilder
  -> Renderers
```

The orchestrator is the only entry point for this report type. It coordinates
the flow but does not parse source payloads, score risk, or render tables.

ClinicalTrials.gov is accessed through a source adapter. The adapter exposes
structured records and hides API or expert-search details from the rest of the
system.

The handoff contract is a typed `DiseaseReportPackage`. The writer and renderers
consume only this package. They do not inspect raw harvest rows and do not
rebuild pipeline data.

The writer becomes a deterministic report composer over structured data. An LLM
may later be used for prose polishing, but it must not choose records, invent
fields, classify risk, or decide report structure.

## Alternatives Considered

### Keep The Current Graph And Patch It

This would fix status propagation and add disease relevance filtering inside
`disease_survey_intelligence_node`.

It is rejected because the project would still have two report paths:

- generic harvest state
- disease survey slot side branch

The writer would still need routing and fallback behavior, and future bugs would
again appear at state and slot boundaries.

### Add A New Disease Survey Slot Beside Existing Generic Harvest

This would formalize `slot_disease_survey` but leave generic harvest and writer
fallback in place.

It is rejected because the user wants one project architecture, not parallel
flows. It also keeps the wrong ownership model: generic harvest collects broad
data, then a later side branch tries to clean it.

### Single Disease Report Pipeline

This is selected.

It removes hidden branches, makes source relevance an upstream requirement, and
turns downstream reporting into a structured rendering problem. It also gives
the project a simpler mental model: one orchestrator, one data package, one
writer path.

## Target Report Shape

The first version of the redesigned report has three chapters:

```text
1. Executive Summary
2. Clinical Trial And Pipeline Landscape
3. Pipeline Timeline And Competition Risk
```

The following chapters are removed from this report:

```text
Company Technical Route Analysis
Literature Review
CNS Benchmark
```

Company technical route support remains as a dormant interface:

```text
CompanyRouteProvider
```

It is not invoked by the report pipeline and does not render a chapter until a
future phase explicitly enables it.

## ClinicalTrials.gov Search Design

The user-facing search semantics follow ClinicalTrials.gov Expert Search.

Step 1: discover the best disease condition term:

```text
https://clinicaltrials.gov/expert-search?term=[disease name]&viewType=Topic
```

The condition term selected from this page is the disease anchor for the report.
For Alzheimer Disease, the resolver must treat these as equivalent:

```text
Alzheimer Disease
Alzheimer's Disease
Alzheimers Disease
```

Step 2: retrieve the latest 50 studies with condition full-match semantics:

```text
https://clinicaltrials.gov/expert-search?term=AREA[Condition]COVERAGE[FullMatch[Disease name]&viewType=Card&sort=StudyFirstPostDate
```

The implementation should preserve this expert-search URL in the source audit
and report metadata for traceability.

The structured data should be fetched through the ClinicalTrials.gov API where
possible. If the API cannot directly evaluate the exact expert-search expression,
the source adapter must implement equivalent local filtering:

- Search the condition area for the selected disease term.
- Normalize apostrophes, possessive forms, punctuation, case, and whitespace.
- Keep only records whose `Conditions` field full-matches one of the selected
  disease condition terms.
- Deduplicate by NCT number.
- Sort by Study First Posted descending.
- Keep the first 50 records.

Records that mention the disease only in title, summary, endpoint, or context
are not sufficient unless `Conditions` also match the target disease.

## Required Report Table Fields

The merged chapter `Clinical Trial And Pipeline Landscape` replaces the old
`Drug Pipeline` and `Trial Landscape` tables.

The report table has exactly these display columns:

```text
Study Title
NCT Number
Status
Conditions
Interventions
Sponsor
Study Type
```

These fields are removed from the disease report data contract and display:

```text
Enrollment
Primary Endpoint
```

The data package may still carry source timing fields needed for the risk
engine, but the main landscape table must not display enrollment or endpoint
columns.

## Source Field Contract

The normalized ClinicalTrials record is:

```python
ClinicalTrialRecord(
    study_title: str,
    nct_number: str,
    status: str,
    conditions: list[str],
    interventions: list[str],
    sponsor: str,
    study_type: str,
    study_first_posted: date | None,
    last_update_posted: date | None,
    start_date: date | None,
    primary_completion_date: date | None,
    completion_date: date | None,
    source_url: str,
)
```

The normalizer must read fields from the raw ClinicalTrials.gov API payload
first. If an intermediate parsed dictionary is used, field lookup must check all
known aliases before defaulting.

Status lookup must include:

```text
protocolSection.statusModule.overallStatus
status
study_status
metadata.status
metadata.study_status
metadata.overall_status
```

This specifically fixes the current bug where ClinicalTrials.gov status is
available upstream but disappears in the disease survey report because the old
aggregator reads only `metadata.status` and `metadata.overall_status`.

## Relevance Gate

The pipeline must audit harvested records before they enter the report package.
This is an internal gate, not a user-visible data quality chapter.

Rules:

- Keep records whose `Conditions` full-match the disease profile terms.
- Treat possessive and non-possessive disease names as equivalent.
- Reject records whose conditions are clearly another disease without the target
  disease condition.
- Reject records that mention the disease only outside the `Conditions` field.
- Do not allow broad terms such as cognitive dysfunction, dementia, mild
  cognitive impairment, caregiver, or education to replace the target disease.
- Deduplicate records by NCT number after filtering.

This prevents Parkinson Disease, heart failure, stroke, nursing career, and
generic caregiver interventions from entering an Alzheimer Disease report unless
the target disease is actually present in Conditions.

## Risk Engine

Risk scoring is deterministic. The LLM must not define risk labels.

The risk chapter emphasizes:

```text
pipeline timeline is long
market competition is crowded
```

### Pipeline Timeline Risk

Inputs:

- Status
- Study First Posted
- Last Update Posted
- Start Date
- Primary Completion Date
- Completion Date
- Current date

Example deterministic rules:

- `High`: study age is more than 5 years and status is still recruiting, active
  not recruiting, unknown, or not yet recruiting.
- `Medium`: study age is 2 to 5 years and status is still not terminal.
- `Low`: study is completed, or first posted within the last 2 years and has
  recent update evidence.
- `Data insufficient`: required timing fields are missing.

The evidence text must include the input values used, for example:

```text
Study first posted 2018-04-10; status RECRUITING; age 8.0 years.
```

### Market Competition Risk

Inputs:

- Disease scope: all retained studies are in the same target disease.
- Intervention text.
- Sponsor.
- Study type.
- Study first posted window.

Intervention categories are rule-based. The first implementation can use a small
deterministic taxonomy:

```text
amyloid antibody
tau therapy
small molecule
cell therapy
device
diagnostic or imaging
behavioral intervention
care delivery
other
```

Example deterministic rules:

- `High`: same intervention category appears in at least 8 retained trials.
- `Medium`: same intervention category appears in 3 to 7 retained trials.
- `Low`: same intervention category appears in 1 to 2 retained trials.
- `Data insufficient`: intervention text cannot be categorized.

The evidence text must include the count:

```text
8 retained Alzheimer Disease studies share intervention category amyloid antibody.
```

## Report Data Package

The handoff object is the only writer input:

```python
DiseaseReportPackage(
    disease_profile=DiseaseProfile,
    clinical_trials=list[ClinicalTrialRecord],
    risk_records=list[PipelineRiskRecord],
    source_audit=SourceAudit,
    generated_at=datetime,
)
```

`source_audit` is for logs, tests, and debugging. It does not render as a formal
report chapter in this phase.

The writer must not accept raw harvested rows for disease reports.

## Rendering And Layout

The report IR must be designed for wide clinical trial tables before rendering.

The landscape table requirements:

- `Study Title` is the widest column and wraps cleanly.
- `NCT Number`, `Status`, and `Study Type` use fixed compact widths.
- `Conditions` and `Interventions` support wrapped lists or compact chips in
  HTML.
- PDF output uses a wide-table layout, landscape page strategy, or controlled
  column wrapping.
- Tables paginate predictably at 50 rows.
- Markdown output remains readable, even if HTML and PDF use richer layout.

Renderer-level emergency compression should not be the primary layout strategy.
The IR builder must encode table intent so each renderer can choose the correct
layout.

## Parallelism And Runtime Optimization

The redesigned pipeline should support bounded parallelism without making data
ownership unclear.

Safe parallel stages:

1. Disease condition discovery can query multiple normalized variants in
   parallel:

```text
Alzheimer Disease
Alzheimer's Disease
Alzheimers Disease
```

2. ClinicalTrials retrieval can fetch pages or condition variants in parallel
   when the API permits independent requests. Pagination that depends on
   `nextPageToken` remains sequential per query, but separate query variants can
   run concurrently and then deduplicate by NCT number.

3. Normalization and relevance checks are per-record pure functions and can run
   in parallel over the fetched studies.

4. Timeline risk and competition category extraction can run after relevance
   filtering. Timeline risk is per record and parallelizable. Competition counts
   need one shared aggregate, so the efficient design is:

```text
parallel intervention category extraction
-> aggregate category counts
-> parallel risk row assembly
```

5. HTML, PDF, and Markdown rendering can run in parallel after the report IR is
   complete, as long as they write separate artifacts.

Stages that should stay sequential:

- Disease profile selection must complete before disease-scoped retrieval.
- Relevance gate must complete before report package building.
- Report package building must complete before report IR.
- Report IR must complete before renderer-specific artifact generation.

This gives a clear DAG:

```text
Resolve disease
  -> discover condition variants in parallel
  -> fetch studies in bounded parallel groups
  -> normalize records in parallel
  -> relevance gate
  -> category extraction in parallel
  -> aggregate competition counts
  -> risk row assembly in parallel
  -> build report package
  -> build report IR
  -> render markdown/html/pdf in parallel
```

Bounded concurrency should be explicit, for example 4 to 8 network requests at a
time, to avoid ClinicalTrials.gov throttling and local renderer contention.

## Project Structure

Replace the current disease survey side-branch package with a cohesive report
package:

```text
src/reports/disease/
  __init__.py
  orchestrator.py
  models.py
  resolver.py
  clinicaltrials_harvester.py
  condition_matcher.py
  normalizer.py
  relevance.py
  package_builder.py
  risk_engine.py
  ir_builder.py
  renderer_adapter.py
  company_routes.py
```

Responsibilities:

- `orchestrator.py`: owns the report pipeline DAG.
- `models.py`: owns typed contracts.
- `resolver.py`: maps user query to disease profile.
- `condition_matcher.py`: selects the best ClinicalTrials condition term.
- `clinicaltrials_harvester.py`: fetches disease-scoped studies.
- `normalizer.py`: converts raw source payloads to `ClinicalTrialRecord`.
- `relevance.py`: enforces condition full-match filtering.
- `package_builder.py`: assembles `DiseaseReportPackage`.
- `risk_engine.py`: deterministic timeline and competition risk.
- `ir_builder.py`: report chapters, tables, charts, and layout hints.
- `renderer_adapter.py`: calls markdown, HTML, and PDF renderers.
- `company_routes.py`: dormant extension interface, not rendered.

The existing `src/engines/report_engine/renderers` can remain as rendering
infrastructure, but disease report business logic should move out of
`src/engines/report_engine/disease_survey`.

## Dead Code And Removal Plan

Remove or migrate these disease-report paths:

- Legacy `aggregate_survey_data` drug asset aggregation.
- Writer-side disease survey detection and fallback.
- `slot_disease_survey` as an extension payload side branch.
- `Drug Pipeline` and `Trial Landscape` separate table builders.
- Company technical route report chapter.
- Literature review report chapter.
- CNS benchmark report chapter.
- Modality and target distribution charts for the new disease report.
- Enrollment and primary endpoint fields in disease report display and contract.
- Risk logic that depends on missing target or modality fields.

Keep or adapt:

- ClinicalTrials.gov low-level API request code.
- Shared renderer infrastructure.
- Company technical route client as a future interface.
- Generic app shell and artifact save utilities, if they do not impose the old
  generic agent data contract.

## Testing Strategy

Add deterministic tests before implementation.

Resolver tests:

- `Alzheimer disease`, `Alzheimer's disease`, and `Alzheimers disease` resolve
  to one disease profile.

Harvester and relevance tests:

- Mock ClinicalTrials studies with Parkinson-only conditions are filtered out
  even if title mentions Alzheimer.
- Mock studies with `Alzheimer Disease` or `Alzheimer's Disease` conditions are
  retained.
- Returned records are sorted by Study First Posted descending.
- Output is capped at 50 retained records.

Field propagation tests:

- `statusModule.overallStatus` appears in `ClinicalTrialRecord.status`.
- `status`, `study_status`, and metadata aliases are covered.
- Report table displays Status.
- Enrollment and Primary Endpoint do not appear in the disease report contract
  or output.

Risk tests:

- Long-running non-terminal studies produce high timeline risk.
- Completed recent studies produce low timeline risk.
- Crowded intervention categories produce high market competition risk.
- Uncategorized intervention text produces data insufficient competition risk.

Rendering tests:

- Report contains only the three approved chapters.
- Landscape table uses exactly the seven approved display columns.
- HTML and PDF renderers receive wide-table layout hints.
- Markdown, HTML, and PDF artifact generation use the same report IR.

## Implementation Phases

Phase 1: new typed models, disease resolver, ClinicalTrials source adapter,
normalizer, and relevance gate.

Phase 2: report package builder and deterministic risk engine.

Phase 3: report IR builder and revised writer path with the three approved
chapters.

Phase 4: remove legacy disease survey side branches and writer fallback.

Phase 5: renderer layout improvements for wide clinical trial tables.

Phase 6: optional high-impact literature module or company route module, added
only as explicit future extensions to the single pipeline.

## Acceptance Criteria

- There is one disease report generation path.
- Disease reports do not use writer-side legacy fallback.
- ClinicalTrials records are filtered by disease condition relevance before
  report package construction.
- Status and other source fields are preserved from upstream to report output.
- The merged landscape table has exactly the approved seven columns.
- Enrollment and Primary Endpoint are absent.
- Removed chapters do not render.
- Risk labels are rule-based and evidence-backed.
- Markdown, HTML, and PDF are generated from the same report IR.
- The project structure has cohesive report modules and no hidden disease survey
  side branch.
