# Disease Survey Handoff Intelligence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:test-driven-development` before changing production code. Use `superpowers:subagent-driven-development` if executing this plan with parallel workers, or `superpowers:executing-plans` if executing inline. Mark each checkbox as it is completed.

**Goal:** Move disease-survey intelligence out of the final writer and into a structured post-harvest handoff slot, then render the final disease report from that slot without the writer generating data.

**Architecture:** Add `disease_survey_intelligence_node` between `harvester` and `extension_handoff`. The node builds `extension_payloads["slot_disease_survey"]` from harvested rows, including cleaned pipeline assets, company technical routes, top-50 literature, evidence-backed pipeline risks, chart payloads, and evidence registry. The writer consumes this slot first and keeps legacy writer-side aggregation only as fallback.

**Tech Stack:** Python, LangGraph `StateGraph`, Pydantic models, pytest, existing `DocumentComposer`/HTML/PDF rendering pipeline.

---

## Current Evidence

- `src/graph/workflow.py` currently routes `START -> harvester -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer -> END`.
- `src/graph/nodes/writer_node.py` already passes `extension_payloads` as `synthesis_sections`.
- `src/agents/report_writer.py::ReportWriterAgent.write_report()` currently accepts `**extra_payload` then immediately deletes it, so slots are not consumed by the agent.
- `ReportWriterAgent._is_disease_survey(rows)` routes only by row identifier density, so company/ticker reports can be misrouted when enough rows contain PMID/NCT IDs.
- `src/engines/report_engine/disease_survey/aggregator.py` preserves many core fields but does not carry ClinicalTrials timing fields into `TrialRecord`.
- Current disease report chapters still include `Sponsor Analysis`, `Target Biology`, `Safety Profile`, and `Market Landscape`.

---

## Target Report Chapters

The primary disease report must contain:

1. Executive Summary
2. Drug Pipeline
3. Trial Landscape
4. Company Technical Route Analysis
5. Literature Review
6. CNS Benchmark
7. Pipeline Timeline And Competition Risk

The primary disease report must not contain independent chapters:

- Sponsor Analysis
- Target Biology
- Safety Profile

`Market Landscape` is replaced by evidence-backed per-pipeline timeline and competition risk, not financial placeholders.

---

## Files To Add

```text
src/graph/nodes/disease_survey_intelligence_node.py
src/engines/report_engine/disease_survey/intelligence.py
src/engines/report_engine/disease_survey/journal_scope.py
src/engines/report_engine/disease_survey/pipeline_risk.py
src/tools/company_approach_client.py
tests/test_disease_survey_intelligence_node.py
tests/test_disease_survey_intelligence_slot.py
tests/test_literature_top50_scope.py
tests/test_pipeline_risk.py
```

## Files To Modify

```text
src/graph/workflow.py
src/graph/state.py
src/graph/nodes/__init__.py
src/graph/nodes/extension_handoff_node.py
src/graph/nodes/writer_node.py
src/agents/report_writer.py
src/engines/report_engine/disease_survey/__init__.py
src/engines/report_engine/disease_survey/models.py
src/engines/report_engine/disease_survey/aggregator.py
src/engines/report_engine/disease_survey/renderer.py
src/engines/report_engine/disease_survey/composer.py
tests/test_disease_survey_aggregator.py
tests/test_disease_survey_composer.py
tests/test_disease_survey_e2e.py
tests/test_disease_survey_models.py
tests/test_disease_survey_renderer.py
tests/test_writer_slot_consumption.py
docs/competition/architecture/DATA_FLOW_ARCHITECTURE.md
```

---

## Phase 0: Baseline And Guardrails

- [ ] Run targeted baseline tests before editing:

```powershell
python -m pytest tests/test_disease_survey_models.py tests/test_disease_survey_aggregator.py tests/test_disease_survey_renderer.py tests/test_disease_survey_composer.py tests/test_writer_slot_consumption.py
```

- [ ] Capture any pre-existing failures in the work log. Do not fix unrelated failures.
- [ ] Confirm no implementation starts until the first failing test for that task exists.

---

## Phase 1: Extend Disease Survey Data Contracts

### Task 1.1: Add model fields for evidence, therapeutic flag, and trial timing

- [ ] Add failing tests in `tests/test_disease_survey_models.py`.

Test intent:

```python
from src.engines.report_engine.disease_survey.models import (
    CompanyTechnicalRoute,
    DrugAsset,
    PipelineRiskRecord,
    TrialRecord,
)


def test_drug_asset_carries_therapeutic_flag_and_evidence():
    asset = DrugAsset(
        asset_name="Lecanemab",
        sponsor="Eisai",
        company="Eisai / Biogen",
        phase="Phase 3",
        is_therapeutic=True,
        asset_note="",
        evidence_ids=["ev_ctgov_NCT03887455"],
    )

    assert asset.company == "Eisai / Biogen"
    assert asset.is_therapeutic is True
    assert asset.evidence_ids == ["ev_ctgov_NCT03887455"]


def test_non_therapeutic_asset_can_be_marked_without_subtaxonomy():
    asset = DrugAsset(
        asset_name="Questionnaire",
        sponsor="Academic Medical Center",
        is_therapeutic=False,
        asset_note="非药物/非治疗性",
    )

    assert asset.is_therapeutic is False
    assert asset.asset_note == "非药物/非治疗性"


def test_trial_record_carries_timing_fields():
    trial = TrialRecord(
        nct_id="NCT00000001",
        title="A trial",
        start_date="2020-01-01",
        primary_completion_date="2024-01-01",
        completion_date="2024-06-01",
        results_first_posted="2025-01-15",
        evidence_ids=["ev_ctgov_NCT00000001"],
    )

    assert trial.start_date == "2020-01-01"
    assert trial.primary_completion_date == "2024-01-01"
    assert trial.completion_date == "2024-06-01"
    assert trial.results_first_posted == "2025-01-15"
    assert trial.evidence_ids == ["ev_ctgov_NCT00000001"]


def test_company_route_and_pipeline_risk_contracts():
    route = CompanyTechnicalRoute(
        company_name="Eisai",
        representative_assets=["Lecanemab"],
        technical_route="anti-Aβ monoclonal antibody",
        targets=["Aβ"],
        modality="Monoclonal Antibody",
        route_summary="Targets amyloid pathology.",
        why_it_fits_disease="Matches the amyloid-pathology hypothesis.",
        evidence_ids=["ev_company_eisai_pipeline"],
    )
    risk = PipelineRiskRecord(
        asset_name="Lecanemab",
        company="Eisai / Biogen",
        phase="Phase 3",
        status="Completed",
        timeline_risk="中",
        timeline_evidence="Primary completion and results fields are populated.",
        competition_risk="高",
        competition_evidence="Same target/modality assets are present.",
        evidence_ids=["ev_ctgov_NCT03887455"],
    )

    assert route.company_name == "Eisai"
    assert risk.timeline_risk in {"低", "中", "高", "数据不足"}
    assert risk.competition_risk in {"低", "中", "高", "数据不足"}
```

- [ ] Update `src/engines/report_engine/disease_survey/models.py`.

Implementation shape:

