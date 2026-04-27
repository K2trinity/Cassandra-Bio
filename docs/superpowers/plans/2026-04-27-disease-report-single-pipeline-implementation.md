# Single Disease Report Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build one disease report generation pipeline that resolves any user-specified disease, harvests only disease-relevant ClinicalTrials.gov records, preserves source fields through a typed handoff contract, and renders a three-section report from one report IR.

**Architecture:** Replace the current LangGraph plus disease_survey side branch with a clean pipeline using ports and adapters: resolver -> ClinicalTrials source adapter -> normalizer -> relevance gate -> typed handoff package -> deterministic risk engine -> report IR -> renderers. The service facade keeps the public `WorkflowService.run()` and `WorkflowService.stream()` methods used by `app.py`, but those methods call the new orchestrator only and do not route through the legacy generic graph or writer fallback.

**Tech Stack:** Python 3.11, Pydantic v2, `requests`, `pytest`, `concurrent.futures.ThreadPoolExecutor`, existing `MarkdownRenderer`, `HTMLRenderer`, and `PDFRenderer` infrastructure.

---

## Context

The current report proved that the report shape is useful, but the data path is wrong. ClinicalTrials status exists upstream in `src/tools/clinical_trials_client.py`, but the old disease survey aggregator reads only a narrow metadata alias set and drops the field. The same old path also admits unrelated trials because disease relevance is checked after broad harvest, not at the source boundary.

This implementation removes the old disease report branch instead of patching it. The only production disease report flow after this plan is:

```text
WorkflowService
  -> DiseaseReportOrchestrator
  -> DiseaseResolver
  -> ClinicalTrialsConditionDiscovery
  -> ClinicalTrialsDiseaseHarvester
  -> SourceFieldNormalizer
  -> DiseaseRelevanceGate
  -> DiseaseReportPackageBuilder
  -> RuleBasedRiskEngine
  -> DiseaseReportIRBuilder
  -> DiseaseReportRendererAdapter
```

The report contains exactly these chapters:

```text
1. Executive Summary
2. Clinical Trial And Pipeline Landscape
3. Pipeline Timeline And Competition Risk
```

The landscape table contains exactly these display columns:

```text
Study Title
NCT Number
Status
Conditions
Interventions
Sponsor
Study Type
```

The disease report data contract and final report do not contain `Enrollment` or `Primary Endpoint`.

## File Structure

Create a cohesive disease report package:

```text
src/reports/
  __init__.py
  disease/
    __init__.py
    models.py
    resolver.py
    condition_matcher.py
    clinicaltrials_harvester.py
    normalizer.py
    relevance.py
    package_builder.py
    risk_engine.py
    ir_builder.py
    renderer_adapter.py
    orchestrator.py
    company_routes.py
```

Modify existing service and renderer boundaries:

```text
src/services/workflow_service.py
src/engines/report_engine/renderers/html_renderer.py
src/engines/report_engine/__init__.py
src/agents/__init__.py
app.py
```

Remove the legacy disease report graph and writer branch:

```text
src/agents/supervisor.py
src/agents/report_writer.py
src/agents/report_writer_agent.py
src/engines/report_engine/agent.py
src/graph/workflow.py
src/graph/state.py
src/graph/profile.py
src/graph/contracts.py
src/graph/nodes/
src/engines/report_engine/disease_survey/
```

Keep these as shared infrastructure:

```text
src/tools/clinical_trials_client.py
src/engines/report_engine/renderers/
src/engines/report_engine/ir/
```

Create new tests:

```text
tests/reports/disease/test_models.py
tests/reports/disease/test_resolver_and_matcher.py
tests/reports/disease/test_clinicaltrials_harvester.py
tests/reports/disease/test_normalizer_and_relevance.py
tests/reports/disease/test_package_builder.py
tests/reports/disease/test_risk_engine.py
tests/reports/disease/test_ir_builder.py
tests/reports/disease/test_renderer_adapter.py
tests/reports/disease/test_workflow_service.py
tests/reports/disease/test_end_to_end_pipeline.py
```

Remove or replace old tests that assert the deleted disease_survey slot and generic graph behavior:

```text
tests/test_writer_slot_consumption.py
tests/test_report_writer_agent.py
tests/test_disease_survey_renderer.py
tests/test_disease_survey_models.py
tests/test_disease_survey_e2e.py
tests/test_disease_survey_composer.py
tests/test_disease_survey_aggregator.py
tests/test_company_route_enrichment.py
tests/test_dataflow_integrity.py
tests/dev_checks/check_harvest_dataflow.py
tests/dev_checks/check_source_to_report_chain.py
```

## Execution Rules

- Do not stage unrelated dirty worktree changes.
- Use `git status --short` before every commit and stage only files named in the task.
- Do not keep compatibility branches for the old disease_survey slot or legacy generic graph.
- All ClinicalTrials network behavior must be injectable for unit tests.
- Unit tests must use fake ClinicalTrials payloads and must not call the network.

---

### Task 1: Typed Disease Report Models

**Files:**
- Create: `src/reports/__init__.py`
- Create: `src/reports/disease/__init__.py`
- Create: `src/reports/disease/models.py`
- Test: `tests/reports/disease/test_models.py`

- [ ] **Step 1: Write the failing model tests**

Create `tests/reports/disease/test_models.py`:

```python
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from src.reports.disease.models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)


def test_clinical_trial_record_has_required_report_fields_only():
    record = ClinicalTrialRecord(
        study_title="A Study of Donanemab in Early Symptomatic Alzheimer Disease",
        nct_number="NCT00000001",
        status="RECRUITING",
        conditions=["Alzheimer Disease"],
        interventions=["Donanemab"],
        sponsor="Eli Lilly and Company",
        study_type="INTERVENTIONAL",
        study_first_posted=date(2026, 4, 20),
        last_update_posted=date(2026, 4, 22),
        start_date=date(2026, 5, 1),
        primary_completion_date=date(2029, 5, 1),
        completion_date=None,
        source_url="https://clinicaltrials.gov/study/NCT00000001",
    )

    payload = record.model_dump()

    assert payload["status"] == "RECRUITING"
    assert payload["conditions"] == ["Alzheimer Disease"]
    assert "enrollment" not in payload
    assert "primary_endpoint" not in payload


def test_clinical_trial_record_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        ClinicalTrialRecord(
            study_title="Noise row",
            nct_number="NCT00000002",
            status="UNKNOWN",
            conditions=["Alzheimer Disease"],
            interventions=[],
            sponsor="Unknown",
            study_type="OBSERVATIONAL",
            source_url="https://clinicaltrials.gov/study/NCT00000002",
            enrollment="100",
        )


def test_disease_report_package_carries_handoff_contract():
    profile = DiseaseProfile(
        query="conduct a comprehensive survey on Alzheimer disease",
        disease_name="Alzheimer Disease",
        canonical_condition="Alzheimer Disease",
        condition_terms=["Alzheimer Disease", "Alzheimer's Disease"],
        normalized_terms=["alzheimer disease"],
        expert_topic_url="https://clinicaltrials.gov/expert-search?term=Alzheimer%20Disease&viewType=Topic",
        expert_full_match_url="https://clinicaltrials.gov/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D&viewType=Card&sort=StudyFirstPostDate",
    )
    trial = ClinicalTrialRecord(
        study_title="A Study in Alzheimer Disease",
        nct_number="NCT00000003",
        status="COMPLETED",
        conditions=["Alzheimer Disease"],
        interventions=["Amyloid antibody"],
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=date(2025, 1, 1),
        source_url="https://clinicaltrials.gov/study/NCT00000003",
    )
    risk = PipelineRiskRecord(
        nct_number="NCT00000003",
        study_title="A Study in Alzheimer Disease",
        sponsor="Sponsor A",
        status="COMPLETED",
        intervention_category="amyloid antibody",
        timeline_signal="Low",
        timeline_evidence="Study first posted 2025-01-01; status COMPLETED; age 1.3 years.",
        competition_signal="High",
        competition_evidence="8 retained Alzheimer Disease studies share intervention category amyloid antibody.",
    )
    audit = SourceAudit(
        topic_url=profile.expert_topic_url,
        full_match_url=profile.expert_full_match_url,
        selected_condition_terms=profile.condition_terms,
        raw_count=3,
        retained_count=1,
        rejected_count=2,
        rejected_nct_numbers=["NCT_BAD_1", "NCT_BAD_2"],
    )

    package = DiseaseReportPackage(
        disease_profile=profile,
        clinical_trials=[trial],
        risk_records=[risk],
        source_audit=audit,
        generated_at=datetime(2026, 4, 27, tzinfo=timezone.utc),
    )

    assert package.disease_profile.disease_name == "Alzheimer Disease"
    assert package.clinical_trials[0].status == "COMPLETED"
    assert package.source_audit.retained_count == 1
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_models.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports'
```

- [ ] **Step 3: Create the package and model implementation**

Create `src/reports/__init__.py`:

```python
"""Report pipeline packages."""
```

Create `src/reports/disease/__init__.py`:

```python
"""Single disease report pipeline."""

from .models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportArtifacts,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)

__all__ = [
    "ClinicalTrialRecord",
    "DiseaseProfile",
    "DiseaseReportArtifacts",
    "DiseaseReportPackage",
    "PipelineRiskRecord",
    "SourceAudit",
]
```

Create `src/reports/disease/models.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DiseaseProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1)
    disease_name: str = Field(..., min_length=1)
    canonical_condition: str = Field(..., min_length=1)
    condition_terms: list[str] = Field(default_factory=list)
    normalized_terms: list[str] = Field(default_factory=list)
    expert_topic_url: str = Field(..., min_length=1)
    expert_full_match_url: str = Field(..., min_length=1)


class ClinicalTrialRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    study_title: str = Field(..., min_length=1)
    nct_number: str = Field(..., min_length=1)
    status: str = Field(default="Unknown", min_length=1)
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    sponsor: str = "Unknown"
    study_type: str = "Unknown"
    study_first_posted: date | None = None
    last_update_posted: date | None = None
    start_date: date | None = None
    primary_completion_date: date | None = None
    completion_date: date | None = None
    source_url: str = Field(..., min_length=1)


class PipelineRiskRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    nct_number: str = Field(..., min_length=1)
    study_title: str = Field(..., min_length=1)
    sponsor: str = ""
    status: str = ""
    intervention_category: str = ""
    timeline_signal: str = "Data insufficient"
    timeline_evidence: str = ""
    competition_signal: str = "Data insufficient"
    competition_evidence: str = ""


class SourceAudit(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_url: str = ""
    full_match_url: str = ""
    selected_condition_terms: list[str] = Field(default_factory=list)
    raw_count: int = 0
    retained_count: int = 0
    rejected_count: int = 0
    rejected_nct_numbers: list[str] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    details: dict[str, Any] = Field(default_factory=dict)


class DiseaseReportPackage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    disease_profile: DiseaseProfile
    clinical_trials: list[ClinicalTrialRecord] = Field(default_factory=list)
    risk_records: list[PipelineRiskRecord] = Field(default_factory=list)
    source_audit: SourceAudit
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DiseaseReportArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    markdown_content: str
    markdown_path: str | None = None
    html_path: str | None = None
    pdf_path: str | None = None
    ir_path: str | None = None
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_models.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/reports/__init__.py src/reports/disease/__init__.py src/reports/disease/models.py tests/reports/disease/test_models.py
git commit -m "feat: add typed disease report models"
```

---

### Task 2: Disease Resolver And Condition Matching

**Files:**
- Create: `src/reports/disease/resolver.py`
- Create: `src/reports/disease/condition_matcher.py`
- Test: `tests/reports/disease/test_resolver_and_matcher.py`

- [ ] **Step 1: Write failing resolver and matcher tests**

Create `tests/reports/disease/test_resolver_and_matcher.py`:

