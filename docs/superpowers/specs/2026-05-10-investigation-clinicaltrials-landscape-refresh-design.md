# Investigation ClinicalTrials Disease And Company Search Design

Date: 2026-05-10

## Scope

Refresh the `investigation` ClinicalTrials.gov path without rebuilding the whole pipeline:

- Use Vertex AI `global` so Cassandra can call the latest available Gemini models.
- Keep ClinicalTrials.gov as the source of truth for trial facts.
- Add missing ClinicalTrials fields to the data model, filters, tables, and narratives.
- Add simple objective landscape strata instead of returning one flat newest-trial list.
- Add an explicit disease/company search mode in the Investigation UI.
- Support company-oriented ClinicalTrials.gov sponsor search with catalyst, expansion, and track-record layers.
- Keep LLM usage constrained so it cannot rewrite source facts or fabricate evidence.

## Model Configuration

Runtime model configuration should use the verified `global` Vertex endpoint:

- `GOOGLE_CLOUD_LOCATION=global`
- Report model: `gemini-3.1-pro-preview`
- Harvest/query model: `gemini-3.1-flash-lite`
- Fallback chain: `gemini-3.1-pro-preview`, `gemini-3-flash-preview`, `gemini-3.1-flash-lite`, `gemini-2.5-pro`, `gemini-2.5-flash`, `gemini-2.5-flash-lite`
- Report temperature: `1.0`

The previous regional setting, `asia-northeast1`, only exposed `gemini-2.5-pro` and `gemini-2.5-flash` in the current project during verification. The same project could call Gemini 3.1 / 3.x models from `global`.

## ClinicalTrials Field Additions

The report should preserve and present these fields from ClinicalTrials.gov where available:

- `phase` / `phases`
- `status`
- `has_results`
- `study_results` / results availability
- `results_first_posted`
- `last_update_posted`
- `study_first_posted`
- `primary_outcome_measures`
- `secondary_outcome_measures`
- `enrollment`
- `study_type`
- `sponsor`
- `interventions`
- `source_url`

The minimum visible report additions are `Phase`, `Status`, and `Results`. Other fields can support filtering, narrative summaries, or expandable detail.

## Investigation Target Mode

The UI should expose a required operator choice before launch:

- `Disease landscape` searches by disease/condition and keeps the current condition full-match safety checks.
- `Company pipeline` searches by sponsor/company and skips disease full-match filtering because ClinicalTrials.gov sponsor matching is the source boundary.

Backend request payloads carry `analysis_target_type` with values `disease`, `company`, or `auto`.

Target-mode resolution rules:

1. Explicit UI value wins.
2. `auto` or missing mode uses conservative inference for backwards compatibility.
3. Disease remains the default.
4. Company inference requires either sponsor/company/pipeline wording or a company suffix such as `Pharmaceuticals`, `Therapeutics`, `Biotech`, `Biosciences`, `Inc`, `Corp`, `Corporation`, `PLC`, `Ltd`, `AG`, `SA`, or `GmbH`.
5. Disease cues such as `disease`, `syndrome`, `cancer`, `carcinoma`, `tumor`, `infection`, `disorder`, and `deficiency` override company inference unless the explicit UI mode is `company`.

This split prevents prompts like `conduct a comprehensive survey on Vertex Pharmaceuticals` from being treated as a disease while preserving legacy disease prompts such as `conduct a comprehensive survey on Alzheimer disease`.

## Stratified ClinicalTrials Search

Use a lightweight deterministic stratification policy. The goal is not a complicated new architecture; it is a clearer data retrieval and presentation contract.

### Foundation

Purpose: anchor current treatment standard and late-stage competitive baseline.

Suggested filter:

- Phase: `PHASE3`, `PHASE4`
- Status: `ACTIVE_NOT_RECRUITING`, `COMPLETED`
- Sort: relevance or `LastUpdatePostDate:desc`
- Target count: 20-30

### Frontier

Purpose: identify new mechanisms, targets, and early innovation.

Suggested filter:

- Phase: `PHASE1`, `PHASE2`
- Status: `RECRUITING`, `NOT_YET_RECRUITING`
- Sort: `StudyFirstPostDate:desc`
- Target count: 20-30

### Evidence

Purpose: focus on posted scientific facts and reduce market-noise dependence.

Suggested filter:

- Results: `hasResults=true` / `results:with`
- Sort: `LastUpdatePostDate:desc`
- Target count: 10-20
- For selected trials, fetch the detailed results payload when affordable.

## Company ClinicalTrials Search

Company mode uses ClinicalTrials.gov API v2 `/api/v2/studies` with `query.spons` set to the normalized company name. The public v2 endpoint accepts sort values such as `PrimaryCompletionDate:asc`; the `@PrimaryCompletionDate:asc` UI/internal-search style is not accepted by the public endpoint.