```python
class DrugAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_name: str = Field(..., min_length=1)
    aliases: List[str] = Field(default_factory=list)
    modality: str = ""
    targets: List[str] = Field(default_factory=list)
    sponsor: str = ""
    company: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    trial_ids: List[str] = Field(default_factory=list)
    indication_subtype: Optional[str] = None
    is_therapeutic: bool = True
    asset_note: str = ""
    evidence_ids: List[str] = Field(default_factory=list)


class TrialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nct_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)
    asset_name: Optional[str] = None
    sponsor: Optional[str] = None
    phase: Optional[str] = None
    status: Optional[str] = None
    enrollment: Optional[str] = None
    start_date: Optional[str] = None
    primary_completion_date: Optional[str] = None
    completion_date: Optional[str] = None
    results_first_posted: Optional[str] = None
    primary_endpoint: Optional[str] = None
    secondary_endpoint: Optional[str] = None
    ae_grade3plus: Optional[str] = None
    sae: Optional[str] = None
    evidence_ids: List[str] = Field(default_factory=list)


class CompanyTechnicalRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")

    company_name: str = Field(..., min_length=1)
    representative_assets: List[str] = Field(default_factory=list)
    technical_route: str = "数据不足"
    targets: List[str] = Field(default_factory=list)
    modality: str = "数据不足"
    route_summary: str = "数据不足"
    why_it_fits_disease: str = "数据不足"
    evidence_ids: List[str] = Field(default_factory=list)


class PipelineRiskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_name: str = Field(..., min_length=1)
    company: str = ""
    phase: Optional[str] = None
    status: Optional[str] = None
    timeline_risk: str = "数据不足"
    timeline_evidence: str = ""
    competition_risk: str = "数据不足"
    competition_evidence: str = ""
    competition_buckets: List[str] = Field(default_factory=list)
    evidence_ids: List[str] = Field(default_factory=list)
```

- [ ] Export new models from `src/engines/report_engine/disease_survey/__init__.py`.
- [ ] Run:

```powershell
python -m pytest tests/test_disease_survey_models.py
```

### Task 1.2: Add optional graph state fields for the disease slot

- [ ] Update `src/graph/state.py`.

Implementation shape:

```python
    disease_survey_slot: Optional[Dict[str, Any]]  # Last-write-wins
```

- [ ] No separate test is required beyond node tests in Phase 5.
- [ ] Commit after Phase 1 passes:

```powershell
git add src/engines/report_engine/disease_survey/models.py src/engines/report_engine/disease_survey/__init__.py src/graph/state.py tests/test_disease_survey_models.py
git commit -m "feat: extend disease survey data contracts"
```

---

## Phase 2: Preserve Harvested Timing, Evidence, And Non-Therapeutic Rows

### Task 2.1: Add aggregator tests for timing fields and non-therapeutic marking

- [ ] Add failing tests to `tests/test_disease_survey_aggregator.py`.

Test intent:

```python
def test_aggregate_survey_data_preserves_trial_timing_fields():
    row = {
        "source": "ClinicalTrials.gov",
        "title": "Lecanemab trial",
        "nct_id": "NCT03887455",
        "metadata": {
            "interventions": ["Lecanemab"],
            "sponsor": "Eisai Inc.",
            "phase": "Phase 3",
            "overall_status": "Completed",
            "enrollment": "1795",
            "start_date": "2019-03-01",
            "primary_completion_date": "2022-03-01",
            "completion_date": "2024-01-01",
            "results_first_posted": "2024-06-01",
            "primary_outcome_measures": "Change in CDR-SB",
        },
    }

    state = aggregate_survey_data([row], "Alzheimer disease survey")
    trial = state.trials[0]

    assert trial.start_date == "2019-03-01"
    assert trial.primary_completion_date == "2022-03-01"
    assert trial.completion_date == "2024-01-01"
    assert trial.results_first_posted == "2024-06-01"
    assert trial.primary_endpoint == "Change in CDR-SB"
    assert trial.evidence_ids == ["ev_ctgov_NCT03887455"]


def test_aggregate_survey_data_marks_non_therapeutic_without_removing_row():
    row = {
        "source": "ClinicalTrials.gov",
        "title": "Caregiver questionnaire study",
        "nct_id": "NCT11111111",
        "metadata": {
            "interventions": ["Questionnaire"],
            "sponsor": "University Hospital",
            "phase": "Not Applicable",
            "overall_status": "Recruiting",
        },
    }

    state = aggregate_survey_data([row], "Alzheimer disease survey")

    assert len(state.drug_assets) == 1
    assert state.drug_assets[0].asset_name == "Questionnaire"
    assert state.drug_assets[0].is_therapeutic is False
    assert state.drug_assets[0].asset_note == "非药物/非治疗性"
```

- [ ] Update `src/engines/report_engine/disease_survey/aggregator.py`.

Implementation notes:

- Add `_evidence_id_for_trial(nct_id: str) -> str`.
- Add `_evidence_id_for_pubmed(pmid: str) -> str`.
- Add `_is_non_therapeutic_intervention(text: str, phase: str) -> bool`.
- Use `primary_outcome_measures` as fallback for `primary_endpoint`.
- Populate `DrugAsset.company` from sponsor for now; richer company grouping happens in `intelligence.py`.
- Keep non-therapeutic interventions in `drug_assets`.

Implementation shape:

```python
_NON_THERAPEUTIC_TERMS = (
    "questionnaire",
    "survey",
    "observational",
    "registry",
    "screening",
    "diagnostic",
    "education",
    "caregiver",
)


def _evidence_id_for_trial(nct_id: str) -> str:
    return f"ev_ctgov_{nct_id}"


def _is_non_therapeutic_intervention(intervention: str, phase: str = "") -> bool:
    text = f"{intervention} {phase}".lower()
    return "not applicable" in text or any(term in text for term in _NON_THERAPEUTIC_TERMS)
```

- [ ] Verify:

```powershell
python -m pytest tests/test_disease_survey_aggregator.py tests/test_disease_survey_models.py
```

### Task 2.2: Add evidence registry to legacy state metadata

- [ ] Extend `aggregate_survey_data()` metadata:

```python
metadata={
    "field_audit": {
        "missing_asset_count": missing_asset_count,
        "missing_sponsor_count": missing_sponsor_count,
        "total_trials": len(trials),
        "total_assets": len(drug_assets),
        "total_sponsors": len(sponsors),
    },
    "evidence_registry": evidence_registry,
}
```

Registry entry shape:

```python
{
    "evidence_id": "ev_ctgov_NCT03887455",
    "source_type": "ClinicalTrials.gov",
    "source_url": "https://clinicaltrials.gov/study/NCT03887455",
    "title": "Lecanemab trial",
    "fields_used": [
        "phase",
        "status",
        "start_date",
        "primary_completion_date",
        "completion_date",
        "results_first_posted",
        "sponsor",
        "interventions",
    ],
}
```

- [ ] Add assertion to `tests/test_disease_survey_aggregator.py` that registry is present.
- [ ] Commit after Phase 2 passes:

```powershell
git add src/engines/report_engine/disease_survey/aggregator.py tests/test_disease_survey_aggregator.py
git commit -m "feat: preserve disease survey harvest fields"
```

---

## Phase 3: Top-50 Literature Scope

### Task 3.1: Add journal scope helper

- [ ] Add `tests/test_literature_top50_scope.py`.

Test intent:

```python
from src.engines.report_engine.disease_survey.journal_scope import (
    filter_top50_literature,
    is_top50_journal,
    normalize_journal_name,
)


def test_normalize_journal_name_handles_punctuation_and_case():
    assert normalize_journal_name("The Lancet Neurology.") == "the lancet neurology"
    assert normalize_journal_name("N. Engl. J. Med.") == "new england journal of medicine"


def test_is_top50_journal_accepts_known_scope():
    assert is_top50_journal("The Lancet Neurology") is True
    assert is_top50_journal("New England Journal of Medicine") is True
    assert is_top50_journal("Local Neurology Case Reports") is False


def test_filter_top50_literature_excludes_lower_scope_records():
    records = [
        {"pmid": "1", "title": "A", "journal": "The Lancet Neurology"},
        {"pmid": "2", "title": "B", "journal": "Local Neurology Case Reports"},
    ]

    scoped, filtered_count = filter_top50_literature(records)

    assert [record["pmid"] for record in scoped] == ["1"]
    assert filtered_count == 1
```

- [ ] Add `src/engines/report_engine/disease_survey/journal_scope.py`.

Implementation shape:

```python
TOP_50_JOURNALS = {
    "new england journal of medicine",
    "the lancet",
    "the lancet neurology",
    "nature",
    "science",
    "cell",
    "nature medicine",
    "nature neuroscience",
    "jama",
    "jama neurology",
    "bmj",
    "brain",
    "annals of neurology",
    "neuron",
    "acta neuropathologica",
    "molecular neurodegeneration",
    "alzheimer's & dementia",
    "alzheimers & dementia",
    "alzheimer's research & therapy",
    "nature reviews neuroscience",
    "nature reviews neurology",
    "nature aging",
    "science translational medicine",
    "clinical trials",
    "clinical pharmacology and therapeutics",
    "neurology",
    "movement disorders",
    "journal of neurology neurosurgery and psychiatry",
    "european journal of neurology",
    "npj parkinson's disease",
    "npj aging",
    "translational neurodegeneration",
    "neurobiology of aging",
    "journal of alzheimer's disease",
    "journal of clinical investigation",
    "proceedings of the national academy of sciences",
    "plos medicine",
    "elife",
    "cell reports medicine",
    "med",
    "lancet healthy longevity",
    "lancet psychiatry",
    "jama internal medicine",
    "jama network open",
    "annals of internal medicine",
    "circulation",
    "blood",
    "immunity",
    "nature immunology",
    "nature genetics",
    "nature communications",
    "communications medicine",
    "bmc medicine",
    "frontiers in aging neuroscience",
    "aging cell",
    "geroscience",
}

_ALIASES = {
    "n engl j med": "new england journal of medicine",
    "n. engl. j. med.": "new england journal of medicine",
    "nejm": "new england journal of medicine",
    "lancet": "the lancet",
    "lancet neurol": "the lancet neurology",
    "lancet neurology": "the lancet neurology",
    "alzheimers dementia": "alzheimer's & dementia",
}


def normalize_journal_name(value: str | None) -> str:
    import re

    text = re.sub(r"\s+", " ", str(value or "").strip().lower())
    text = text.rstrip(".")
    text = text.replace("&amp;", "&")
    no_punct = re.sub(r"[^\w\s&'-]", "", text)
    return _ALIASES.get(text) or _ALIASES.get(no_punct) or no_punct


def is_top50_journal(value: str | None) -> bool:
    return normalize_journal_name(value) in TOP_50_JOURNALS


def filter_top50_literature(records: list[dict]) -> tuple[list[dict], int]:
    scoped: list[dict] = []
    filtered_out = 0
    for record in records:
        if is_top50_journal(record.get("journal")):
            scoped.append(record)
        else:
            filtered_out += 1
    return scoped, filtered_out
```

Important: keep the curated set at 50 or more canonical journal names. If any name is removed, replace it in the same change.

### Task 3.2: Enforce top-50 scope in the intelligence slot

- [ ] In Phase 6, `build_disease_survey_slot()` must call `filter_top50_literature()` and store:

```python
"literature_review": {
    "journal_scope": "top_50_only",
    "year_scope": "last_5_years",
    "search_queries_used": [
        f"{survey_state.disease_name} clinical trial top journal",
        f"{survey_state.disease_name} target mechanism top journal",
        f"{survey_state.disease_name} therapeutic pipeline top journal",
    ],
    "records": scoped_records,
    "filtered_out_count": filtered_out_count,
}
```

- [ ] Commit after Phase 3 helper tests pass:

```powershell
git add src/engines/report_engine/disease_survey/journal_scope.py tests/test_literature_top50_scope.py
git commit -m "feat: add top fifty journal scope"
```

---

## Phase 4: Pipeline Timeline And Competition Risk

### Task 4.1: Add deterministic pipeline risk builder

- [ ] Add `tests/test_pipeline_risk.py`.

Test intent:

```python
from src.engines.report_engine.disease_survey.pipeline_risk import (
    build_pipeline_timeline_competition_risks,
)


def test_missing_timing_fields_yields_data_insufficient_timeline_risk():
    assets = [
        {
            "asset_name": "Drug A",
            "company": "Company A",
            "phase": "Phase 2",
            "status": "Recruiting",
            "targets": ["Tau"],
            "modality": "Small Molecule",
            "is_therapeutic": True,
            "trial_ids": ["NCT1"],
            "evidence_ids": ["ev_ctgov_NCT1"],
        }
    ]
    trials = [{"nct_id": "NCT1", "asset_name": "Drug A"}]

    risks = build_pipeline_timeline_competition_risks(assets, trials, [])

    assert risks[0]["timeline_risk"] == "数据不足"
    assert "Missing" in risks[0]["timeline_evidence"]


def test_same_target_and_modality_competitors_raise_competition_risk():
    assets = [
        {
            "asset_name": "Drug A",
            "company": "Company A",
            "phase": "Phase 2",
            "status": "Recruiting",
            "targets": ["Aβ"],
            "modality": "Monoclonal Antibody",
            "is_therapeutic": True,
            "trial_ids": ["NCT1"],
            "evidence_ids": ["ev_ctgov_NCT1"],
        },
        {
            "asset_name": "Drug B",
            "company": "Company B",
            "phase": "Phase 3",
            "status": "Completed",
            "targets": ["Aβ"],
            "modality": "Monoclonal Antibody",
            "is_therapeutic": True,
            "trial_ids": ["NCT2"],
            "evidence_ids": ["ev_ctgov_NCT2"],
        },
    ]
    trials = [
        {
            "nct_id": "NCT1",
            "asset_name": "Drug A",
            "start_date": "2023-01-01",
            "primary_completion_date": "2025-01-01",
        },
        {
            "nct_id": "NCT2",
            "asset_name": "Drug B",
            "start_date": "2020-01-01",
            "primary_completion_date": "2023-01-01",
        },
    ]

    risks = build_pipeline_timeline_competition_risks(assets, trials, [])

    drug_a = next(row for row in risks if row["asset_name"] == "Drug A")
    assert drug_a["competition_risk"] == "高"
    assert "same_target" in drug_a["competition_buckets"]
    assert "same_modality" in drug_a["competition_buckets"]
```

- [ ] Add `src/engines/report_engine/disease_survey/pipeline_risk.py`.

Implementation rules:

- Only therapeutic assets enter the output.
- Labels are exactly `低`, `中`, `高`, `数据不足`.
- Missing timing evidence returns `timeline_risk = "数据不足"`.
- Missing target or modality returns `competition_risk = "数据不足"`.
- Competition buckets can include `same_disease`, `same_target`, `same_modality`, `same_phase`, `same_milestone_window`.
- No market shares or success probabilities.

Implementation shape:

```python
RISK_LABELS = {"低", "中", "高", "数据不足"}


def build_pipeline_timeline_competition_risks(
    pipeline_assets: list[dict],
    trials: list[dict],
    literature_records: list[dict],
) -> list[dict]:
    therapeutic_assets = [asset for asset in pipeline_assets if asset.get("is_therapeutic") is True]
    trial_by_id = {trial.get("nct_id"): trial for trial in trials if trial.get("nct_id")}
    risks: list[dict] = []

    for asset in therapeutic_assets:
        matching_trials = [
            trial_by_id[trial_id]
            for trial_id in asset.get("trial_ids", [])
            if trial_id in trial_by_id
        ]
        timeline_risk, timeline_evidence = _score_timeline(asset, matching_trials)
        competition_risk, competition_evidence, buckets = _score_competition(asset, therapeutic_assets)
        risks.append(
            {
                "asset_name": asset.get("asset_name") or "",
                "company": asset.get("company") or asset.get("sponsor") or "",
                "phase": asset.get("phase"),
                "status": asset.get("status"),
                "timeline_risk": timeline_risk,
                "timeline_evidence": timeline_evidence,
                "competition_risk": competition_risk,
                "competition_evidence": competition_evidence,
                "competition_buckets": buckets,
                "evidence_ids": asset.get("evidence_ids", []),
            }
        )

    return risks
```

- [ ] Verify:

```powershell
python -m pytest tests/test_pipeline_risk.py
```

- [ ] Commit after Phase 4 passes:

```powershell
git add src/engines/report_engine/disease_survey/pipeline_risk.py tests/test_pipeline_risk.py
git commit -m "feat: add evidence backed pipeline risk scoring"
```

---

## Phase 5: Company Technical Route Extraction