```python
from src.reports.disease.condition_matcher import (
    condition_variants,
    conditions_full_match,
    normalize_condition_text,
)
from src.reports.disease.resolver import DiseaseResolver, build_expert_full_match_url


def test_resolver_extracts_disease_from_report_prompt():
    profile = DiseaseResolver().resolve("conduct a comprehensive survey on Alzheimer disease")

    assert profile.disease_name == "Alzheimer Disease"
    assert profile.canonical_condition == "Alzheimer Disease"
    assert "Alzheimer's Disease" in profile.condition_terms
    assert profile.normalized_terms == ["alzheimer disease"]
    assert profile.expert_topic_url.endswith("term=Alzheimer%20Disease&viewType=Topic")
    assert "AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D" in profile.expert_full_match_url


def test_resolver_handles_possessive_user_input():
    profile = DiseaseResolver().resolve("Alzheimer's disease pipeline")

    assert profile.disease_name == "Alzheimer Disease"
    assert set(profile.condition_terms) == {
        "Alzheimer Disease",
        "Alzheimer's Disease",
        "Alzheimers Disease",
    }


def test_normalize_condition_text_collapses_possessive_and_punctuation():
    assert normalize_condition_text("Alzheimer's Disease") == "alzheimer disease"
    assert normalize_condition_text("Alzheimers disease") == "alzheimer disease"
    assert normalize_condition_text("  Alzheimer-Disease  ") == "alzheimer disease"


def test_conditions_full_match_accepts_equivalent_ad_terms():
    profile = DiseaseResolver().resolve("Alzheimer disease")

    assert conditions_full_match(["Alzheimer's Disease"], profile)
    assert conditions_full_match(["Alzheimer Disease"], profile)
    assert conditions_full_match(["ALZHEIMERS DISEASE"], profile)


def test_conditions_full_match_rejects_non_target_and_broad_terms():
    profile = DiseaseResolver().resolve("Alzheimer disease")

    assert not conditions_full_match(["Parkinson Disease"], profile)
    assert not conditions_full_match(["Cognitive Impairment"], profile)
    assert not conditions_full_match(["Mild Cognitive Impairment"], profile)
    assert not conditions_full_match(["Caregiver Education"], profile)


def test_condition_variants_for_non_ad_disease_are_stable():
    assert condition_variants("Parkinson Disease") == ["Parkinson Disease"]
    assert build_expert_full_match_url("Parkinson Disease").endswith(
        "AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BParkinson%20Disease%5D%5D&viewType=Card&sort=StudyFirstPostDate"
    )
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_resolver_and_matcher.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.resolver'
```

- [ ] **Step 3: Implement resolver and condition matcher**

Create `src/reports/disease/condition_matcher.py`:

```python
from __future__ import annotations

import re
from typing import Iterable

from .models import DiseaseProfile


BROAD_NON_ANCHOR_TERMS = {
    "care delivery",
    "caregiver",
    "caregiver education",
    "cognitive behavioral therapy",
    "cognitive dysfunction",
    "cognitive impairment",
    "dementia",
    "education",
    "mild cognitive impairment",
    "nursing career",
}


def normalize_condition_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\balzheimer[' ]?s\b", "alzheimer", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def condition_variants(disease_name: str) -> list[str]:
    cleaned = _title_case_entity(disease_name)
    normalized = normalize_condition_text(cleaned)
    if normalized == "alzheimer disease":
        return ["Alzheimer Disease", "Alzheimer's Disease", "Alzheimers Disease"]
    return [cleaned]


def conditions_full_match(conditions: Iterable[str], profile: DiseaseProfile) -> bool:
    allowed = set(profile.normalized_terms)
    if not allowed:
        allowed = {normalize_condition_text(term) for term in profile.condition_terms}
    for condition in conditions or []:
        normalized = normalize_condition_text(str(condition))
        if normalized in BROAD_NON_ANCHOR_TERMS:
            continue
        if normalized in allowed:
            return True
    return False


def _title_case_entity(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9' -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    words = []
    lower_words = {"and", "or", "of", "in", "with", "for"}
    for index, word in enumerate(text.split()):
        lowered = word.lower()
        if index > 0 and lowered in lower_words:
            words.append(lowered)
        elif word.isupper() and len(word) <= 6:
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)
```

Create `src/reports/disease/resolver.py`:

```python
from __future__ import annotations

import re
from urllib.parse import quote

from .condition_matcher import condition_variants, normalize_condition_text
from .models import DiseaseProfile


EXPERT_SEARCH_BASE = "https://clinicaltrials.gov/expert-search"


class DiseaseResolver:
    def resolve(self, user_query: str) -> DiseaseProfile:
        disease_name = _extract_disease_name(user_query)
        canonical = _canonical_condition(disease_name)
        variants = condition_variants(canonical)
        normalized_terms = sorted({normalize_condition_text(term) for term in variants})
        return DiseaseProfile(
            query=str(user_query or "").strip(),
            disease_name=canonical,
            canonical_condition=canonical,
            condition_terms=variants,
            normalized_terms=normalized_terms,
            expert_topic_url=build_expert_topic_url(canonical),
            expert_full_match_url=build_expert_full_match_url(canonical),
        )


def build_expert_topic_url(disease_name: str) -> str:
    return f"{EXPERT_SEARCH_BASE}?term={quote(disease_name)}&viewType=Topic"


def build_expert_full_match_url(disease_name: str) -> str:
    expression = f"AREA[Condition]COVERAGE[FullMatch[{disease_name}]]"
    return f"{EXPERT_SEARCH_BASE}?term={quote(expression)}&viewType=Card&sort=StudyFirstPostDate"


def _extract_disease_name(user_query: str) -> str:
    text = re.sub(r"\s+", " ", str(user_query or "")).strip()
    patterns = [
        r"^(?:conduct|perform|run|create|generate|write|prepare)\s+(?:a\s+|an\s+)?(?:comprehensive\s+|full\s+|complete\s+)?(?:disease\s+)?(?:survey|landscape|overview|review|report|analysis)\s+(?:on|of|about|for)\s+(.+)$",
        r"^(?:comprehensive\s+|full\s+|complete\s+)?(?:disease\s+)?(?:survey|landscape|overview|review|report|analysis)\s+(?:on|of|about|for)\s+(.+)$",
        r"^(.+?)\s+(?:disease\s+)?(?:survey|landscape|overview|review|report|analysis|pipeline)\s*$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_candidate(match.group(1))
    return _clean_candidate(text)


def _clean_candidate(value: str) -> str:
    text = str(value or "").strip()
    text = re.split(r"\s+(?:with|using|based on|from)\s+", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"[,;:|/]", text, maxsplit=1)[0]
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "Disease"


def _canonical_condition(value: str) -> str:
    normalized = normalize_condition_text(value)
    if normalized == "alzheimer disease":
        return "Alzheimer Disease"
    words = []
    for word in _clean_candidate(value).split():
        words.append(word if word.isupper() and len(word) <= 6 else word[:1].upper() + word[1:].lower())
    return " ".join(words)
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_resolver_and_matcher.py -v
```

Expected:

```text
6 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/reports/disease/resolver.py src/reports/disease/condition_matcher.py tests/reports/disease/test_resolver_and_matcher.py
git commit -m "feat: resolve disease condition terms"
```

---

### Task 3: ClinicalTrials Condition Discovery And Disease Harvester

**Files:**
- Create: `src/reports/disease/clinicaltrials_harvester.py`
- Test: `tests/reports/disease/test_clinicaltrials_harvester.py`

- [ ] **Step 1: Write failing harvester tests**

Create `tests/reports/disease/test_clinicaltrials_harvester.py`:

```python
from datetime import date, timedelta

from src.reports.disease.clinicaltrials_harvester import (
    ClinicalTrialsConditionDiscovery,
    ClinicalTrialsDiseaseHarvester,
)
from src.reports.disease.resolver import DiseaseResolver


def _api_study(nct, title, conditions, first_posted, status="RECRUITING"):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": title},
            "statusModule": {
                "overallStatus": status,
                "studyFirstPostDateStruct": {"date": first_posted},
            },
            "conditionsModule": {"conditions": conditions},
            "armsInterventionsModule": {"interventions": [{"name": "Donanemab"}]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Sponsor A"}},
            "designModule": {"studyType": "INTERVENTIONAL"},
        }
    }


def test_condition_discovery_prefers_full_match_condition_link():
    html = """
    <a href="/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%27s%20Disease%5D%5D&viewType=Card">
      Alzheimer's Disease
    </a>
    """

    def get_text(url):
        assert "viewType=Topic" in url
        return html

    profile = DiseaseResolver().resolve("Alzheimer disease")
    updated = ClinicalTrialsConditionDiscovery(get_text=get_text).discover(profile)

    assert updated.canonical_condition == "Alzheimer Disease"
    assert "Alzheimer's Disease" in updated.condition_terms
    assert "Alzheimer Disease" in updated.condition_terms


def test_harvester_uses_condition_query_and_filters_full_match_locally():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    payload = {
        "studies": [
            _api_study("NCT00000001", "Newest AD", ["Alzheimer's Disease"], "2026-04-20"),
            _api_study("NCT00000002", "Parkinson title mentions Alzheimer", ["Parkinson Disease"], "2026-04-21"),
            _api_study("NCT00000003", "Older AD", ["Alzheimer Disease"], "2025-01-10"),
        ]
    }
    calls = []

    def get_json(url, params):
        calls.append((url, dict(params)))
        return payload

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    assert calls[0][0] == "https://clinicaltrials.gov/api/v2/studies"
    assert calls[0][1]["query.cond"] == "Alzheimer Disease"
    assert result.raw_count == 3
    assert [study["protocolSection"]["identificationModule"]["nctId"] for study in result.studies] == [
        "NCT00000001",
        "NCT00000003",
    ]
    assert result.rejected_nct_numbers == ["NCT00000002"]


def test_harvester_sorts_by_study_first_posted_desc_and_caps_to_50():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    studies = []
    for i in range(60):
        first_posted = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        studies.append(
            _api_study(
                f"NCT{i:08d}",
                f"AD trial {i}",
                ["Alzheimer Disease"],
                first_posted,
            )
        )

    def get_json(url, params):
        return {"studies": studies}

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    assert len(result.studies) == 50
    first_dates = [
        study["protocolSection"]["statusModule"]["studyFirstPostDateStruct"]["date"]
        for study in result.studies[:3]
    ]
    assert first_dates == ["2026-03-01", "2026-02-28", "2026-02-27"]
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_clinicaltrials_harvester.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.clinicaltrials_harvester'
```

- [ ] **Step 3: Implement condition discovery and raw ClinicalTrials harvester**

Create `src/reports/disease/clinicaltrials_harvester.py`:

```python
from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

import requests
from pydantic import BaseModel, ConfigDict, Field

from .condition_matcher import conditions_full_match, normalize_condition_text
from .models import DiseaseProfile
from .resolver import build_expert_full_match_url


CTGOV_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"


class RawClinicalTrialsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studies: list[dict[str, Any]] = Field(default_factory=list)
    raw_count: int = 0
    rejected_nct_numbers: list[str] = Field(default_factory=list)


@dataclass
class ClinicalTrialsConditionDiscovery:
    get_text: Callable[[str], str] | None = None

    def discover(self, profile: DiseaseProfile) -> DiseaseProfile:
        page_text = self._get_text(profile.expert_topic_url)
        candidates = _extract_condition_candidates(page_text)
        terms = list(profile.condition_terms)
        for candidate in candidates:
            if normalize_condition_text(candidate) in profile.normalized_terms and candidate not in terms:
                terms.append(candidate)
        return profile.model_copy(
            update={
                "condition_terms": terms,
                "expert_full_match_url": build_expert_full_match_url(profile.canonical_condition),
            }
        )

    def _get_text(self, url: str) -> str:
        if self.get_text:
            return self.get_text(url)
        response = requests.get(url, timeout=30, headers={"User-Agent": "Cassandra/1.0"})
        response.raise_for_status()
        return response.text


@dataclass
class ClinicalTrialsDiseaseHarvester:
    get_json: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None
    page_size: int = 100

    def fetch_raw_studies(self, profile: DiseaseProfile, max_records: int = 50) -> RawClinicalTrialsResult:
        fetched: list[dict[str, Any]] = []
        seen: set[str] = set()
        raw_count = 0
        rejected: list[str] = []

        for condition_term in profile.condition_terms:
            page_token = None
            while True:
                params: dict[str, Any] = {
                    "query.cond": condition_term,
                    "pageSize": self.page_size,
                    "format": "json",
                }
                if page_token:
                    params["pageToken"] = page_token
                payload = self._get_json(CTGOV_STUDIES_URL, params)
                studies = payload.get("studies") if isinstance(payload, dict) else []
                if not isinstance(studies, list):
                    studies = []
                raw_count += len(studies)
                for study in studies:
                    if not isinstance(study, dict):
                        continue
                    nct = _extract_nct_number(study)
                    if not nct or nct in seen:
                        continue
                    seen.add(nct)
                    if conditions_full_match(_extract_conditions(study), profile):
                        fetched.append(study)
                    else:
                        rejected.append(nct)
                page_token = payload.get("nextPageToken") if isinstance(payload, dict) else None
                if not page_token:
                    break

        fetched.sort(key=_extract_study_first_posted_sort_key, reverse=True)
        return RawClinicalTrialsResult(
            studies=fetched[:max_records],
            raw_count=raw_count,
            rejected_nct_numbers=rejected,
        )

    def _get_json(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if self.get_json:
            return self.get_json(url, params)
        response = requests.get(url, params=params, timeout=45, headers={"User-Agent": "Cassandra/1.0"})
        response.raise_for_status()
        return response.json()


def _extract_condition_candidates(page_text: str) -> list[str]:
    text = html.unescape(str(page_text or ""))
    candidates: list[str] = []
    for match in re.finditer(r"FullMatch%5B([^%<]+(?:%20[^%<]+)*)%5D", text):
        candidate = html.unescape(match.group(1).replace("%20", " ").replace("%27", "'"))
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    for match in re.finditer(r">\s*([A-Za-z][A-Za-z' -]+Disease)\s*<", text):
        candidate = match.group(1).strip()
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _extract_nct_number(study: dict[str, Any]) -> str:
    protocol = study.get("protocolSection") if isinstance(study.get("protocolSection"), dict) else {}
    identification = protocol.get("identificationModule") if isinstance(protocol.get("identificationModule"), dict) else {}
    return str(study.get("nct_number") or study.get("nct_id") or identification.get("nctId") or "").strip()


def _extract_conditions(study: dict[str, Any]) -> list[str]:
    protocol = study.get("protocolSection") if isinstance(study.get("protocolSection"), dict) else {}
    conditions_module = protocol.get("conditionsModule") if isinstance(protocol.get("conditionsModule"), dict) else {}
    conditions = study.get("conditions") or study.get("condition") or conditions_module.get("conditions") or []
    if isinstance(conditions, str):
        return [part.strip() for part in re.split(r"[,;|]", conditions) if part.strip()]
    if isinstance(conditions, list):
        return [str(item).strip() for item in conditions if str(item).strip()]
    return []


def _extract_study_first_posted_sort_key(study: dict[str, Any]) -> date:
    protocol = study.get("protocolSection") if isinstance(study.get("protocolSection"), dict) else {}
    status_module = protocol.get("statusModule") if isinstance(protocol.get("statusModule"), dict) else {}
    value = (
        study.get("study_first_posted")
        or study.get("studyFirstPostDate")
        or status_module.get("studyFirstPostDateStruct", {}).get("date")
        or ""
    )
    return _parse_date(value) or date.min


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    for pattern in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            parsed = date.fromisoformat(text if pattern == "%Y-%m-%d" else text + "-01" if pattern == "%Y-%m" else text + "-01-01")
            return parsed
        except ValueError:
            continue
    return None
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_clinicaltrials_harvester.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/reports/disease/clinicaltrials_harvester.py tests/reports/disease/test_clinicaltrials_harvester.py
git commit -m "feat: harvest disease-scoped clinical trials"
```

---

### Task 4: Source Normalizer And Relevance Gate

**Files:**
- Create: `src/reports/disease/normalizer.py`
- Create: `src/reports/disease/relevance.py`
- Test: `tests/reports/disease/test_normalizer_and_relevance.py`

- [ ] **Step 1: Write failing normalizer and relevance tests**

Create `tests/reports/disease/test_normalizer_and_relevance.py`:

```python
from datetime import date

from src.reports.disease.normalizer import normalize_trial_payload
from src.reports.disease.relevance import DiseaseRelevanceGate
from src.reports.disease.resolver import DiseaseResolver


def test_normalizer_reads_status_from_nested_clinicaltrials_payload():
    payload = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT06500001", "briefTitle": "AD trial"},
            "statusModule": {
                "overallStatus": "ACTIVE_NOT_RECRUITING",
                "studyFirstPostDateStruct": {"date": "2024-02-10"},
                "lastUpdatePostDateStruct": {"date": "2026-04-01"},
                "startDateStruct": {"date": "2024-06"},
                "primaryCompletionDateStruct": {"date": "2028"},
            },
            "conditionsModule": {"conditions": ["Alzheimer's Disease"]},
            "armsInterventionsModule": {"interventions": [{"name": "Remternetug"}]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Eli Lilly and Company"}},
            "designModule": {"studyType": "INTERVENTIONAL"},
        }
    }

    record = normalize_trial_payload(payload)

    assert record.nct_number == "NCT06500001"
    assert record.status == "ACTIVE_NOT_RECRUITING"
    assert record.conditions == ["Alzheimer's Disease"]
    assert record.interventions == ["Remternetug"]
    assert record.sponsor == "Eli Lilly and Company"
    assert record.study_type == "INTERVENTIONAL"
    assert record.study_first_posted == date(2024, 2, 10)
    assert record.start_date == date(2024, 6, 1)
    assert record.primary_completion_date == date(2028, 1, 1)


def test_normalizer_reads_status_aliases_without_losing_source_field():
    base = {
        "nct_id": "NCT06500002",
        "title": "Flat AD trial",
        "conditions": ["Alzheimer Disease"],
        "interventions": ["Amyloid antibody"],
        "sponsor": "Sponsor A",
        "study_type": "INTERVENTIONAL",
        "study_first_posted": "2026-01-01",
    }

    assert normalize_trial_payload({**base, "status": "RECRUITING"}).status == "RECRUITING"
    assert normalize_trial_payload({**base, "study_status": "COMPLETED"}).status == "COMPLETED"
    assert normalize_trial_payload({**base, "metadata": {"overall_status": "WITHDRAWN"}}).status == "WITHDRAWN"
    assert normalize_trial_payload({**base, "metadata": {"study_status": "SUSPENDED"}}).status == "SUSPENDED"


def test_normalizer_does_not_emit_removed_fields():
    record = normalize_trial_payload(
        {
            "nct_id": "NCT06500003",
            "title": "AD trial",
            "status": "RECRUITING",
            "conditions": ["Alzheimer Disease"],
            "interventions": ["Drug A"],
            "enrollment": "100",
            "primary_endpoint": "ADAS-Cog",
        }
    )

    payload = record.model_dump()

    assert "enrollment" not in payload
    assert "primary_endpoint" not in payload


def test_relevance_gate_keeps_only_condition_full_match_records():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    records = [
        normalize_trial_payload(
            {
                "nct_id": "NCT_KEEP",
                "title": "AD trial",
                "status": "RECRUITING",
                "conditions": ["Alzheimer's Disease"],
                "interventions": ["Donanemab"],
            }
        ),
        normalize_trial_payload(
            {
                "nct_id": "NCT_REJECT",
                "title": "Alzheimer biomarker in Parkinson Disease",
                "status": "RECRUITING",
                "conditions": ["Parkinson Disease"],
                "interventions": ["Levodopa"],
            }
        ),
        normalize_trial_payload(
            {
                "nct_id": "NCT_BROAD",
                "title": "Cognitive behavioral therapy",
                "status": "RECRUITING",
                "conditions": ["Cognitive Impairment"],
                "interventions": ["Cognitive Behavioral Therapy"],
            }
        ),
    ]

    result = DiseaseRelevanceGate().filter_records(records, profile)

    assert [record.nct_number for record in result.retained] == ["NCT_KEEP"]
    assert result.rejected_nct_numbers == ["NCT_REJECT", "NCT_BROAD"]
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_normalizer_and_relevance.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.normalizer'
```

- [ ] **Step 3: Implement normalizer and relevance gate**

Create `src/reports/disease/normalizer.py` with these public functions:

```python
from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from .models import ClinicalTrialRecord


def normalize_trial_payload(payload: dict[str, Any]) -> ClinicalTrialRecord:
    protocol = _dict(payload.get("protocolSection"))
    identification = _dict(protocol.get("identificationModule"))
    status_module = _dict(protocol.get("statusModule"))
    conditions_module = _dict(protocol.get("conditionsModule"))
    interventions_module = _dict(protocol.get("armsInterventionsModule"))
    sponsors_module = _dict(protocol.get("sponsorCollaboratorsModule"))
    design_module = _dict(protocol.get("designModule"))
    metadata = _dict(payload.get("metadata"))

    nct = _first_text(payload, metadata, identification, keys=("nct_number", "nct_id", "nctId"))
    title = _first_text(payload, metadata, identification, keys=("study_title", "title", "briefTitle", "officialTitle"))
    status = _first_text(
        payload,
        metadata,
        status_module,
        keys=("status", "study_status", "overall_status", "overallStatus"),
        default="Unknown",
    )
    conditions = _list_text(
        payload.get("conditions")
        or payload.get("condition")
        or metadata.get("conditions")
        or metadata.get("condition")
        or conditions_module.get("conditions")
    )
    interventions = _extract_interventions(payload, metadata, interventions_module)
    sponsor = _first_text(
        payload,
        metadata,
        _dict(sponsors_module.get("leadSponsor")),
        keys=("sponsor", "lead_sponsor", "trial_sponsor", "sponsor_name", "name"),
        default="Unknown",
    )
    study_type = _first_text(payload, metadata, design_module, keys=("study_type", "studyType"), default="Unknown")

    return ClinicalTrialRecord(
        study_title=title or "Untitled Clinical Trial",
        nct_number=nct,
        status=status,
        conditions=conditions,
        interventions=interventions,
        sponsor=sponsor,
        study_type=study_type,
        study_first_posted=_date_from_sources(payload, metadata, status_module, "study_first_posted", "studyFirstPostDate", "studyFirstPostDateStruct"),
        last_update_posted=_date_from_sources(payload, metadata, status_module, "last_update_posted", "lastUpdatePostDate", "lastUpdatePostDateStruct"),
        start_date=_date_from_sources(payload, metadata, status_module, "start_date", "startDate", "startDateStruct"),
        primary_completion_date=_date_from_sources(payload, metadata, status_module, "primary_completion_date", "primaryCompletionDate", "primaryCompletionDateStruct"),
        completion_date=_date_from_sources(payload, metadata, status_module, "completion_date", "completionDate", "completionDateStruct"),
        source_url=_first_text(payload, metadata, keys=("source_url", "study_url", "url"), default=f"https://clinicaltrials.gov/study/{nct}"),
    )


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_text(*sources: dict[str, Any], keys: Iterable[str], default: str = "") -> str:
    for source in sources:
        for key in keys:
            value = source.get(key)
            if isinstance(value, list):
                value = ", ".join(str(item) for item in value if item)
            text = str(value or "").strip()
            if text:
                return text
    return default


def _list_text(value: Any) -> list[str]:
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            if isinstance(item, dict):
                item = item.get("name") or item.get("label") or item.get("interventionName")
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;|]", value) if part.strip()]
    return []


def _extract_interventions(payload: dict[str, Any], metadata: dict[str, Any], interventions_module: dict[str, Any]) -> list[str]:
    direct = payload.get("interventions") or payload.get("intervention") or metadata.get("interventions") or metadata.get("intervention")
    if direct:
        return _list_text(direct)
    interventions = interventions_module.get("interventions") or []
    return _list_text(interventions)


def _date_from_sources(payload: dict[str, Any], metadata: dict[str, Any], status_module: dict[str, Any], *keys: str) -> date | None:
    for key in keys:
        for source in (payload, metadata, status_module):
            value = source.get(key)
            if isinstance(value, dict):
                value = value.get("date")
            parsed = _parse_date(value)
            if parsed:
                return parsed
    return None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text or text.lower() in {"unknown", "n/a", "none"}:
        return None
    for suffix in ("", "-01", "-01-01"):
        try:
            return date.fromisoformat(text + suffix)
        except ValueError:
            continue
    return None
```