### Catalyst Tracker

Purpose: identify event-driven readouts that may matter over the next 3-6 months.

API parameters:

- `query.spons`: normalized company name, for example `Vertex Pharmaceuticals`
- `filter.overallStatus`: `ACTIVE_NOT_RECRUITING`
- `filter.advanced`: `AREA[Phase](PHASE2 OR PHASE3)`
- `sort`: `PrimaryCompletionDate:asc`
- `pageSize`: `30`

Returned trials receive `strata=["catalyst"]` unless they also appear in another company layer.

### Expansion Map

Purpose: identify where the company is actively deploying R&D resources.

API parameters:

- `query.spons`: normalized company name
- `filter.overallStatus`: `RECRUITING`
- `sort`: `StudyFirstPostDate:desc`
- `pageSize`: `50`

Returned trials receive `strata=["expansion"]`.

### Track Record

Purpose: build an evidence base from posted results and recent updates.

API parameters:

- `query.spons`: normalized company name
- `filter.advanced`: `AREA[HasResults]true`
- `sort`: `LastUpdatePostDate:desc`
- `pageSize`: `30`

Returned trials receive `strata=["track_record"]`.

Company-mode primary stratum priority:

1. `catalyst`
2. `track_record`
3. `expansion`

The report should also aggregate condition counts from company-mode trials so users can see where the company is concentrating current development.

## Deduplication And Layer Labels

Deduplicate by `NCTId`, but do not discard layer membership.

If a trial appears in multiple layers, keep one record and attach all matched strata, for example:

```json
{
  "nct_number": "NCT...",
  "strata": ["catalyst", "track_record"],
  "primary_stratum": "catalyst"
}
```

Preferred disease-mode primary stratum priority:

1. `evidence`
2. `foundation`
3. `frontier`

This keeps the report concise while preserving why a trial was selected.

## LLM Role

LLM can participate, but only after deterministic source data is fetched, normalized, and tagged.

Allowed LLM tasks:

- Generate concise Chinese or English narrative from supplied JSON.
- Summarize distribution patterns, such as phase/status/results counts.
- Optionally label intervention/MOA themes from trial titles and intervention names, if every label is marked as derived and source-linked.
- Optionally suggest query synonyms before search, but not replace ClinicalTrials.gov filters.

Disallowed LLM tasks:

- Changing phase, status, dates, results flags, sponsors, NCT IDs, enrollment, or outcome values.
- Creating missing trials, endpoints, results, safety findings, or efficacy claims.
- Deciding that a trial has results unless ClinicalTrials.gov says `hasResults=true`.

## Hallucination Controls

The source-of-truth path should remain deterministic:

1. ClinicalTrials.gov API response is fetched.
2. Fields are normalized into typed records.
3. Filters and strata are assigned by code.
4. Report tables render normalized fields directly.
5. LLM receives a compact JSON payload and writes narrative only.
6. Prompt rules continue to require: use only supplied JSON, do not infer missing facts, and return strict JSON.

Company mode adds one more hard rule: the LLM may summarize company strata, condition distribution, and sponsor facts supplied by JSON, but it must not infer stock impact, success probability, or future readout timing beyond deterministic ClinicalTrials.gov dates.

If LLM-derived labels are added later, keep them in separate fields such as `llm_theme_label` or `llm_summary`, never overwrite source fields.

## Expected Runtime Impact

The deterministic stratified ClinicalTrials fetch adds modest network cost, not major LLM cost:

- Three list queries per condition term instead of one.
- Target total can increase from roughly 50 to 60-100 records.
- Evidence layer may add detail fetches for 10-20 result-bearing trials.
- LLM time should not increase much if narratives receive aggregated summaries and a capped table payload.

The main latency risk is ClinicalTrials.gov network calls, not Gemini. Keep page sizes bounded, cap evidence detail fetches, and deduplicate before expensive detail requests.

## Acceptance Criteria

- `/investigation` uses the new global Gemini configuration.
- `/investigation` lets the user choose disease-oriented or company-oriented ClinicalTrials search before launch.
- `/api/analyze` accepts and validates `analysis_target_type` from JSON and FormData requests.
- Legacy requests without `analysis_target_type` still run via conservative `auto` mode and default to disease.
- ClinicalTrials records carry phase/status/results fields through harvest, package, IR, and rendered report.
- Disease-mode output visibly separates or labels Foundation, Frontier, and Evidence strata when disease stratification is enabled.
- Company-mode output visibly separates or labels Catalyst Tracker, Expansion Map, and Track Record strata.
- Company-mode API calls use `query.spons` plus the three layer-specific parameter sets above.
- Deduplication preserves all stratum memberships.
- LLM narrative cannot mutate source facts.
- Existing deterministic tests cover target-mode resolution, UI payload propagation, filtering, deduplication, field propagation, company-layer API parameters, and report rendering.