### Task 5.1: Add deterministic company route client with injectable fetcher

- [ ] Add focused tests in `tests/test_disease_survey_intelligence_slot.py`.

Test intent:

```python
from src.tools.company_approach_client import CompanyApproachClient


def test_company_approach_client_extracts_route_from_pipeline_text():
    client = CompanyApproachClient(fetch_text=lambda url: "Eisai pipeline: lecanemab is an anti-amyloid beta monoclonal antibody for Alzheimer's disease.")

    result = client.fetch_company_route("Eisai", ["Lecanemab"], ["Aβ"], "Monoclonal Antibody")

    assert result["company_name"] == "Eisai"
    assert result["technical_route"] != "数据不足"
    assert result["evidence_ids"]


def test_company_route_degrades_to_data_insufficient_on_fetch_failure():
    client = CompanyApproachClient(fetch_text=lambda url: "")

    result = client.fetch_company_route("Unknown Biotech", ["Drug X"], ["Tau"], "Small Molecule")

    assert result["technical_route"] == "数据不足"
    assert result["route_summary"] == "数据不足"
```

- [ ] Add `src/tools/company_approach_client.py`.

Implementation rules:

- Use deterministic parsing of fetched text.
- Accept an injectable `fetch_text` callable for tests.
- Do not use LLM output to create technical routes.
- If no official/company text is available, return `数据不足`.
- Use the asset's own targets/modality as structured fallback only when there is evidence from trials; do not invent disease fit.

Implementation shape:

```python
KNOWN_COMPANY_PIPELINE_URLS = {
    "eisai": "https://www.eisai.com/innovation/research/pipeline/index.html",
    "biogen": "https://www.biogen.com/science-and-innovation/pipeline.html",
    "eli-lilly": "https://www.lilly.com/discovery/clinical-development-pipeline",
    "lilly": "https://www.lilly.com/discovery/clinical-development-pipeline",
    "roche": "https://www.roche.com/solutions/pipeline",
    "novartis": "https://www.novartis.com/research-development/novartis-pipeline",
}


class CompanyApproachClient:
    def __init__(
        self,
        fetch_text: Callable[[str], str] | None = None,
        company_urls: dict[str, str] | None = None,
    ):
        self._fetch_text = fetch_text or self._default_fetch_text
        self._company_urls = company_urls or KNOWN_COMPANY_PIPELINE_URLS

    def fetch_company_route(
        self,
        company_name: str,
        representative_assets: list[str],
        targets: list[str],
        modality: str,
    ) -> dict:
        url = self._build_pipeline_url(company_name)
        evidence_id = f"ev_company_{_slug(company_name)}_pipeline"
        if not url:
            return {
                "company_name": company_name,
                "representative_assets": representative_assets,
                "technical_route": "数据不足",
                "targets": targets,
                "modality": modality or "数据不足",
                "route_summary": "数据不足",
                "why_it_fits_disease": "数据不足",
                "evidence_ids": [],
            }
        text = self._fetch_text(url)
        if not text:
            return {
                "company_name": company_name,
                "representative_assets": representative_assets,
                "technical_route": "数据不足",
                "targets": targets,
                "modality": modality or "数据不足",
                "route_summary": "数据不足",
                "why_it_fits_disease": "数据不足",
                "evidence_ids": [],
            }

        route_terms = self._extract_route_terms(text, targets, modality)
        route_summary = self._summarize_route(company_name, representative_assets, route_terms, text)
        return {
            "company_name": company_name,
            "representative_assets": representative_assets,
            "technical_route": route_terms or "数据不足",
            "targets": targets,
            "modality": modality or "数据不足",
            "route_summary": route_summary or "数据不足",
            "why_it_fits_disease": (
                f"Structured company/pipeline text links {', '.join(representative_assets)} "
                f"to {route_terms}."
                if route_terms and representative_assets
                else "数据不足"
            ),
            "evidence_ids": [evidence_id] if route_terms else [],
        }

    def _build_pipeline_url(self, company_name: str) -> str:
        return self._company_urls.get(_slug(company_name), "")

    def _default_fetch_text(self, url: str) -> str:
        try:
            import requests

            response = requests.get(url, timeout=8)
            if response.status_code >= 400:
                return ""
            return response.text[:50000]
        except Exception:
            return ""

    def _extract_route_terms(self, text: str, targets: list[str], modality: str) -> str:
        lower = text.lower()
        target_hit = next((target for target in targets if target and target.lower().replace("β", "beta") in lower), "")
        modality_hit = modality if modality and modality.lower() in lower else ""
        if target_hit and modality_hit:
            return f"{target_hit} {modality_hit}"
        if target_hit:
            return target_hit
        if modality_hit:
            return modality_hit
        return ""

    def _summarize_route(self, company_name: str, assets: list[str], route_terms: str, text: str) -> str:
        if not route_terms:
            return ""
        asset_text = ", ".join(assets) if assets else "its representative assets"
        return f"{company_name} positions {asset_text} around {route_terms}."
```

### Task 5.2: Filter company route candidates

- [ ] Add helper in `intelligence.py` later:

```python
_NON_COMPANY_SPONSOR_TERMS = (
    "university",
    "hospital",
    "institute",
    "foundation",
    "nih",
    "national institutes",
    "individual",
)


def is_pharma_or_biotech_sponsor(name: str) -> bool:
    text = (name or "").strip().lower()
    if not text:
        return False
    if any(term in text for term in _NON_COMPANY_SPONSOR_TERMS):
        return False
    company_markers = (
        "inc",
        "corp",
        "corporation",
        "company",
        "co.",
        "ltd",
        "limited",
        "pharma",
        "biotech",
        "therapeutics",
        "biosciences",
        "biogen",
        "eisai",
        "lilly",
        "roche",
        "novartis",
        "abbvie",
        "takeda",
    )
    return any(marker in text for marker in company_markers)
```

- [ ] Tests should assert universities/hospitals and non-therapeutic-only sponsors are excluded from `company_technical_routes`.
- [ ] Commit after company route helper tests pass:

```powershell
git add src/tools/company_approach_client.py tests/test_disease_survey_intelligence_slot.py
git commit -m "feat: add company technical route client"
```

---

## Phase 6: Build `slot_disease_survey`

### Task 6.1: Add slot builder tests

- [ ] Add `tests/test_disease_survey_intelligence_slot.py` tests for full slot shape.

Test intent:

```python
from src.engines.report_engine.disease_survey.intelligence import (
    build_disease_survey_slot,
    validate_disease_survey_slot,
)


def test_build_disease_survey_slot_includes_required_top_level_keys():
    rows = [
        {
            "source": "ClinicalTrials.gov",
            "title": "Lecanemab trial",
            "nct_id": "NCT03887455",
            "metadata": {
                "interventions": ["Lecanemab"],
                "sponsor": "Eisai Inc.",
                "phase": "Phase 3",
                "overall_status": "Completed",
                "start_date": "2019-03-01",
                "primary_completion_date": "2022-03-01",
            },
        },
        {
            "source": "PubMed",
            "title": "Anti amyloid therapy review",
            "pmid": "123",
            "journal": "The Lancet Neurology",
            "year": 2024,
            "metadata": {"pmid": "123"},
        },
    ]

    slot = build_disease_survey_slot(rows, "conduct a comprehensive survey on Alzheimer disease")

    assert validate_disease_survey_slot(slot) == []
    assert slot["intent"]["report_type"] == "disease_survey"
    assert slot["entity_profile"]["entity_type"] == "disease"
    assert "pipeline_assets" in slot
    assert "company_technical_routes" in slot
    assert "literature_review" in slot
    assert "pipeline_timeline_competition_risks" in slot
    assert "charts" in slot
    assert "evidence_registry" in slot


def test_slot_keeps_non_therapeutic_assets_but_excludes_them_from_risk():
    rows = [
        {
            "source": "ClinicalTrials.gov",
            "title": "Questionnaire study",
            "nct_id": "NCT11111111",
            "metadata": {
                "interventions": ["Questionnaire"],
                "sponsor": "University Hospital",
                "phase": "Not Applicable",
            },
        }
    ]

    slot = build_disease_survey_slot(rows, "Alzheimer disease survey")

    assert slot["pipeline_assets"][0]["asset_note"] == "非药物/非治疗性"
    assert slot["pipeline_timeline_competition_risks"] == []
    assert slot["company_technical_routes"] == []


def test_slot_literature_review_is_top50_only():
    rows = [
        {"source": "PubMed", "pmid": "1", "title": "A", "journal": "The Lancet Neurology", "year": 2024, "metadata": {"pmid": "1"}},
        {"source": "PubMed", "pmid": "2", "title": "B", "journal": "Local Neurology Case Reports", "year": 2024, "metadata": {"pmid": "2"}},
    ]

    slot = build_disease_survey_slot(rows, "Alzheimer disease survey")

    assert slot["literature_review"]["journal_scope"] == "top_50_only"
    assert [record["pmid"] for record in slot["literature_review"]["records"]] == ["1"]
    assert slot["literature_review"]["filtered_out_count"] == 1
```