Create `src/reports/disease/relevance.py`:

```python
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from .condition_matcher import conditions_full_match
from .models import ClinicalTrialRecord, DiseaseProfile


class RelevanceGateResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    retained: list[ClinicalTrialRecord] = Field(default_factory=list)
    rejected_nct_numbers: list[str] = Field(default_factory=list)


class DiseaseRelevanceGate:
    def filter_records(self, records: list[ClinicalTrialRecord], profile: DiseaseProfile) -> RelevanceGateResult:
        retained: list[ClinicalTrialRecord] = []
        rejected: list[str] = []
        seen: set[str] = set()
        for record in records:
            if record.nct_number in seen:
                continue
            seen.add(record.nct_number)
            if conditions_full_match(record.conditions, profile):
                retained.append(record)
            else:
                rejected.append(record.nct_number)
        return RelevanceGateResult(retained=retained, rejected_nct_numbers=rejected)
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_normalizer_and_relevance.py -v
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/reports/disease/normalizer.py src/reports/disease/relevance.py tests/reports/disease/test_normalizer_and_relevance.py
git commit -m "feat: normalize and gate clinical trial records"
```

---

### Task 5: Handoff Package Builder

**Files:**
- Create: `src/reports/disease/package_builder.py`
- Test: `tests/reports/disease/test_package_builder.py`

- [ ] **Step 1: Write failing package builder tests**

Create `tests/reports/disease/test_package_builder.py`:

```python
from datetime import date

from src.reports.disease.models import ClinicalTrialRecord
from src.reports.disease.package_builder import DiseaseReportPackageBuilder
from src.reports.disease.resolver import DiseaseResolver


def _record(nct, first_posted):
    return ClinicalTrialRecord(
        study_title=f"Trial {nct}",
        nct_number=nct,
        status="RECRUITING",
        conditions=["Alzheimer Disease"],
        interventions=["Donanemab"],
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=first_posted,
        source_url=f"https://clinicaltrials.gov/study/{nct}",
    )


def test_package_builder_dedupes_sorts_and_records_audit():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    builder = DiseaseReportPackageBuilder()
    records = [
        _record("NCT00000001", date(2025, 1, 1)),
        _record("NCT00000002", date(2026, 1, 1)),
        _record("NCT00000001", date(2025, 1, 1)),
    ]

    package = builder.build(
        disease_profile=profile,
        retained_records=records,
        raw_count=5,
        rejected_nct_numbers=["NCT_BAD_1", "NCT_BAD_2"],
        risk_records=[],
    )

    assert [record.nct_number for record in package.clinical_trials] == ["NCT00000002", "NCT00000001"]
    assert package.source_audit.raw_count == 5
    assert package.source_audit.retained_count == 2
    assert package.source_audit.rejected_count == 2
    assert package.source_audit.rejected_nct_numbers == ["NCT_BAD_1", "NCT_BAD_2"]


def test_package_builder_caps_records_to_requested_limit():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    records = [_record(f"NCT{i:08d}", date(2026, 1, min(i + 1, 28))) for i in range(55)]

    package = DiseaseReportPackageBuilder().build(
        disease_profile=profile,
        retained_records=records,
        raw_count=55,
        rejected_nct_numbers=[],
        risk_records=[],
        max_records=50,
    )

    assert len(package.clinical_trials) == 50
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_package_builder.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.package_builder'
```

- [ ] **Step 3: Implement package builder**

Create `src/reports/disease/package_builder.py`:

```python
from __future__ import annotations

from datetime import date

from .models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)


class DiseaseReportPackageBuilder:
    def build(
        self,
        disease_profile: DiseaseProfile,
        retained_records: list[ClinicalTrialRecord],
        raw_count: int,
        rejected_nct_numbers: list[str],
        risk_records: list[PipelineRiskRecord],
        max_records: int = 50,
    ) -> DiseaseReportPackage:
        records = _dedupe_records(retained_records)
        records.sort(key=lambda record: record.study_first_posted or date.min, reverse=True)
        records = records[:max_records]
        audit = SourceAudit(
            topic_url=disease_profile.expert_topic_url,
            full_match_url=disease_profile.expert_full_match_url,
            selected_condition_terms=disease_profile.condition_terms,
            raw_count=int(raw_count),
            retained_count=len(records),
            rejected_count=len(rejected_nct_numbers),
            rejected_nct_numbers=list(rejected_nct_numbers),
        )
        return DiseaseReportPackage(
            disease_profile=disease_profile,
            clinical_trials=records,
            risk_records=risk_records,
            source_audit=audit,
        )


def _dedupe_records(records: list[ClinicalTrialRecord]) -> list[ClinicalTrialRecord]:
    seen: set[str] = set()
    result: list[ClinicalTrialRecord] = []
    for record in records:
        if record.nct_number in seen:
            continue
        seen.add(record.nct_number)
        result.append(record)
    return result
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_package_builder.py -v
```

Expected:

```text
2 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/reports/disease/package_builder.py tests/reports/disease/test_package_builder.py
git commit -m "feat: build disease report handoff package"
```

---

### Task 6: Deterministic Timeline And Competition Risk Engine

**Files:**
- Create: `src/reports/disease/risk_engine.py`
- Test: `tests/reports/disease/test_risk_engine.py`

- [ ] **Step 1: Write failing risk engine tests**

Create `tests/reports/disease/test_risk_engine.py`:

```python
from datetime import date

from src.reports.disease.models import ClinicalTrialRecord
from src.reports.disease.risk_engine import RuleBasedRiskEngine, categorize_interventions


def _trial(nct, status, first_posted, interventions):
    return ClinicalTrialRecord(
        study_title=f"Trial {nct}",
        nct_number=nct,
        status=status,
        conditions=["Alzheimer Disease"],
        interventions=interventions,
        sponsor="Sponsor A",
        study_type="INTERVENTIONAL",
        study_first_posted=first_posted,
        source_url=f"https://clinicaltrials.gov/study/{nct}",
    )


def test_categorize_interventions_uses_rule_based_taxonomy():
    assert categorize_interventions(["anti-amyloid monoclonal antibody"]) == "amyloid antibody"
    assert categorize_interventions(["tau aggregation inhibitor"]) == "tau therapy"
    assert categorize_interventions(["oral small molecule BACE inhibitor"]) == "small molecule"
    assert categorize_interventions(["deep brain stimulation device"]) == "device"
    assert categorize_interventions(["PET imaging diagnostic"]) == "diagnostic or imaging"
    assert categorize_interventions(["caregiver behavioral intervention"]) == "behavioral intervention"
    assert categorize_interventions([""]) == ""


def test_timeline_signal_high_for_old_non_terminal_trial():
    engine = RuleBasedRiskEngine(current_date=date(2026, 4, 27))
    records = [_trial("NCT_OLD", "RECRUITING", date(2018, 4, 10), ["Drug A"])]

    risk_records = engine.build(records, disease_name="Alzheimer Disease")

    assert risk_records[0].timeline_signal == "High"
    assert "Study first posted 2018-04-10; status RECRUITING; age 8.0 years." in risk_records[0].timeline_evidence


def test_timeline_signal_low_for_completed_or_recent_trial():
    engine = RuleBasedRiskEngine(current_date=date(2026, 4, 27))
    records = [
        _trial("NCT_DONE", "COMPLETED", date(2019, 1, 1), ["Drug A"]),
        _trial("NCT_RECENT", "RECRUITING", date(2025, 8, 1), ["Drug B"]),
    ]

    risk_records = engine.build(records, disease_name="Alzheimer Disease")

    assert [risk.timeline_signal for risk in risk_records] == ["Low", "Low"]


def test_timeline_signal_data_insufficient_when_first_posted_missing():
    engine = RuleBasedRiskEngine(current_date=date(2026, 4, 27))
    records = [_trial("NCT_MISSING", "RECRUITING", None, ["Drug A"])]

    risk_records = engine.build(records, disease_name="Alzheimer Disease")

    assert risk_records[0].timeline_signal == "Data insufficient"
    assert "Study first posted missing" in risk_records[0].timeline_evidence


def test_competition_signal_counts_category_crowding():
    engine = RuleBasedRiskEngine(current_date=date(2026, 4, 27))
    records = [
        _trial(f"NCT_A{i}", "RECRUITING", date(2025, 1, 1), ["anti-amyloid monoclonal antibody"])
        for i in range(8)
    ]
    records.append(_trial("NCT_OTHER", "RECRUITING", date(2025, 1, 1), ["cell therapy"]))

    risk_records = engine.build(records, disease_name="Alzheimer Disease")
    amyloid_records = [risk for risk in risk_records if risk.intervention_category == "amyloid antibody"]
    cell_records = [risk for risk in risk_records if risk.intervention_category == "cell therapy"]

    assert all(risk.competition_signal == "High" for risk in amyloid_records)
    assert all("8 retained Alzheimer Disease studies share intervention category amyloid antibody." in risk.competition_evidence for risk in amyloid_records)
    assert cell_records[0].competition_signal == "Low"
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_risk_engine.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.risk_engine'
```

- [ ] **Step 3: Implement deterministic risk engine**

Create `src/reports/disease/risk_engine.py`:

```python
from __future__ import annotations

from collections import Counter
from datetime import date

from .models import ClinicalTrialRecord, PipelineRiskRecord


NON_TERMINAL_STATUSES = {
    "ACTIVE_NOT_RECRUITING",
    "ENROLLING_BY_INVITATION",
    "NOT_YET_RECRUITING",
    "RECRUITING",
    "UNKNOWN",
}
TERMINAL_STATUSES = {"COMPLETED", "TERMINATED", "SUSPENDED", "WITHDRAWN"}


def categorize_interventions(interventions: list[str]) -> str:
    text = " ".join(str(item or "").lower() for item in interventions)
    if not text.strip():
        return ""
    if "amyloid" in text or "abeta" in text or "a beta" in text:
        if "antibody" in text or "monoclonal" in text or "mab" in text:
            return "amyloid antibody"
    if "tau" in text:
        return "tau therapy"
    if "cell" in text or "stem cell" in text:
        return "cell therapy"
    if "device" in text or "stimulation" in text or "wearable" in text:
        return "device"
    if "diagnostic" in text or "imaging" in text or "pet" in text or "mri" in text or "biomarker" in text:
        return "diagnostic or imaging"
    if "behavioral" in text or "cognitive behavioral" in text or "psychotherapy" in text:
        return "behavioral intervention"
    if "care" in text or "caregiver" in text or "telehealth" in text:
        return "care delivery"
    if "small molecule" in text or "inhibitor" in text or "oral" in text:
        return "small molecule"
    return "other"


class RuleBasedRiskEngine:
    def __init__(self, current_date: date | None = None):
        self.current_date = current_date or date.today()

    def build(self, records: list[ClinicalTrialRecord], disease_name: str) -> list[PipelineRiskRecord]:
        categories = {record.nct_number: categorize_interventions(record.interventions) for record in records}
        counts = Counter(category for category in categories.values() if category)
        return [
            self._risk_record(record, disease_name=disease_name, category=categories[record.nct_number], category_count=counts.get(categories[record.nct_number], 0))
            for record in records
        ]

    def _risk_record(
        self,
        record: ClinicalTrialRecord,
        disease_name: str,
        category: str,
        category_count: int,
    ) -> PipelineRiskRecord:
        timeline_signal, timeline_evidence = self._timeline_signal(record)
        competition_signal, competition_evidence = self._competition_signal(disease_name, category, category_count)
        return PipelineRiskRecord(
            nct_number=record.nct_number,
            study_title=record.study_title,
            sponsor=record.sponsor,
            status=record.status,
            intervention_category=category,
            timeline_signal=timeline_signal,
            timeline_evidence=timeline_evidence,
            competition_signal=competition_signal,
            competition_evidence=competition_evidence,
        )

    def _timeline_signal(self, record: ClinicalTrialRecord) -> tuple[str, str]:
        if not record.study_first_posted:
            return "Data insufficient", f"Study first posted missing; status {record.status or 'Unknown'}."
        age_years = round((self.current_date - record.study_first_posted).days / 365.25, 1)
        status = (record.status or "Unknown").upper()
        evidence = f"Study first posted {record.study_first_posted.isoformat()}; status {status}; age {age_years:.1f} years."
        if status in TERMINAL_STATUSES:
            return "Low", evidence
        if age_years > 5 and status in NON_TERMINAL_STATUSES:
            return "High", evidence
        if 2 <= age_years <= 5 and status in NON_TERMINAL_STATUSES:
            return "Medium", evidence
        return "Low", evidence

    def _competition_signal(self, disease_name: str, category: str, category_count: int) -> tuple[str, str]:
        if not category:
            return "Data insufficient", "Intervention text could not be categorized."
        evidence = f"{category_count} retained {disease_name} studies share intervention category {category}."
        if category_count >= 8:
            return "High", evidence
        if 3 <= category_count <= 7:
            return "Medium", evidence
        return "Low", evidence
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_risk_engine.py -v
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/reports/disease/risk_engine.py tests/reports/disease/test_risk_engine.py
git commit -m "feat: add deterministic disease pipeline risk engine"
```

---

### Task 7: Disease Report IR Builder

**Files:**
- Create: `src/reports/disease/ir_builder.py`
- Test: `tests/reports/disease/test_ir_builder.py`

- [ ] **Step 1: Write failing IR builder tests**

Create `tests/reports/disease/test_ir_builder.py`:

```python
from datetime import date

from src.reports.disease.ir_builder import DiseaseReportIRBuilder, LANDSCAPE_COLUMNS
from src.reports.disease.models import ClinicalTrialRecord, PipelineRiskRecord
from src.reports.disease.package_builder import DiseaseReportPackageBuilder
from src.reports.disease.resolver import DiseaseResolver


def _package():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    trial = ClinicalTrialRecord(
        study_title="A Study of Donanemab in Alzheimer Disease",
        nct_number="NCT00000001",
        status="RECRUITING",
        conditions=["Alzheimer Disease"],
        interventions=["Donanemab"],
        sponsor="Eli Lilly and Company",
        study_type="INTERVENTIONAL",
        study_first_posted=date(2026, 4, 20),
        source_url="https://clinicaltrials.gov/study/NCT00000001",
    )
    risk = PipelineRiskRecord(
        nct_number="NCT00000001",
        study_title=trial.study_title,
        sponsor=trial.sponsor,
        status=trial.status,
        intervention_category="amyloid antibody",
        timeline_signal="Low",
        timeline_evidence="Study first posted 2026-04-20; status RECRUITING; age 0.0 years.",
        competition_signal="High",
        competition_evidence="8 retained Alzheimer Disease studies share intervention category amyloid antibody.",
    )
    return DiseaseReportPackageBuilder().build(
        disease_profile=profile,
        retained_records=[trial],
        raw_count=1,
        rejected_nct_numbers=[],
        risk_records=[risk],
    )


def _table_headers(table_block):
    return [
        cell["blocks"][0]["inlines"][0]["text"]
        for cell in table_block["rows"][0]["cells"]
    ]


def test_ir_has_exact_three_approved_chapters():
    ir = DiseaseReportIRBuilder().build(_package())

    titles = [chapter["title"] for chapter in ir["chapters"]]

    assert titles == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
    ]


def test_landscape_table_uses_exact_approved_columns():
    ir = DiseaseReportIRBuilder().build(_package())
    landscape = ir["chapters"][1]
    table = next(block for block in landscape["blocks"] if block["type"] == "table")

    assert _table_headers(table) == LANDSCAPE_COLUMNS
    assert table["metadata"]["layout"] == "wide-clinical-trial-table"
    assert len(table["colgroup"]) == 7


def test_ir_excludes_removed_sections_and_removed_fields():
    ir = DiseaseReportIRBuilder().build(_package())
    rendered_text = str(ir)

    assert "Drug Pipeline" not in rendered_text
    assert "Trial Landscape" not in rendered_text
    assert "Company Technical Route Analysis" not in rendered_text
    assert "Literature Review" not in rendered_text
    assert "CNS Benchmark" not in rendered_text
    assert "Data Quality" not in rendered_text
    assert "Enrollment" not in rendered_text
    assert "Primary Endpoint" not in rendered_text
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_ir_builder.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.ir_builder'
```

- [ ] **Step 3: Implement report IR builder**

Create `src/reports/disease/ir_builder.py`:

```python
from __future__ import annotations

from .models import ClinicalTrialRecord, DiseaseReportPackage, PipelineRiskRecord


LANDSCAPE_COLUMNS = [
    "Study Title",
    "NCT Number",
    "Status",
    "Conditions",
    "Interventions",
    "Sponsor",
    "Study Type",
]

RISK_COLUMNS = [
    "Study Title",
    "NCT Number",
    "Status",
    "Timeline Signal",
    "Timeline Evidence",
    "Competition Signal",
    "Competition Evidence",
]


class DiseaseReportIRBuilder:
    def build(self, package: DiseaseReportPackage) -> dict:
        disease = package.disease_profile.disease_name
        return {
            "title": f"{disease} Disease Pipeline Report",
            "subtitle": "ClinicalTrials.gov disease-scoped intelligence",
            "query": package.disease_profile.query,
            "metadata": {
                "reportType": "disease_pipeline",
                "disease": disease,
                "generatedAt": package.generated_at.isoformat(),
                "sourceAudit": package.source_audit.model_dump(mode="json"),
                "layout": {"wideTables": ["clinical-trial-landscape", "pipeline-risk"]},
            },
            "chapters": [
                _chapter("executive-summary", "Executive Summary", 1, self._summary_blocks(package)),
                _chapter("clinical-trial-pipeline-landscape", "Clinical Trial And Pipeline Landscape", 2, [self._landscape_table(package.clinical_trials)]),
                _chapter("pipeline-timeline-competition-risk", "Pipeline Timeline And Competition Risk", 3, [self._risk_table(package.risk_records)]),
            ],
        }

    def _summary_blocks(self, package: DiseaseReportPackage) -> list[dict]:
        disease = package.disease_profile.disease_name
        retained = len(package.clinical_trials)
        rejected = package.source_audit.rejected_count
        latest = package.clinical_trials[0].study_first_posted.isoformat() if package.clinical_trials and package.clinical_trials[0].study_first_posted else "not available"
        return [
            {
                "type": "paragraph",
                "inlines": [
                    {
                        "text": (
                            f"This report covers {retained} ClinicalTrials.gov studies whose Conditions field full-matches "
                            f"{disease}. {rejected} fetched studies were excluded before handoff because their Conditions "
                            f"did not match the target disease. The latest retained Study First Posted date is {latest}."
                        )
                    }
                ],
            }
        ]

    def _landscape_table(self, records: list[ClinicalTrialRecord]) -> dict:
        rows = [_header_row(LANDSCAPE_COLUMNS)]
        for record in records:
            rows.append(
                _row(
                    [
                        record.study_title,
                        record.nct_number,
                        record.status,
                        "; ".join(record.conditions),
                        "; ".join(record.interventions),
                        record.sponsor,
                        record.study_type,
                    ]
                )
            )
        return {
            "type": "table",
            "caption": "ClinicalTrials.gov records retained by disease condition full-match",
            "colgroup": [
                {"key": "study_title", "width": "28%"},
                {"key": "nct_number", "width": "10%"},
                {"key": "status", "width": "11%"},
                {"key": "conditions", "width": "14%"},
                {"key": "interventions", "width": "17%"},
                {"key": "sponsor", "width": "13%"},
                {"key": "study_type", "width": "7%"},
            ],
            "rows": rows,
            "metadata": {"layout": "wide-clinical-trial-table", "className": "clinical-trial-landscape"},
        }

    def _risk_table(self, risks: list[PipelineRiskRecord]) -> dict:
        rows = [_header_row(RISK_COLUMNS)]
        for risk in risks:
            rows.append(
                _row(
                    [
                        risk.study_title,
                        risk.nct_number,
                        risk.status,
                        risk.timeline_signal,
                        risk.timeline_evidence,
                        risk.competition_signal,
                        risk.competition_evidence,
                    ]
                )
            )
        return {
            "type": "table",
            "caption": "Rule-based timeline length and market crowding signals",
            "colgroup": [
                {"key": "study_title", "width": "24%"},
                {"key": "nct_number", "width": "9%"},
                {"key": "status", "width": "10%"},
                {"key": "timeline_signal", "width": "9%"},
                {"key": "timeline_evidence", "width": "20%"},
                {"key": "competition_signal", "width": "9%"},
                {"key": "competition_evidence", "width": "19%"},
            ],
            "rows": rows,
            "metadata": {"layout": "wide-risk-table", "className": "pipeline-risk"},
        }


def _chapter(slug: str, title: str, order: int, blocks: list[dict]) -> dict:
    return {"chapterId": slug, "id": slug, "slug": slug, "anchor": slug, "title": title, "order": order, "blocks": blocks}


def _header_row(values: list[str]) -> dict:
    return {"cells": [_cell(value, header=True) for value in values]}


def _row(values: list[str]) -> dict:
    return {"cells": [_cell(value) for value in values]}


def _cell(value: str, header: bool = False) -> dict:
    return {
        "header": header,
        "blocks": [{"type": "paragraph", "inlines": [{"text": str(value or "")}]}],
    }
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_ir_builder.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/reports/disease/ir_builder.py tests/reports/disease/test_ir_builder.py
git commit -m "feat: build disease report IR"
```

---

### Task 8: Renderer Adapter And Wide Table Rendering

**Files:**
- Create: `src/reports/disease/renderer_adapter.py`
- Modify: `src/engines/report_engine/renderers/html_renderer.py`
- Test: `tests/reports/disease/test_renderer_adapter.py`

- [ ] **Step 1: Write failing renderer tests**

Create `tests/reports/disease/test_renderer_adapter.py`:

```python
from pathlib import Path

from src.engines.report_engine.renderers.html_renderer import HTMLRenderer
from src.reports.disease.renderer_adapter import DiseaseReportRendererAdapter, sanitize_report_filename


class FakeMarkdownRenderer:
    def __init__(self):
        self.ir = None

    def render(self, document_ir, ir_file_path=None):
        self.ir = document_ir
        return "# Fake Markdown"


class FakeHTMLRenderer:
    def __init__(self):
        self.ir = None

    def render(self, document_ir, ir_file_path=None):
        self.ir = document_ir
        return "<html>Fake</html>"


class FakePDFRenderer:
    def __init__(self):
        self.ir = None

    def render_to_pdf(self, document_ir, output_path, optimize_layout=True, ir_file_path=None):
        self.ir = document_ir
        Path(output_path).write_bytes(b"%PDF-fake")
        return Path(output_path)


def test_sanitize_report_filename_is_filesystem_safe():
    assert sanitize_report_filename("conduct a survey on Alzheimer disease") == "conduct_a_survey_on_Alzheimer_disease"
    assert sanitize_report_filename("a/b:c*d?e") == "a_b_c_d_e"


def test_renderer_adapter_writes_all_artifacts_from_same_ir(tmp_path):
    md = FakeMarkdownRenderer()
    html = FakeHTMLRenderer()
    pdf = FakePDFRenderer()
    ir = {"title": "Alzheimer Disease Report", "chapters": [], "metadata": {}}

    artifacts = DiseaseReportRendererAdapter(
        markdown_renderer=md,
        html_renderer=html,
        pdf_renderer=pdf,
    ).render_all(ir, output_dir=tmp_path, project_name="Alzheimer Disease")

    assert artifacts.markdown_content == "# Fake Markdown"
    assert Path(artifacts.markdown_path).exists()
    assert Path(artifacts.html_path).exists()
    assert Path(artifacts.pdf_path).exists()
    assert Path(artifacts.ir_path).exists()
    assert md.ir == ir
    assert html.ir == ir
    assert pdf.ir == ir


def test_html_renderer_respects_table_colgroup_and_wide_class():
    ir = {
        "title": "Report",
        "metadata": {},
        "chapters": [
            {
                "title": "Clinical Trial And Pipeline Landscape",
                "blocks": [
                    {
                        "type": "table",
                        "colgroup": [{"width": "70%"}, {"width": "30%"}],
                        "metadata": {"className": "clinical-trial-landscape"},
                        "rows": [
                            {
                                "cells": [
                                    {"header": True, "blocks": [{"type": "paragraph", "inlines": [{"text": "Study Title"}]}]},
                                    {"header": True, "blocks": [{"type": "paragraph", "inlines": [{"text": "Status"}]}]},
                                ]
                            }
                        ],
                    }
                ],
            }
        ],
    }

    html = HTMLRenderer().render(ir)

    assert '<col style="width: 70%">' in html
    assert 'clinical-trial-landscape' in html
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_renderer_adapter.py -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.renderer_adapter'
```

- [ ] **Step 3: Implement renderer adapter**

Create `src/reports/disease/renderer_adapter.py`:

```python
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from src.engines.report_engine.renderers.html_renderer import HTMLRenderer
from src.engines.report_engine.renderers.markdown_renderer import MarkdownRenderer
from src.engines.report_engine.renderers.pdf_renderer import PDFRenderer

from .models import DiseaseReportArtifacts


def sanitize_report_filename(filename: str, max_length: int = 80) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", str(filename or ""))
    cleaned = cleaned.replace(" ", "_").strip("_. ")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        cleaned = "disease_report"
    return cleaned[:max_length].rstrip("_. ")


class DiseaseReportRendererAdapter:
    def __init__(
        self,
        markdown_renderer: Any | None = None,
        html_renderer: Any | None = None,
        pdf_renderer: Any | None = None,
    ):
        self.markdown_renderer = markdown_renderer or MarkdownRenderer()
        self.html_renderer = html_renderer or HTMLRenderer()
        self.pdf_renderer = pdf_renderer or PDFRenderer()

    def render_all(self, document_ir: dict[str, Any], output_dir: str | Path, project_name: str) -> DiseaseReportArtifacts:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        stem = f"{sanitize_report_filename(project_name)}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        ir_path = output_path / f"{stem}.ir.json"
        markdown_path = output_path / f"{stem}.md"
        html_path = output_path / f"{stem}.html"
        pdf_path = output_path / f"{stem}.pdf"

        ir_path.write_text(json.dumps(document_ir, ensure_ascii=False, indent=2), encoding="utf-8")
        markdown_content = self.markdown_renderer.render(copy.deepcopy(document_ir), ir_file_path=str(ir_path))
        html_content = self.html_renderer.render(copy.deepcopy(document_ir), ir_file_path=str(ir_path))
        markdown_path.write_text(markdown_content, encoding="utf-8")
        html_path.write_text(html_content, encoding="utf-8")
        rendered_pdf_path = self.pdf_renderer.render_to_pdf(copy.deepcopy(document_ir), pdf_path, optimize_layout=True, ir_file_path=str(ir_path))

        return DiseaseReportArtifacts(
            markdown_content=markdown_content,
            markdown_path=str(markdown_path),
            html_path=str(html_path),
            pdf_path=str(rendered_pdf_path),
            ir_path=str(ir_path),
        )
```

- [ ] **Step 4: Modify HTML table rendering to respect layout hints**

In `src/engines/report_engine/renderers/html_renderer.py`, update `_render_table` so it reads `block["colgroup"]` and `block["metadata"]["className"]`.

Replace the final `return` line inside `_render_table` with:

```python
        metadata = block.get("metadata") if isinstance(block.get("metadata"), dict) else {}
        class_name = str(metadata.get("className") or metadata.get("class") or "").strip()
        table_class = f' class="{self._escape_html(class_name)}"' if class_name else ""
        colgroup_html = ""
        colgroup = block.get("colgroup") or []
        if isinstance(colgroup, list) and colgroup:
            cols = []
            for col in colgroup:
                width = ""
                if isinstance(col, dict):
                    width = str(col.get("width") or "").strip()
                style = f' style="width: {self._escape_html(width)}"' if width else ""
                cols.append(f"<col{style}>")
            colgroup_html = f"<colgroup>{''.join(cols)}</colgroup>"
        wrap_class = "table-wrap table-wrap--wide" if class_name else "table-wrap"
        return f'<div class="{wrap_class}"><table{table_class}>{colgroup_html}{caption_html}<tbody>{rows_html}</tbody></table></div>'
```

- [ ] **Step 5: Run renderer tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_renderer_adapter.py -v
```

Expected:

```text
3 passed
```

- [ ] **Step 6: Commit**

```powershell
git add src/reports/disease/renderer_adapter.py src/engines/report_engine/renderers/html_renderer.py tests/reports/disease/test_renderer_adapter.py
git commit -m "feat: render disease report artifacts from one IR"
```

---

### Task 9: Disease Report Orchestrator With Bounded Parallel Stages

**Files:**
- Create: `src/reports/disease/orchestrator.py`
- Create: `src/reports/disease/company_routes.py`
- Modify: `src/reports/disease/__init__.py`
- Test: `tests/reports/disease/test_workflow_service.py`

- [ ] **Step 1: Write failing orchestrator tests**

Create the orchestrator-focused part of `tests/reports/disease/test_workflow_service.py`:

```python
from pathlib import Path

from src.reports.disease.orchestrator import DiseaseReportOrchestrator


def _study(nct, condition, status="RECRUITING"):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": f"Trial {nct}"},
            "statusModule": {
                "overallStatus": status,
                "studyFirstPostDateStruct": {"date": "2026-04-20"},
            },
            "conditionsModule": {"conditions": [condition]},
            "armsInterventionsModule": {"interventions": [{"name": "anti-amyloid monoclonal antibody"}]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Sponsor A"}},
            "designModule": {"studyType": "INTERVENTIONAL"},
        }
    }


class FakeRendererAdapter:
    def render_all(self, document_ir, output_dir, project_name):
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        md = output / "report.md"
        html = output / "report.html"
        pdf = output / "report.pdf"
        ir = output / "report.ir.json"
        md.write_text("# Disease Report", encoding="utf-8")
        html.write_text("<html></html>", encoding="utf-8")
        pdf.write_bytes(b"%PDF-fake")
        ir.write_text("{}", encoding="utf-8")
        from src.reports.disease.models import DiseaseReportArtifacts

        return DiseaseReportArtifacts(
            markdown_content="# Disease Report",
            markdown_path=str(md),
            html_path=str(html),
            pdf_path=str(pdf),
            ir_path=str(ir),
        )


def test_orchestrator_run_returns_app_state_keys(tmp_path):
    def get_json(url, params):
        return {
            "studies": [
                _study("NCT_KEEP", "Alzheimer Disease"),
                _study("NCT_REJECT", "Parkinson Disease"),
            ]
        }

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=FakeRendererAdapter(),
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run("Alzheimer disease pipeline", output_dir=tmp_path)

    assert state["status"] == "writer_complete"
    assert state["final_report"] == "# Disease Report"
    assert state["final_report_path"].endswith("report.md")
    assert state["final_report_html_path"].endswith("report.html")
    assert state["final_report_pdf_path"].endswith("report.pdf")
    assert state["clinical_data"]["trial_records"] == 1
    assert len(state["harvested_data"]) == 1
    assert state["disease_areas"] == ["Alzheimer Disease"]
    assert "disease_report_package" in state


def test_orchestrator_stream_yields_harvest_handoff_writer_nodes(tmp_path):
    def get_json(url, params):
        return {"studies": [_study("NCT_KEEP", "Alzheimer Disease")]}

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=FakeRendererAdapter(),
        current_date_for_tests="2026-04-27",
    )

    events = list(orchestrator.stream("Alzheimer disease", output_dir=tmp_path))

    assert [name for name, state in events] == ["harvester", "extension_handoff", "writer"]
    assert events[-1][1]["final_report"] == "# Disease Report"
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_workflow_service.py::test_orchestrator_run_returns_app_state_keys tests/reports/disease/test_workflow_service.py::test_orchestrator_stream_yields_harvest_handoff_writer_nodes -v
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.orchestrator'
```

- [ ] **Step 3: Implement dormant company route interface**

Create `src/reports/disease/company_routes.py`:

```python
from __future__ import annotations

from typing import Protocol

from .models import DiseaseReportPackage


class CompanyRouteProvider(Protocol):
    def enrich(self, package: DiseaseReportPackage) -> DiseaseReportPackage:
        pass


class NoopCompanyRouteProvider:
    def enrich(self, package: DiseaseReportPackage) -> DiseaseReportPackage:
        return package
```

- [ ] **Step 4: Implement orchestrator**

Create `src/reports/disease/orchestrator.py`:

```python
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Any, Callable, Iterator

from .clinicaltrials_harvester import ClinicalTrialsConditionDiscovery, ClinicalTrialsDiseaseHarvester
from .company_routes import NoopCompanyRouteProvider
from .ir_builder import DiseaseReportIRBuilder
from .normalizer import normalize_trial_payload
from .package_builder import DiseaseReportPackageBuilder
from .relevance import DiseaseRelevanceGate
from .renderer_adapter import DiseaseReportRendererAdapter
from .resolver import DiseaseResolver
from .risk_engine import RuleBasedRiskEngine