### Task 6.2: Implement intelligence slot builder

- [ ] Add `src/engines/report_engine/disease_survey/intelligence.py`.

Implementation responsibilities:

- Call `aggregate_survey_data(rows, query)` once in the post-harvest node path.
- Convert `DiseaseSurveyState` to plain dict records.
- Preserve `metadata["field_audit"]` and `metadata["evidence_registry"]`.
- Build `intent` and `entity_profile`.
- Build `pipeline_assets`, sorted therapeutic first.
- Build `company_technical_routes` for pharma/biotech therapeutic sponsors only.
- Build `literature_review` using `filter_top50_literature`.
- Build `pipeline_timeline_competition_risks` using `build_pipeline_timeline_competition_risks`.
- Build chart payloads from actual slot data only.
- Validate writer-ready slot shape.

Implementation shape:

```python
def build_disease_survey_slot(
    rows: list[dict],
    query: str,
    *,
    source_payloads: dict | None = None,
    company_client: CompanyApproachClient | None = None,
) -> dict:
    survey_state = aggregate_survey_data(rows, query)
    pipeline_assets = _state_assets_to_slot(survey_state)
    trials = _state_trials_to_slot(survey_state)
    literature_records = _state_literature_to_slot(survey_state)
    scoped_literature, filtered_out_count = filter_top50_literature(literature_records)
    company_routes = _build_company_routes(pipeline_assets, company_client or CompanyApproachClient())
    risks = build_pipeline_timeline_competition_risks(pipeline_assets, trials, scoped_literature)

    slot = {
        "intent": _build_intent(query, survey_state),
        "entity_profile": _build_entity_profile(query, survey_state),
        "field_audit": survey_state.metadata.get("field_audit", {}),
        "pipeline_assets": pipeline_assets,
        "trial_landscape": trials,
        "company_technical_routes": company_routes,
        "literature_review": {
            "journal_scope": "top_50_only",
            "year_scope": "last_5_years",
            "search_queries_used": _build_literature_queries(survey_state.disease_name),
            "records": scoped_literature,
            "filtered_out_count": filtered_out_count,
        },
        "pipeline_timeline_competition_risks": risks,
        "charts": _build_slot_charts(pipeline_assets, trials, scoped_literature, company_routes, risks),
        "evidence_registry": survey_state.metadata.get("evidence_registry", []),
    }
    errors = validate_disease_survey_slot(slot)
    if errors:
        slot["field_audit"] = {**slot.get("field_audit", {}), "slot_validation_errors": errors}
    return slot
```

- [ ] Add `validate_disease_survey_slot(slot: dict) -> list[str]`.
- [ ] Export helpers from `src/engines/report_engine/disease_survey/__init__.py`.
- [ ] Verify:

```powershell
python -m pytest tests/test_disease_survey_intelligence_slot.py tests/test_literature_top50_scope.py tests/test_pipeline_risk.py
```

- [ ] Commit after Phase 6 passes:

```powershell
git add src/engines/report_engine/disease_survey/intelligence.py src/engines/report_engine/disease_survey/__init__.py tests/test_disease_survey_intelligence_slot.py
git commit -m "feat: build disease survey handoff slot"
```

---

## Phase 7: Add Disease Survey Intelligence Node And Wire Workflow

### Task 7.1: Add node tests

- [ ] Add `tests/test_disease_survey_intelligence_node.py`.

Test intent:

```python
from src.graph.nodes.disease_survey_intelligence_node import disease_survey_intelligence_node


def test_disease_survey_intelligence_node_adds_slot_without_dropping_existing_slots():
    state = {
        "user_query": "conduct a comprehensive survey on Alzheimer disease",
        "harvested_data": [
            {
                "source": "ClinicalTrials.gov",
                "title": "Lecanemab trial",
                "nct_id": "NCT03887455",
                "metadata": {"interventions": ["Lecanemab"], "sponsor": "Eisai", "phase": "Phase 3"},
            }
        ],
        "extension_payloads": {"slot_a": {"existing": True}},
        "harvest_source_payloads": {},
    }

    result = disease_survey_intelligence_node(state)

    assert result["status"] == "disease_survey_intelligence_complete"
    assert result["extension_payloads"]["slot_a"] == {"existing": True}
    assert "slot_disease_survey" in result["extension_payloads"]
    assert result["disease_survey_slot"] == result["extension_payloads"]["slot_disease_survey"]


def test_disease_survey_intelligence_node_noops_for_non_disease_query():
    state = {
        "user_query": "Generate a new investigation for BIIB",
        "harvested_data": [{"source": "PubMed", "pmid": "1", "title": "A", "metadata": {"pmid": "1"}}],
        "extension_payloads": {},
    }

    result = disease_survey_intelligence_node(state)

    assert result["status"] == "disease_survey_intelligence_skipped"
    assert "slot_disease_survey" not in result.get("extension_payloads", {})
```

### Task 7.2: Implement node

- [ ] Add `src/graph/nodes/disease_survey_intelligence_node.py`.

Implementation shape:

```python
_DISEASE_SURVEY_INTENT_TERMS = ("survey", "comprehensive", "landscape", "overview")
_DISEASE_TERMS = ("alzheimer", "parkinson", "huntington", "multiple sclerosis", "als", "amyotrophic")


def _is_disease_survey_intent(query: str) -> bool:
    text = (query or "").lower()
    return any(term in text for term in _DISEASE_TERMS) and any(term in text for term in _DISEASE_SURVEY_INTENT_TERMS)


def disease_survey_intelligence_node(state: AgentState) -> Dict[str, Any]:
    logger.info("🧠 NODE: DISEASE SURVEY INTELLIGENCE")
    query = state.get("user_query", "")
    harvested_data = state.get("harvested_data", []) or []
    extension_payloads = dict(state.get("extension_payloads") or {})

    if not harvested_data or not _is_disease_survey_intent(query):
        return {"extension_payloads": extension_payloads, "status": "disease_survey_intelligence_skipped"}

    slot = build_disease_survey_slot(
        harvested_data,
        query,
        source_payloads=state.get("harvest_source_payloads") or {},
    )
    extension_payloads["slot_disease_survey"] = slot
    return {
        "extension_payloads": extension_payloads,
        "disease_survey_slot": slot,
        "status": "disease_survey_intelligence_complete",
    }
```

### Task 7.3: Wire workflow and exports

- [ ] Update `src/graph/nodes/__init__.py`.

Implementation shape:

```python
from .disease_survey_intelligence_node import disease_survey_intelligence_node
```

- [ ] Update `src/graph/workflow.py`.

Implementation shape:

```python
from src.graph.nodes import (
    clinical_analyzer_node,
    disease_survey_intelligence_node,
    evidence_synthesizer_node,
    extension_handoff_node,
    harvester_node,
    quality_assessor_node,
    writer_node,
)

workflow.add_node("disease_survey_intelligence", disease_survey_intelligence_node)
workflow.add_edge(START, "harvester")
workflow.add_edge("harvester", "disease_survey_intelligence")
workflow.add_edge("disease_survey_intelligence", "extension_handoff")
```

- [ ] Verify topology with a small test if an existing workflow test exists; otherwise rely on node tests plus import check:

```powershell
python -m pytest tests/test_disease_survey_intelligence_node.py
python - <<'PY'
from src.graph.workflow import create_workflow
workflow = create_workflow()
print(workflow)
PY
```

Use a PowerShell-compatible inline Python invocation if needed:

```powershell
@'
from src.graph.workflow import create_workflow
workflow = create_workflow()
print(workflow)
'@ | python -
```

### Task 7.4: Ensure extension handoff preserves the disease slot

- [ ] Update `src/graph/nodes/extension_handoff_node.py`:

```python
extension_payloads.setdefault("slot_disease_survey", {})
```

Important: This must use `setdefault`, not assignment, so the intelligence node's populated slot is not deleted.

- [ ] Add/extend tests for handoff preservation. If no test file exists, add this assertion to `tests/test_disease_survey_intelligence_node.py` or create `tests/test_extension_handoff_node.py`.

Test intent:

```python
from src.graph.nodes.extension_handoff_node import extension_handoff_node


def test_extension_handoff_preserves_existing_disease_slot():
    slot = {"intent": {"report_type": "disease_survey"}}
    result = extension_handoff_node({"extension_payloads": {"slot_disease_survey": slot}})

    assert result["extension_payloads"]["slot_disease_survey"] is slot
```

- [ ] Verify:

```powershell
python -m pytest tests/test_disease_survey_intelligence_node.py tests/test_writer_slot_consumption.py
```

- [ ] Commit after Phase 7 passes:

```powershell
git add src/graph/nodes/disease_survey_intelligence_node.py src/graph/nodes/__init__.py src/graph/workflow.py src/graph/nodes/extension_handoff_node.py tests/test_disease_survey_intelligence_node.py
git commit -m "feat: add disease survey intelligence node"
```

---

## Phase 8: Make Writer Consume Slots Without Generating Data

### Task 8.1: Add writer tests proving slot path is primary

- [ ] Extend `tests/test_writer_slot_consumption.py`.

Test intent:

```python
from unittest.mock import patch

from src.agents.report_writer import ReportWriterAgent


def _valid_disease_slot():
    return {
        "intent": {"report_type": "disease_survey", "disease_name": "Alzheimer's Disease", "original_query": "Alzheimer survey", "confidence": "high"},
        "entity_profile": {"primary_entity": "Alzheimer's Disease", "entity_type": "disease", "synonyms": [], "excluded_query_terms": []},
        "field_audit": {},
        "pipeline_assets": [
            {"asset_name": "Lecanemab", "company": "Eisai / Biogen", "sponsor": "Eisai", "phase": "Phase 3", "status": "Completed", "modality": "Monoclonal Antibody", "targets": ["Aβ"], "trial_ids": ["NCT1"], "is_therapeutic": True, "asset_note": "", "evidence_ids": ["ev_ctgov_NCT1"]},
        ],
        "trial_landscape": [],
        "company_technical_routes": [],
        "literature_review": {"journal_scope": "top_50_only", "year_scope": "last_5_years", "search_queries_used": [], "records": [], "filtered_out_count": 0},
        "pipeline_timeline_competition_risks": [],
        "charts": {},
        "evidence_registry": [],
    }


def test_report_writer_uses_disease_slot_before_legacy_aggregation(tmp_path):
    agent = ReportWriterAgent()

    with patch("src.agents.report_writer.aggregate_survey_data", side_effect=AssertionError("legacy aggregator should not run")):
        output = agent.write_report(
            user_query="conduct a comprehensive survey on Alzheimer disease",
            harvest_data={"results": [{"source": "PubMed", "pmid": "1", "title": "A", "metadata": {"pmid": "1"}}]},
            synthesis_sections={"slot_disease_survey": _valid_disease_slot()},
            output_dir=str(tmp_path),
        )

    assert output.analysis_position == "DISEASE_SURVEY"
    assert "Company Technical Route Analysis" in output.markdown_content
```

Patch target may need adjustment because `aggregate_survey_data` is imported lazily today. If the import remains lazy, patch `src.engines.report_engine.disease_survey.aggregator.aggregate_survey_data` and assert the slot path does not call it.

### Task 8.2: Update `ReportWriterAgent.write_report()`

- [ ] Remove `del extra_payload`.
- [ ] Extract `synthesis_sections`.
- [ ] Validate and route `slot_disease_survey` before `_is_disease_survey(rows)`.
- [ ] Add `_write_disease_survey_slot_report()`.

Implementation shape:

```python
        synthesis_sections = extra_payload.get("synthesis_sections") if isinstance(extra_payload, dict) else {}
        if not isinstance(synthesis_sections, dict):
            synthesis_sections = {}
        disease_slot = synthesis_sections.get("slot_disease_survey")

        if isinstance(disease_slot, dict):
            from src.engines.report_engine.disease_survey.intelligence import validate_disease_survey_slot

            slot_errors = validate_disease_survey_slot(disease_slot)
            if not slot_errors:
                logger.info("Disease survey slot detected, rendering slot-authoritative report")
                return self._write_disease_survey_slot_report(
                    slot=disease_slot,
                    user_query=_safe_text(user_query, 500),
                    output_dir=output_dir,
                    project_name=resolved_project_name,
                )
            logger.warning(f"Invalid disease survey slot, falling back: {slot_errors[:5]}")
```

Implementation shape for helper:

```python
    def _write_disease_survey_slot_report(
        self,
        slot: Dict[str, Any],
        user_query: str,
        output_dir: str,
        project_name: str,
    ) -> "ReportOutput":
        from src.engines.report_engine.disease_survey.composer import compose_disease_survey_slot_report_bundle

        bundle = compose_disease_survey_slot_report_bundle(slot, llm_client=self.llm)
        markdown_content = bundle["markdown"]
        markdown_path = self._save_markdown(markdown_content, output_dir, project_name)
        html_path, pdf_path = self._save_rendered_artifacts(
            markdown_content=markdown_content,
            output_dir=output_dir,
            project_name=project_name,
            document_ir=bundle.get("document_ir"),
        )
        return ReportOutput(
            markdown_content=markdown_content,
            markdown_path=markdown_path,
            html_path=html_path,
            pdf_path=pdf_path,
            analysis_position="DISEASE_SURVEY",
            data_confidence=9.0,
            signal_severity_score=0.0,
        )
```

### Task 8.3: Simplify `writer_node`

- [ ] Remove the unused `survey_state = aggregate_survey_data(...)` branch from `src/graph/nodes/writer_node.py`.
- [ ] Keep `writer_node` responsible for packaging payload and calling `agent.write_report(**writer_payload)`.
- [ ] Update `has_extensions` to include `slot_disease_survey`:

```python
        has_extensions = any(
            bool(extension_payloads.get(slot))
            for slot in ("slot_a", "slot_b", "slot_c", "slot_disease_survey")
        )
```

- [ ] If `aggregate_survey_data` import becomes unused, remove it from `writer_node.py`.

- [ ] Verify:

```powershell
python -m pytest tests/test_writer_slot_consumption.py tests/test_report_writer_agent.py
```

- [ ] Commit after Phase 8 passes:

```powershell
git add src/agents/report_writer.py src/graph/nodes/writer_node.py tests/test_writer_slot_consumption.py
git commit -m "feat: render disease reports from handoff slot"
```

---

## Phase 9: Render Seven-Chapter Slot Report With Injected Tables And Charts

### Task 9.1: Add slot composer tests

- [ ] Extend `tests/test_disease_survey_composer.py`.

Test intent:

```python
from src.engines.report_engine.disease_survey.composer import (
    compose_disease_survey_slot_report,
    compose_disease_survey_slot_report_bundle,
)


def test_slot_report_uses_new_seven_chapter_structure():
    report = compose_disease_survey_slot_report(_valid_disease_slot())

    assert list(report.keys()) == [
        "executive_summary",
        "drug_pipeline",
        "trial_landscape",
        "company_technical_route_analysis",
        "literature_review",
        "cns_benchmark",
        "pipeline_timeline_competition_risk",
    ]
    assert "sponsor_analysis" not in report
    assert "target_biology" not in report
    assert "safety_profile" not in report


def test_slot_markdown_injects_tables_charts_and_risk_data():
    bundle = compose_disease_survey_slot_report_bundle(_valid_disease_slot())
    markdown = bundle["markdown"]

    assert "## Company Technical Route Analysis" in markdown
    assert "## Pipeline Timeline And Competition Risk" in markdown
    assert "非药物/非治疗性" not in markdown or "Therapeutic Flag" in markdown
    assert "Sponsor Analysis" not in markdown
    assert "Target Biology" not in markdown
    assert "Safety Profile" not in markdown
    assert bundle["document_ir"]["chapters"]
```

### Task 9.2: Implement slot renderers

- [ ] In `src/engines/report_engine/disease_survey/renderer.py`, keep legacy state renderers but add slot renderers:

```python
def _slot_charts(slot: Dict[str, Any]) -> Dict[str, Any]:
    charts = slot.get("charts")
    return charts if isinstance(charts, dict) else {}


def render_slot_executive_summary(slot: Dict[str, Any]) -> Dict[str, Any]:
    assets = slot.get("pipeline_assets") or []
    trials = slot.get("trial_landscape") or []
    literature = (slot.get("literature_review") or {}).get("records") or []
    charts = _slot_charts(slot)
    return {
        "intent": slot.get("intent") or {},
        "entity_profile": slot.get("entity_profile") or {},
        "field_audit": slot.get("field_audit") or {},
        "total_assets": len(assets),
        "total_trials": len(trials),
        "total_literature": len(literature),
        "therapeutic_assets": sum(1 for asset in assets if asset.get("is_therapeutic") is True),
        "non_therapeutic_assets": sum(1 for asset in assets if asset.get("is_therapeutic") is False),
        "phase_chart": charts.get("phase_distribution"),
        "therapeutic_chart": charts.get("therapeutic_vs_non_therapeutic"),
    }


def render_slot_drug_pipeline(slot: Dict[str, Any]) -> Dict[str, Any]:
    charts = _slot_charts(slot)
    assets = sorted(
        list(slot.get("pipeline_assets") or []),
        key=lambda asset: (asset.get("is_therapeutic") is not True, asset.get("asset_name") or ""),
    )
    return {
        "assets": assets,
        "phase_chart": charts.get("phase_distribution"),
        "target_chart": charts.get("target_distribution"),
        "therapeutic_chart": charts.get("therapeutic_vs_non_therapeutic"),
    }


def render_slot_trial_landscape(slot: Dict[str, Any]) -> Dict[str, Any]:
    charts = _slot_charts(slot)
    trials = list(slot.get("trial_landscape") or [])
    return {
        "trials": trials,
        "total": len(trials),
        "status_chart": charts.get("trial_status_distribution"),
        "phase_chart": charts.get("phase_distribution"),
        "timeline_availability_chart": charts.get("timeline_availability"),
    }


def render_slot_company_technical_route_analysis(slot: Dict[str, Any]) -> Dict[str, Any]:
    charts = _slot_charts(slot)
    routes = list(slot.get("company_technical_routes") or [])
    return {
        "routes": routes,
        "total": len(routes),
        "company_route_chart": charts.get("company_route_distribution"),
        "target_chart": charts.get("target_distribution"),
        "modality_chart": charts.get("modality_distribution"),
    }


def render_slot_literature_review(slot: Dict[str, Any]) -> Dict[str, Any]:
    charts = _slot_charts(slot)
    literature = slot.get("literature_review") or {}
    return {
        "journal_scope": literature.get("journal_scope"),
        "year_scope": literature.get("year_scope"),
        "search_queries_used": literature.get("search_queries_used") or [],
        "records": literature.get("records") or [],
        "filtered_out_count": literature.get("filtered_out_count", 0),
        "journal_chart": charts.get("top50_journal_distribution"),
        "year_chart": charts.get("literature_year_distribution"),
        "matched_target_chart": charts.get("matched_target_distribution"),
    }


def render_slot_cns_benchmark(slot: Dict[str, Any]) -> Dict[str, Any]:
    charts = _slot_charts(slot)
    return {
        "entries": slot.get("cns_benchmark") or [],
        "target_alignment_chart": charts.get("cns_target_alignment"),
        "top50_target_hit_chart": charts.get("top50_target_hit_distribution"),
    }


def render_slot_pipeline_timeline_competition_risk(slot: Dict[str, Any]) -> Dict[str, Any]:
    charts = _slot_charts(slot)
    risks = list(slot.get("pipeline_timeline_competition_risks") or [])
    return {
        "risks": risks,
        "total": len(risks),
        "timeline_risk_chart": charts.get("timeline_risk_distribution"),
        "competition_risk_chart": charts.get("competition_risk_distribution"),
        "competition_bucket_chart": charts.get("competition_bucket_distribution"),
    }
```

Rules:

- Renderers only reshape existing slot data.
- Missing chart payloads return no widget; do not invent chart data.
- Missing fields render `数据不足` or `—`.
- `Drug Pipeline` includes non-therapeutic rows and marks them `非药物/非治疗性`.
- `Pipeline Timeline And Competition Risk` includes only therapeutic assets through `slot["pipeline_timeline_competition_risks"]`.

### Task 9.3: Implement slot composer functions

- [ ] In `src/engines/report_engine/disease_survey/composer.py`, keep legacy functions but add:

```python
def compose_disease_survey_slot_report(slot: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "executive_summary": render_slot_executive_summary(slot),
        "drug_pipeline": render_slot_drug_pipeline(slot),
        "trial_landscape": render_slot_trial_landscape(slot),
        "company_technical_route_analysis": render_slot_company_technical_route_analysis(slot),
        "literature_review": render_slot_literature_review(slot),
        "cns_benchmark": render_slot_cns_benchmark(slot),
        "pipeline_timeline_competition_risk": render_slot_pipeline_timeline_competition_risk(slot),
    }
```

- [ ] Add:

```python
def build_disease_survey_slot_document(slot: Dict[str, Any], report_id: str | None = None) -> Dict[str, Any]:
    sections = compose_disease_survey_slot_report(slot)
    disease_name = (slot.get("intent") or {}).get("disease_name") or "Disease Survey"
    if report_id is None:
        report_id = f"disease-survey-slot-{sanitize_filename(disease_name)}"
    chapters = _build_slot_chapters(sections)
    metadata = {
        "title": f"{disease_name} Disease Survey",
        "disease_name": disease_name,
        "query": (slot.get("intent") or {}).get("original_query", ""),
    }
    return DocumentComposer().build_document(report_id, metadata, chapters)


def disease_survey_slot_to_markdown(slot: Dict[str, Any]) -> str:
    sections = compose_disease_survey_slot_report(slot)
    lines = [f"# {(slot.get('intent') or {}).get('disease_name', 'Disease Survey')} - Disease Survey"]
    lines.extend(_slot_markdown_executive_summary(sections["executive_summary"]))
    lines.extend(_slot_markdown_drug_pipeline(sections["drug_pipeline"]))
    lines.extend(_slot_markdown_trial_landscape(sections["trial_landscape"]))
    lines.extend(_slot_markdown_company_routes(sections["company_technical_route_analysis"]))
    lines.extend(_slot_markdown_literature(sections["literature_review"]))
    lines.extend(_slot_markdown_cns_benchmark(sections["cns_benchmark"]))
    lines.extend(_slot_markdown_pipeline_risk(sections["pipeline_timeline_competition_risk"]))
    return "\n".join(lines).strip() + "\n"


def compose_disease_survey_slot_report_bundle(slot: Dict[str, Any], llm_client: Any | None = None) -> Dict[str, Any]:
    sections = compose_disease_survey_slot_report(slot)
    summary_text = _build_deterministic_slot_summary(slot, sections)
    if llm_client is not None:
        summary_text = _try_slot_summary_llm(llm_client, slot, sections) or summary_text
    sections["executive_summary"]["summary_text"] = summary_text
    return {
        "sections": sections,
        "document_ir": build_disease_survey_slot_document(slot),
        "markdown": disease_survey_slot_to_markdown(slot),
        "analysis_metadata": {
            "summary_source": "slot",
            "field_audit": slot.get("field_audit") or {},
        },
    }
```