class DiseaseReportOrchestrator:
    def __init__(
        self,
        clinicaltrials_get_json: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        clinicaltrials_get_text: Callable[[str], str] | None = None,
        renderer_adapter: Any | None = None,
        max_workers: int = 4,
        current_date_for_tests: str | None = None,
        company_route_provider: Any | None = None,
    ):
        self.resolver = DiseaseResolver()
        self.discovery = ClinicalTrialsConditionDiscovery(get_text=clinicaltrials_get_text)
        self.harvester = ClinicalTrialsDiseaseHarvester(get_json=clinicaltrials_get_json)
        self.relevance_gate = DiseaseRelevanceGate()
        self.package_builder = DiseaseReportPackageBuilder()
        self.ir_builder = DiseaseReportIRBuilder()
        self.renderer_adapter = renderer_adapter or DiseaseReportRendererAdapter()
        self.max_workers = max_workers
        current_date = date.fromisoformat(current_date_for_tests) if current_date_for_tests else None
        self.risk_engine = RuleBasedRiskEngine(current_date=current_date)
        self.company_route_provider = company_route_provider or NoopCompanyRouteProvider()

    def run(self, user_query: str, output_dir: str = "final_reports", max_trials: int = 50) -> dict[str, Any]:
        final_state = None
        for _node, state in self.stream(user_query=user_query, output_dir=output_dir, max_trials=max_trials):
            final_state = state
        return final_state or {"status": "failed", "errors": ["Disease report pipeline produced no state."]}

    def stream(self, user_query: str, output_dir: str = "final_reports", max_trials: int = 50) -> Iterator[tuple[str, dict[str, Any]]]:
        profile = self.discovery.discover(self.resolver.resolve(user_query))
        raw = self.harvester.fetch_raw_studies(profile, max_records=max_trials)

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            normalized = list(executor.map(normalize_trial_payload, raw.studies))

        relevance = self.relevance_gate.filter_records(normalized, profile)
        harvest_state = self._state_after_harvest(user_query, profile, relevance.retained, raw.raw_count, raw.rejected_nct_numbers + relevance.rejected_nct_numbers)
        yield "harvester", harvest_state

        risks = self.risk_engine.build(relevance.retained, disease_name=profile.disease_name)
        package = self.package_builder.build(
            disease_profile=profile,
            retained_records=relevance.retained,
            raw_count=raw.raw_count,
            rejected_nct_numbers=raw.rejected_nct_numbers + relevance.rejected_nct_numbers,
            risk_records=risks,
            max_records=max_trials,
        )
        package = self.company_route_provider.enrich(package)
        handoff_state = dict(harvest_state)
        handoff_state.update(
            {
                "status": "handoff_complete",
                "disease_report_package": package.model_dump(mode="json"),
                "analysis_focus": "DISEASE_REPORT_PIPELINE",
            }
        )
        yield "extension_handoff", handoff_state

        document_ir = self.ir_builder.build(package)
        artifacts = self.renderer_adapter.render_all(document_ir, output_dir=output_dir, project_name=profile.disease_name)
        final_state = dict(handoff_state)
        final_state.update(
            {
                "status": "writer_complete",
                "final_report": artifacts.markdown_content,
                "final_report_markdown": artifacts.markdown_content,
                "final_report_path": artifacts.markdown_path,
                "final_report_html_path": artifacts.html_path,
                "final_report_pdf_path": artifacts.pdf_path,
                "final_report_ir_path": artifacts.ir_path,
                "report_ir": document_ir,
            }
        )
        yield "writer", final_state

    def _state_after_harvest(self, user_query: str, profile, records, raw_count: int, rejected_nct_numbers: list[str]) -> dict[str, Any]:
        harvested_data = [
            {
                "source": "ClinicalTrials.gov",
                "title": record.study_title,
                "nct_id": record.nct_number,
                "nct_number": record.nct_number,
                "status": record.status,
                "conditions": record.conditions,
                "interventions": record.interventions,
                "sponsor": record.sponsor,
                "study_type": record.study_type,
                "url": record.source_url,
                "metadata": record.model_dump(mode="json"),
            }
            for record in records
        ]
        return {
            "user_query": user_query,
            "project_name": profile.disease_name,
            "status": "harvest_complete",
            "analysis_focus": "DISEASE_REPORT_PIPELINE",
            "harvested_data": harvested_data,
            "disease_areas": [profile.disease_name],
            "clinical_data": {"trial_records": len(records), "raw_records": raw_count, "rejected_records": len(rejected_nct_numbers)},
            "evidence_stats": {"clinical_trial_records": len(records)},
            "extension_payloads": {},
            "errors": [],
        }
```

- [ ] **Step 5: Export orchestrator**

Update `src/reports/disease/__init__.py`:

```python
"""Single disease report pipeline."""

from .models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportArtifacts,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)
from .orchestrator import DiseaseReportOrchestrator

__all__ = [
    "ClinicalTrialRecord",
    "DiseaseProfile",
    "DiseaseReportArtifacts",
    "DiseaseReportPackage",
    "DiseaseReportOrchestrator",
    "PipelineRiskRecord",
    "SourceAudit",
]
```

- [ ] **Step 6: Run orchestrator tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_workflow_service.py::test_orchestrator_run_returns_app_state_keys tests/reports/disease/test_workflow_service.py::test_orchestrator_stream_yields_harvest_handoff_writer_nodes -v
```

Expected:

```text
2 passed
```

- [ ] **Step 7: Commit**

```powershell
git add src/reports/disease/orchestrator.py src/reports/disease/company_routes.py src/reports/disease/__init__.py tests/reports/disease/test_workflow_service.py
git commit -m "feat: orchestrate single disease report pipeline"
```

---

### Task 10: WorkflowService Integration

**Files:**
- Modify: `src/services/workflow_service.py`
- Test: `tests/reports/disease/test_workflow_service.py`

- [ ] **Step 1: Extend WorkflowService tests**

Append to `tests/reports/disease/test_workflow_service.py`:

```python
from src.services.workflow_service import WorkflowService


def test_workflow_service_run_uses_disease_orchestrator(tmp_path):
    def factory():
        return DiseaseReportOrchestrator(
            clinicaltrials_get_json=lambda url, params: {"studies": [_study("NCT_KEEP", "Alzheimer Disease")]},
            clinicaltrials_get_text=lambda url: "",
            renderer_adapter=FakeRendererAdapter(),
            current_date_for_tests="2026-04-27",
        )

    service = WorkflowService(orchestrator_factory=factory, output_dir=tmp_path)

    state = service.run("Alzheimer disease")

    assert state["status"] == "writer_complete"
    assert state["final_report"] == "# Disease Report"


def test_workflow_service_stream_uses_three_public_progress_nodes(tmp_path):
    def factory():
        return DiseaseReportOrchestrator(
            clinicaltrials_get_json=lambda url, params: {"studies": [_study("NCT_KEEP", "Alzheimer Disease")]},
            clinicaltrials_get_text=lambda url: "",
            renderer_adapter=FakeRendererAdapter(),
            current_date_for_tests="2026-04-27",
        )

    service = WorkflowService(orchestrator_factory=factory, output_dir=tmp_path)

    events = list(service.stream("Alzheimer disease"))

    assert [name for name, state in events] == ["harvester", "extension_handoff", "writer"]
    assert events[-1][1]["final_report"] == "# Disease Report"
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
pytest tests/reports/disease/test_workflow_service.py -v
```

Expected:

```text
TypeError: WorkflowService() takes no arguments
```

- [ ] **Step 3: Replace WorkflowService graph facade with orchestrator facade**

Replace `src/services/workflow_service.py` with:

```python
"""Workflow execution facade for the single disease report pipeline."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Generator, Optional, Tuple

from src.reports.disease import DiseaseReportOrchestrator


class WorkflowService:
    """Application-facing service for disease report generation."""

    def __init__(
        self,
        orchestrator_factory: Callable[[], DiseaseReportOrchestrator] | None = None,
        output_dir: str | Path = "final_reports",
    ):
        self.orchestrator_factory = orchestrator_factory or DiseaseReportOrchestrator
        self.output_dir = output_dir

    def run(
        self,
        user_query: str,
        pdf_paths: Optional[list] = None,
        checkpointer: Any = None,
        thread_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        orchestrator = self.orchestrator_factory()
        return orchestrator.run(user_query=user_query, output_dir=str(self.output_dir))

    def stream(
        self,
        user_query: str,
        pdf_paths: Optional[list] = None,
        progress_callback: Any = None,
        checkpointer: Any = None,
        thread_id: Optional[str] = None,
        interrupt_before: Optional[list] = None,
        allow_interrupts: bool = False,
    ) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        orchestrator = self.orchestrator_factory()
        for node_name, state in orchestrator.stream(user_query=user_query, output_dir=str(self.output_dir)):
            if progress_callback:
                progress_callback(node_name, state)
            yield node_name, state

    def get_state(self, thread_id: str, checkpointer: Any = None) -> Any:
        return None

    def resume(
        self,
        thread_id: str,
        checkpointer: Any,
        progress_callback: Any = None,
    ) -> Generator[Tuple[str, Dict[str, Any]], None, None]:
        yield from ()


__all__ = ["WorkflowService"]
```

- [ ] **Step 4: Run service tests and verify they pass**

Run:

```powershell
pytest tests/reports/disease/test_workflow_service.py -v
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

```powershell
git add src/services/workflow_service.py tests/reports/disease/test_workflow_service.py
git commit -m "feat: route workflow service to disease pipeline"
```

---

### Task 11: End-To-End Disease Report Regression

**Files:**
- Test: `tests/reports/disease/test_end_to_end_pipeline.py`

- [ ] **Step 1: Write end-to-end regression test**

Create `tests/reports/disease/test_end_to_end_pipeline.py`:

```python
from pathlib import Path

from src.reports.disease.orchestrator import DiseaseReportOrchestrator


def _study(nct, title, condition, intervention, sponsor, status="RECRUITING", first_posted="2026-04-20"):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": title},
            "statusModule": {
                "overallStatus": status,
                "studyFirstPostDateStruct": {"date": first_posted},
                "lastUpdatePostDateStruct": {"date": "2026-04-21"},
            },
            "conditionsModule": {"conditions": [condition]},
            "armsInterventionsModule": {"interventions": [{"name": intervention}]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": sponsor}},
            "designModule": {"studyType": "INTERVENTIONAL"},
        }
    }


class CapturingRendererAdapter:
    def __init__(self):
        self.ir = None

    def render_all(self, document_ir, output_dir, project_name):
        self.ir = document_ir
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        markdown = _markdown_from_ir(document_ir)
        md = output / "report.md"
        html = output / "report.html"
        pdf = output / "report.pdf"
        ir = output / "report.ir.json"
        md.write_text(markdown, encoding="utf-8")
        html.write_text("<html></html>", encoding="utf-8")
        pdf.write_bytes(b"%PDF-fake")
        ir.write_text("{}", encoding="utf-8")
        from src.reports.disease.models import DiseaseReportArtifacts

        return DiseaseReportArtifacts(
            markdown_content=markdown,
            markdown_path=str(md),
            html_path=str(html),
            pdf_path=str(pdf),
            ir_path=str(ir),
        )


def _markdown_from_ir(ir):
    lines = [ir["title"]]
    for chapter in ir["chapters"]:
        lines.append(chapter["title"])
        for block in chapter["blocks"]:
            lines.append(str(block))
    return "\n".join(lines)


def test_end_to_end_pipeline_filters_noise_preserves_status_and_removes_old_sections(tmp_path):
    renderer = CapturingRendererAdapter()

    def get_json(url, params):
        return {
            "studies": [
                _study("NCT_KEEP_1", "AD amyloid study", "Alzheimer Disease", "anti-amyloid monoclonal antibody", "Sponsor A", "RECRUITING"),
                _study("NCT_KEEP_2", "AD tau study", "Alzheimer's Disease", "tau aggregation inhibitor", "Sponsor B", "COMPLETED"),
                _study("NCT_BAD_PD", "Parkinson title mentions Alzheimer", "Parkinson Disease", "Levodopa", "Sponsor C", "RECRUITING"),
                _study("NCT_BAD_CBT", "Cognitive therapy", "Cognitive Impairment", "Cognitive Behavioral Therapy", "Sponsor D", "RECRUITING"),
            ]
        }

    state = DiseaseReportOrchestrator(
        clinicaltrials_get_json=get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=renderer,
        current_date_for_tests="2026-04-27",
    ).run("conduct a comprehensive survey on Alzheimer disease", output_dir=tmp_path)

    report = state["final_report"]

    assert state["status"] == "writer_complete"
    assert state["clinical_data"]["trial_records"] == 2
    assert "NCT_KEEP_1" in report
    assert "NCT_KEEP_2" in report
    assert "RECRUITING" in report
    assert "COMPLETED" in report
    assert "NCT_BAD_PD" not in report
    assert "NCT_BAD_CBT" not in report
    assert "Drug Pipeline" not in report
    assert "Trial Landscape" not in report
    assert "Company Technical Route Analysis" not in report
    assert "Literature Review" not in report
    assert "CNS Benchmark" not in report
    assert "Data Quality" not in report
    assert "Enrollment" not in report
    assert "Primary Endpoint" not in report
    assert [chapter["title"] for chapter in renderer.ir["chapters"]] == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
    ]