Writer summary rule:

- `compose_disease_survey_slot_report_bundle()` may ask LLM for concise prose only using existing slot facts.
- If LLM is used, prompt must explicitly forbid creating assets, companies, risks, evidence, or chart data.
- If LLM fails, deterministic text is enough.

Prompt shape:

```python
(
    "Write a concise executive summary from the supplied structured disease survey slot. "
    "Do not create assets, companies, risk labels, evidence sources, charts, or data fields. "
    "Only summarize the supplied counts and structured facts."
)
```

### Task 9.4: Update legacy tests to accept new primary slot path

- [ ] Existing tests for `compose_disease_survey_report(state)` can remain for fallback compatibility.
- [ ] Tests that assert the primary disease report contains old chapters must be changed to assert legacy-only behavior or removed if obsolete.
- [ ] New slot tests must assert the seven-chapter structure.

- [ ] Verify:

```powershell
python -m pytest tests/test_disease_survey_renderer.py tests/test_disease_survey_composer.py
```

- [ ] Commit after Phase 9 passes:

```powershell
git add src/engines/report_engine/disease_survey/renderer.py src/engines/report_engine/disease_survey/composer.py tests/test_disease_survey_renderer.py tests/test_disease_survey_composer.py
git commit -m "feat: compose seven chapter disease slot reports"
```

---

## Phase 10: End-To-End Disease Survey Acceptance

### Task 10.1: Add E2E test for Alzheimer disease slot report

- [ ] Extend `tests/test_disease_survey_e2e.py`.

Test intent:

```python
from src.engines.report_engine.disease_survey.intelligence import build_disease_survey_slot
from src.engines.report_engine.disease_survey.composer import compose_disease_survey_slot_report_bundle


def test_alzheimer_slot_report_acceptance():
    slot = build_disease_survey_slot(AD_ROWS, "conduct a comprehensive survey on Alzheimer disease")
    bundle = compose_disease_survey_slot_report_bundle(slot)
    markdown = bundle["markdown"]

    assert "## Executive Summary" in markdown
    assert "## Drug Pipeline" in markdown
    assert "## Trial Landscape" in markdown
    assert "## Company Technical Route Analysis" in markdown
    assert "## Literature Review" in markdown
    assert "## CNS Benchmark" in markdown
    assert "## Pipeline Timeline And Competition Risk" in markdown

    assert "## Sponsor Analysis" not in markdown
    assert "## Target Biology" not in markdown
    assert "## Safety Profile" not in markdown

    assert slot["literature_review"]["journal_scope"] == "top_50_only"
    assert all(row["journal"] for row in slot["literature_review"]["records"])
```

### Task 10.2: Add workflow-level smoke test if existing fixtures support it

- [ ] If workflow tests already run nodes with mocks, add a test that:

1. Calls `disease_survey_intelligence_node()`.
2. Calls `extension_handoff_node()` with the result.
3. Calls `writer_node()` with a mocked `create_report_agent()` or a real deterministic writer.
4. Asserts final markdown came from slot path.

- [ ] Avoid live network in tests.

- [ ] Verify:

```powershell
python -m pytest tests/test_disease_survey_e2e.py tests/test_disease_survey_intelligence_node.py tests/test_writer_slot_consumption.py
```

- [ ] Commit after Phase 10 passes:

```powershell
git add tests/test_disease_survey_e2e.py
git commit -m "test: cover disease survey slot acceptance"
```

---

## Phase 11: Documentation Update

### Task 11.1: Update architecture docs

- [ ] Update `docs/competition/architecture/DATA_FLOW_ARCHITECTURE.md`.

Required doc changes:

- Show new workflow:

```text
START -> harvester -> disease_survey_intelligence -> extension_handoff -> evidence_synthesizer -> clinical_analyzer -> quality_assessor -> writer -> END
```

- Document that `aggregate_survey_data()` now runs in the first post-harvest intelligence node for disease-survey reports.
- Explain that `disease survey` still works today through the legacy writer-side fallback, but the primary path is now slot-authoritative.
- Document writer boundary:

```text
Writer may summarize/render existing structured data.
Writer must not generate assets, companies, technical routes, risk labels, evidence, or chart payloads.
```

- Document `slot_disease_survey` top-level shape.
- Document top-50 journal constraint and per-pipeline risk labels.

- [ ] Verify doc references by searching:

```powershell
rg -n "disease_survey_intelligence|slot_disease_survey|Sponsor Analysis|Target Biology|Safety Profile|aggregate_survey_data" docs src tests
```

- [ ] Commit:

```powershell
git add docs/competition/architecture/DATA_FLOW_ARCHITECTURE.md
git commit -m "docs: update disease survey data flow"
```

---

## Phase 12: Final Verification

- [ ] Run targeted full suite for touched areas:

```powershell
python -m pytest tests/test_disease_survey_models.py tests/test_disease_survey_aggregator.py tests/test_literature_top50_scope.py tests/test_pipeline_risk.py tests/test_disease_survey_intelligence_slot.py tests/test_disease_survey_intelligence_node.py tests/test_disease_survey_renderer.py tests/test_disease_survey_composer.py tests/test_disease_survey_e2e.py tests/test_writer_slot_consumption.py tests/test_report_writer_agent.py
```

- [ ] Run import smoke:

```powershell
@'
from src.graph.workflow import create_workflow
from src.engines.report_engine.disease_survey import build_disease_survey_slot
print(create_workflow())
print(build_disease_survey_slot)
'@ | python -
```

- [ ] Search for forbidden or obsolete primary-path behavior:

```powershell
rg -n "del extra_payload|Sponsor Analysis|Target Biology|Safety Profile|Market Landscape|slot_disease_survey" src tests docs
```

Review results carefully:

- `del extra_payload` must be gone from `ReportWriterAgent.write_report()`.
- Old chapter names may remain only in legacy fallback tests/functions, not in primary slot report assertions.
- `slot_disease_survey` should appear in state, node, handoff, writer, tests, and docs.

- [ ] Run self-review diff:

```powershell
git diff --stat
git diff -- src/agents/report_writer.py src/graph/workflow.py src/engines/report_engine/disease_survey
```

- [ ] Commit any final fixes in small scoped commits.

---

## Execution Notes

- Do not call live web services in tests.
- Do not use LLM output to create structured data.
- Do not remove legacy disease survey aggregation in this phase.
- Do not change unrelated dirty files in the current worktree.
- Keep commits scoped. Stage only files changed for the current phase.
- If a phase reveals large unrelated failures, record them and continue with targeted tests for this change set.

---

## Completion Criteria

The implementation is complete when:

- `slot_disease_survey` is created after harvest for disease survey intent.
- `extension_handoff` preserves `slot_a`, `slot_b`, `slot_c`, `slot_kline`, and `slot_disease_survey`.
- `ReportWriterAgent.write_report()` consumes `slot_disease_survey` before legacy disease survey aggregation.
- The primary disease report renders the seven target chapters.
- Old independent chapters are absent from the primary slot report.
- Literature Review and CNS Benchmark use only top-50 journal records.
- Non-therapeutic rows remain visible and are marked `非药物/非治疗性`.
- Company Technical Route Analysis covers pharma/biotech therapeutic sponsors only.
- Final pipeline risk chapter includes only therapeutic assets and every risk label has evidence or `数据不足`.
- Tests prove the writer does not generate data when a valid slot exists.