```

- [ ] **Step 2: Run end-to-end test and verify it passes**

Run:

```powershell
pytest tests/reports/disease/test_end_to_end_pipeline.py -v
```

Expected:

```text
1 passed
```

- [ ] **Step 3: Commit**

```powershell
git add tests/reports/disease/test_end_to_end_pipeline.py
git commit -m "test: cover disease report end-to-end flow"
```

---

### Task 12: Remove Legacy Disease Survey And Generic Graph Report Path

**Files:**
- Delete: `src/agents/supervisor.py`
- Delete: `src/agents/report_writer.py`
- Delete: `src/agents/report_writer_agent.py`
- Delete: `src/engines/report_engine/agent.py`
- Delete: `src/engines/evidence_synthesizer/`
- Delete: `src/engines/clinical_analyzer/`
- Delete: `src/engines/quality_assessor/`
- Delete: `src/graph/workflow.py`
- Modify: `src/graph/__init__.py`
- Delete: `src/graph/state.py`
- Delete: `src/graph/profile.py`
- Delete: `src/graph/contracts.py`
- Delete: `src/graph/nodes/disease_survey_intelligence_node.py`
- Delete: `src/graph/nodes/writer_node.py`
- Delete: `src/graph/nodes/harvester_node.py`
- Delete: `src/graph/nodes/extension_handoff_node.py`
- Delete: `src/graph/nodes/evidence_synthesizer_node.py`
- Delete: `src/graph/nodes/clinical_analyzer_node.py`
- Delete: `src/graph/nodes/quality_assessor_node.py`
- Delete: `src/graph/nodes/__init__.py`
- Delete: `src/engines/report_engine/disease_survey/__init__.py`
- Delete: `src/engines/report_engine/disease_survey/aggregator.py`
- Delete: `src/engines/report_engine/disease_survey/company_routes.py`
- Delete: `src/engines/report_engine/disease_survey/composer.py`
- Delete: `src/engines/report_engine/disease_survey/intelligence.py`
- Delete: `src/engines/report_engine/disease_survey/journal_scope.py`
- Delete: `src/engines/report_engine/disease_survey/models.py`
- Delete: `src/engines/report_engine/disease_survey/pipeline_risk.py`
- Delete: `src/engines/report_engine/disease_survey/renderer.py`
- Modify: `src/engines/report_engine/__init__.py`
- Modify: `src/agents/__init__.py`
- Modify: `app.py`
- Delete: old tests listed in the file structure section

- [ ] **Step 1: Remove app import of deleted graph state**

In `app.py`, remove these imports:

```python
from src.graph.state import AgentState
from langgraph.checkpoint.memory import MemorySaver
```

No replacement import is needed. Also remove the checkpointer initialization:

```python
_redis_checkpointer = MemorySaver()
```

In the `_workflow_service.stream(...)` call, remove this argument:

```python
checkpointer=_redis_checkpointer,
```

- [ ] **Step 2: Remove report writer exports from `src/engines/report_engine/__init__.py`**

Delete this import:

```python
from .agent import ReportWriterAgent, create_report_agent
```

Delete these names from `__all__`:

```python
"ReportWriterAgent",
"create_report_agent",
```

- [ ] **Step 3: Remove report writer exports from `src/agents/__init__.py`**

Replace `src/agents/__init__.py` with:

```python
"""Agent package.

The production disease report path is owned by src.reports.disease.
"""

__all__: list[str] = []
```

- [ ] **Step 4: Delete legacy source files**

Run:

```powershell
git rm src/agents/supervisor.py
git rm src/agents/report_writer.py
git rm src/agents/report_writer_agent.py
git rm src/engines/report_engine/agent.py
git rm -r src/engines/evidence_synthesizer
git rm -r src/engines/clinical_analyzer
git rm -r src/engines/quality_assessor
git rm src/graph/workflow.py src/graph/state.py src/graph/profile.py src/graph/contracts.py
git rm -r src/graph/nodes
git rm -r src/engines/report_engine/disease_survey
```

Expected:

```text
rm 'src/agents/supervisor.py'
rm 'src/agents/report_writer.py'
rm 'src/agents/report_writer_agent.py'
rm 'src/engines/report_engine/agent.py'
rm 'src/engines/evidence_synthesizer/...'
rm 'src/engines/clinical_analyzer/...'
rm 'src/engines/quality_assessor/...'
rm 'src/graph/workflow.py'
rm 'src/graph/state.py'
rm 'src/graph/profile.py'
rm 'src/graph/contracts.py'
rm 'src/graph/nodes/...'
rm 'src/engines/report_engine/disease_survey/...'
```

- [ ] **Step 5: Remove untracked legacy directories left after `git rm`**

Run:

```powershell
$repo = Resolve-Path -LiteralPath '.'
$legacyDirs = @(
  'src\graph\nodes',
  'src\engines\report_engine\disease_survey',
  'src\engines\evidence_synthesizer',
  'src\engines\clinical_analyzer',
  'src\engines\quality_assessor'
)
foreach ($legacyDir in $legacyDirs) {
  if (Test-Path -LiteralPath $legacyDir) {
    $resolved = Resolve-Path -LiteralPath $legacyDir
    if (-not $resolved.Path.StartsWith($repo.Path)) { throw "Refusing to remove path outside repository root: $($resolved.Path)" }
    Remove-Item -LiteralPath $resolved.Path -Recurse -Force
  }
}
git add -A src\graph\nodes src\engines\report_engine\disease_survey src\engines\evidence_synthesizer src\engines\clinical_analyzer src\engines\quality_assessor
```

Expected:

```text
No PowerShell error output.
```

- [ ] **Step 6: Keep `src.graph.manager` importable without the deleted workflow**

Replace `src/graph/__init__.py` with:

```python
"""Knowledge graph integration package.

The disease report workflow no longer lives in src.graph.
"""

try:
    from .manager import GraphManager
except Exception:
    GraphManager = None

__all__ = ["GraphManager"]
```

- [ ] **Step 7: Delete old tests that assert removed behavior**

Run:

```powershell
git rm tests/test_writer_slot_consumption.py
git rm tests/test_report_writer_agent.py
git rm tests/test_disease_survey_renderer.py
git rm tests/test_disease_survey_models.py
git rm tests/test_disease_survey_e2e.py
git rm tests/test_disease_survey_composer.py
git rm tests/test_disease_survey_aggregator.py
git rm tests/test_company_route_enrichment.py
git rm tests/test_dataflow_integrity.py
git rm tests/test_evidence_synthesizer.py
git rm tests/test_clinical_analyzer.py
git rm tests/test_quality_assessor.py
git rm tests/dev_checks/check_harvest_dataflow.py
git rm tests/dev_checks/check_source_to_report_chain.py
git rm tests/dev_checks/check_disease_field_completeness.py
```

Expected:

```text
rm 'tests/test_writer_slot_consumption.py'
rm 'tests/test_report_writer_agent.py'
rm 'tests/test_disease_survey_renderer.py'
rm 'tests/test_disease_survey_models.py'
rm 'tests/test_disease_survey_e2e.py'
rm 'tests/test_disease_survey_composer.py'
rm 'tests/test_disease_survey_aggregator.py'
rm 'tests/test_company_route_enrichment.py'
rm 'tests/test_dataflow_integrity.py'
rm 'tests/test_evidence_synthesizer.py'
rm 'tests/test_clinical_analyzer.py'
rm 'tests/test_quality_assessor.py'
rm 'tests/dev_checks/check_harvest_dataflow.py'
rm 'tests/dev_checks/check_source_to_report_chain.py'
rm 'tests/dev_checks/check_disease_field_completeness.py'
```

- [ ] **Step 8: Verify no production references to removed path remain**

Run:

```powershell
rg "slot_disease_survey|legacy_disease_survey_fallback|disease_survey_intelligence|aggregate_survey_data|compose_disease_survey|DiseaseSurveyState|create_report_agent|run_cassandra_workflow|stream_cassandra_workflow|evidence_synthesizer|clinical_analyzer|quality_assessor" src tests app.py
```

Expected:

```text
No matches.
```

- [ ] **Step 9: Verify removed chapters and removed fields do not appear in disease report code**

Run:

```powershell
rg "Drug Pipeline|Trial Landscape|Company Technical Route Analysis|Literature Review|CNS Benchmark|Data Quality|Primary Endpoint|Enrollment" src/reports src/services tests/reports app.py
```

Expected:

```text
No matches.
```

- [ ] **Step 10: Run focused disease report test suite**

Run:

```powershell
pytest tests/reports/disease -v
```

Expected:

```text
All tests in tests/reports/disease pass.
```

- [ ] **Step 11: Commit**

```powershell
git add app.py src/engines/report_engine/__init__.py src/agents/__init__.py src/graph/__init__.py
git add -u src tests
git commit -m "refactor: remove legacy disease survey report path"
```

---

### Task 13: Full Verification

**Files:**
- No source file creation.
- Validate the whole project after the architecture replacement.

- [ ] **Step 1: Run static import scan**

Run:

```powershell
python -m compileall src
```

Expected:

```text
No SyntaxError output.
```

- [ ] **Step 2: Run focused disease report tests**

Run:

```powershell
pytest tests/reports/disease -v
```

Expected:

```text
All tests in tests/reports/disease pass.
```

- [ ] **Step 3: Run renderer regression tests that still apply**

Run:

```powershell
pytest tests/test_report_engine_sanitization.py tests/test_clinical_trials_results_flow.py -v
```

Expected:

```text
All selected tests pass.
```

- [ ] **Step 4: Run full test suite**

Run:

```powershell
pytest -v
```

Expected:

```text
All collected tests pass.
```

- [ ] **Step 5: Run dead-code search one final time**

Run:

```powershell
rg "slot_disease_survey|legacy_disease_survey_fallback|disease_survey_intelligence|aggregate_survey_data|compose_disease_survey|DiseaseSurveyState|evidence_synthesizer|clinical_analyzer|quality_assessor" src tests app.py
rg "Drug Pipeline|Trial Landscape|Company Technical Route Analysis|Literature Review|CNS Benchmark|Data Quality|Primary Endpoint|Enrollment" src/reports src/services tests/reports app.py
```

Expected:

```text
No matches.
```

- [ ] **Step 6: Run git whitespace check**

Run:

```powershell
git diff --check
```

Expected:

```text
No output.
```

- [ ] **Step 7: Confirm no verification-only file changes remain**

Run:

```powershell
git status --short src tests app.py
```

Expected after Tasks 1 through 12 have been committed:

```text
No output.
```

---

## Acceptance Checklist

- [ ] `WorkflowService.run()` and `WorkflowService.stream()` use `DiseaseReportOrchestrator`.
- [ ] No production disease report path uses `slot_disease_survey`.
- [ ] No production disease report path uses writer-side legacy fallback.
- [ ] ClinicalTrials.gov records are condition full-match filtered before handoff.
- [ ] Alzheimer possessive variants resolve to one disease profile.
- [ ] Parkinson-only and broad cognitive impairment records are rejected for an Alzheimer Disease report.
- [ ] `Status` propagates from nested ClinicalTrials `overallStatus`, flat `status`, flat `study_status`, and metadata aliases.
- [ ] Landscape table contains exactly seven approved columns.
- [ ] `Enrollment` and `Primary Endpoint` are absent from the disease report contract and rendered output.
- [ ] Removed chapters do not render.
- [ ] Risk signals are deterministic and evidence-backed.
- [ ] Markdown, HTML, PDF, and IR artifacts are generated from the same document IR.
- [ ] HTML table rendering respects disease report wide-table column hints.
- [ ] The company route interface exists as `NoopCompanyRouteProvider` and does not render a chapter.
- [ ] The focused test suite `pytest tests/reports/disease -v` passes.
- [ ] The full test suite `pytest -v` passes.
