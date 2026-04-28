# Report Narratives Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional Gemini-generated Chinese or English descriptive paragraphs to each disease report chapter without changing structured report data.

**Architecture:** Add a read-only narrative layer between `DiseaseReportPackageBuilder` and `DiseaseReportIRBuilder`. The narrative service builds chapter-scoped payloads from `DiseaseReportPackage`, calls the configured Gemini report client for strict JSON, and returns strings only. The IR builder inserts those strings as paragraph blocks and falls back to deterministic paragraphs when narrative generation fails.

**Tech Stack:** Python 3.11, Pydantic v2, existing `src.llms.create_report_client()`, pytest.

---

## File Structure

- `src/reports/disease/models.py`: add `DiseaseChapterNarratives`.
- `src/reports/disease/narrative.py`: new read-only Gemini narrative service and deterministic payload builders.
- `src/reports/disease/ir_builder.py`: accept optional narratives and insert paragraph blocks.
- `src/reports/disease/orchestrator.py`: call narrative service after package construction.
- `src/services/workflow_service.py`: pass narrative language through public service methods.
- `app.py`: read optional `narrative_language` from `/api/analyze` JSON.
- `config.py`: add `REPORT_NARRATIVE_LANGUAGE` default.
- `tests/reports/disease/test_narrative.py`: new narrative service tests with mocked client.
- `tests/reports/disease/test_ir_builder.py`: extend IR insertion tests.
- `tests/reports/disease/test_workflow_service.py`: extend orchestration language propagation tests.

No KLine or backtest files are modified in this plan.

---

### Task 1: Add Narrative Model

**Files:**
- Modify: `src/reports/disease/models.py`
- Modify: `src/reports/disease/__init__.py`
- Test: `tests/reports/disease/test_models.py`

- [ ] **Step 1: Write failing model tests**

Append to `tests/reports/disease/test_models.py`:

```python
from src.reports.disease.models import DiseaseChapterNarratives


def test_disease_chapter_narratives_defaults_to_chinese_empty_strings():
    narratives = DiseaseChapterNarratives()

    assert narratives.language == "zh"
    assert narratives.executive_summary == ""
    assert narratives.clinical_trial_and_pipeline_landscape == ""
    assert narratives.pipeline_timeline_and_competition_risk == ""


def test_disease_chapter_narratives_accepts_english():
    narratives = DiseaseChapterNarratives(
        executive_summary="English executive summary.",
        clinical_trial_and_pipeline_landscape="English landscape summary.",
        pipeline_timeline_and_competition_risk="English risk summary.",
        language="en",
    )

    assert narratives.language == "en"
    assert narratives.executive_summary == "English executive summary."
```

- [ ] **Step 2: Run tests and verify expected failure**

Run:

```powershell
pytest tests/reports/disease/test_models.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
ImportError: cannot import name 'DiseaseChapterNarratives'
```

- [ ] **Step 3: Implement model**

In `src/reports/disease/models.py`, update imports:

```python
from typing import Any, Literal
```

Add after `DiseaseReportPackage`:

```python
class DiseaseChapterNarratives(BaseModel):
    model_config = ConfigDict(extra="forbid")

    executive_summary: str = ""
    clinical_trial_and_pipeline_landscape: str = ""
    pipeline_timeline_and_competition_risk: str = ""
    language: Literal["zh", "en"] = "zh"
```

In `src/reports/disease/__init__.py`, import and export `DiseaseChapterNarratives`:

```python
from .models import (
    ClinicalTrialRecord,
    DiseaseChapterNarratives,
    DiseaseProfile,
    DiseaseReportArtifacts,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)

__all__ = [
    "ClinicalTrialRecord",
    "DiseaseChapterNarratives",
    "DiseaseProfile",
    "DiseaseReportArtifacts",
    "DiseaseReportPackage",
    "PipelineRiskRecord",
    "SourceAudit",
]
```

- [ ] **Step 4: Run model tests**

Run:

```powershell
pytest tests/reports/disease/test_models.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git status --short
git add src/reports/disease/models.py src/reports/disease/__init__.py tests/reports/disease/test_models.py
git commit -m "feat: add disease report narrative model"
```

Expected:

```text
[branch commit] feat: add disease report narrative model
```

---

### Task 2: Add Read-Only Gemini Narrative Service

**Files:**
- Create: `src/reports/disease/narrative.py`
- Create: `tests/reports/disease/test_narrative.py`

- [ ] **Step 1: Write failing narrative service tests**

Create `tests/reports/disease/test_narrative.py`:

```python
from __future__ import annotations

from datetime import date, datetime, timezone

from src.reports.disease.models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)
from src.reports.disease.narrative import DiseaseReportNarrativeService, build_narrative_payload


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def generate_json(self, prompt, response_schema=None, system_instruction=None, **kwargs):
        self.calls.append(
            {
                "prompt": prompt,
                "response_schema": response_schema,
                "system_instruction": system_instruction,
                "kwargs": kwargs,
            }
        )
        return self.payload


def _package() -> DiseaseReportPackage:
    profile = DiseaseProfile(
        query="Alzheimer disease",
        disease_name="Alzheimer Disease",
        canonical_condition="Alzheimer Disease",
        condition_terms=["Alzheimer Disease"],
        normalized_terms=["alzheimer disease"],
        expert_topic_url="https://clinicaltrials.gov/expert-search?term=Alzheimer%20Disease&viewType=Topic",
        expert_full_match_url="https://clinicaltrials.gov/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D",
    )
    trial = ClinicalTrialRecord(
        study_title="A Study of Donanemab in Early Symptomatic Alzheimer Disease",
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
        nct_number=trial.nct_number,
        study_title=trial.study_title,
        sponsor=trial.sponsor,
        status=trial.status,
        intervention_category="amyloid antibody",
        timeline_signal="Low",
        timeline_evidence="Study first posted 2026-04-20; status RECRUITING; age 0.0 years.",
        competition_signal="Medium",
        competition_evidence="5 retained Alzheimer Disease studies share intervention category amyloid antibody.",
    )
    audit = SourceAudit(
        topic_url=profile.expert_topic_url,
        full_match_url=profile.expert_full_match_url,
        selected_condition_terms=profile.condition_terms,
        raw_count=3,
        retained_count=1,
        rejected_count=2,
        rejected_nct_numbers=["NCT_REJECTED"],
    )
    return DiseaseReportPackage(
        disease_profile=profile,
        clinical_trials=[trial],
        risk_records=[risk],
        source_audit=audit,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )


def test_build_narrative_payload_is_chapter_scoped_and_read_only():
    package = _package()
    before = package.model_dump(mode="json")

    payload = build_narrative_payload(package)

    assert payload["executive_summary"]["disease_name"] == "Alzheimer Disease"
    assert payload["executive_summary"]["retained_count"] == 1
    assert payload["clinical_trial_and_pipeline_landscape"]["records"][0]["nct_number"] == "NCT00000001"
    assert payload["pipeline_timeline_and_competition_risk"]["risk_records"][0]["timeline_signal"] == "Low"
    assert package.model_dump(mode="json") == before


def test_narrative_service_returns_chinese_strings_from_mocked_gemini():
    client = FakeClient(
        {
            "executive_summary": "该报告保留一项阿尔茨海默病临床试验，展示近期管线活动。",
            "clinical_trial_and_pipeline_landscape": "入组试验集中在干预性研究，赞助方和干预手段清晰。",
            "pipeline_timeline_and_competition_risk": "时间线风险较低，竞争风险由同类干预数量决定。",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_package(), language="zh")

    assert narratives.language == "zh"
    assert narratives.executive_summary.startswith("该报告")
    assert "Chinese" in client.calls[0]["system_instruction"]
    assert client.calls[0]["response_schema"]["required"] == [
        "executive_summary",
        "clinical_trial_and_pipeline_landscape",
        "pipeline_timeline_and_competition_risk",
    ]


def test_narrative_service_returns_english_strings_from_mocked_gemini():
    client = FakeClient(
        {
            "executive_summary": "The report retains one Alzheimer Disease clinical trial.",
            "clinical_trial_and_pipeline_landscape": "The landscape is centered on interventional development.",
            "pipeline_timeline_and_competition_risk": "Risk discussion remains grounded in deterministic labels.",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_package(), language="en")

    assert narratives.language == "en"
    assert narratives.executive_summary.startswith("The report")
    assert "English" in client.calls[0]["system_instruction"]


def test_narrative_service_falls_back_to_empty_on_invalid_payload():
    client = FakeClient({"error": "JSON parse failed"})
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_package(), language="zh")

    assert narratives.language == "zh"
    assert narratives.executive_summary == ""
    assert narratives.clinical_trial_and_pipeline_landscape == ""
    assert narratives.pipeline_timeline_and_competition_risk == ""
```

- [ ] **Step 2: Run tests and verify expected failure**

Run:

```powershell
pytest tests/reports/disease/test_narrative.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
ModuleNotFoundError: No module named 'src.reports.disease.narrative'
```

- [ ] **Step 3: Implement narrative service**

Create `src/reports/disease/narrative.py`:

```python
from __future__ import annotations

import json
from collections import Counter
from typing import Any, Callable, Literal

from loguru import logger

from src.llms import create_report_client

from .models import DiseaseChapterNarratives, DiseaseReportPackage


NARRATIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "clinical_trial_and_pipeline_landscape": {"type": "string"},
        "pipeline_timeline_and_competition_risk": {"type": "string"},
    },
    "required": [
        "executive_summary",
        "clinical_trial_and_pipeline_landscape",
        "pipeline_timeline_and_competition_risk",
    ],
}


class DiseaseReportNarrativeService:
    def __init__(self, client_factory: Callable[[], Any] = create_report_client) -> None:
        self.client_factory = client_factory

    def generate(
        self,
        package: DiseaseReportPackage,
        language: Literal["zh", "en"] = "zh",
    ) -> DiseaseChapterNarratives:
        selected_language = language if language in ("zh", "en") else "zh"
        payload = build_narrative_payload(package)
        system_instruction = _system_instruction(selected_language)
        prompt = (
            "Write descriptive chapter summaries from this JSON data only.\n\n"
            f"{json.dumps(payload, ensure_ascii=False, indent=2, default=str)}"
        )

        try:
            response = self.client_factory().generate_json(
                prompt,
                response_schema=NARRATIVE_SCHEMA,
                system_instruction=system_instruction,
                max_output_tokens=1200,
            )
        except Exception as exc:
            logger.warning(f"Disease report narrative generation failed: {exc}")
            return DiseaseChapterNarratives(language=selected_language)

        if not isinstance(response, dict):
            return DiseaseChapterNarratives(language=selected_language)

        values = {
            "executive_summary": _clean_text(response.get("executive_summary")),
            "clinical_trial_and_pipeline_landscape": _clean_text(response.get("clinical_trial_and_pipeline_landscape")),
            "pipeline_timeline_and_competition_risk": _clean_text(response.get("pipeline_timeline_and_competition_risk")),
        }
        if not any(values.values()):
            return DiseaseChapterNarratives(language=selected_language)

        return DiseaseChapterNarratives(language=selected_language, **values)


def build_narrative_payload(package: DiseaseReportPackage) -> dict[str, Any]:
    trials = package.clinical_trials
    risk_records = package.risk_records
    return {
        "executive_summary": {
            "disease_name": package.disease_profile.disease_name,
            "retained_count": package.source_audit.retained_count,
            "rejected_count": package.source_audit.rejected_count,
            "latest_study_first_posted": _latest_study_first_posted(package),
            "status_distribution": dict(Counter(trial.status for trial in trials)),
            "top_sponsors": _top_values([trial.sponsor for trial in trials], limit=5),
        },
        "clinical_trial_and_pipeline_landscape": {
            "disease_name": package.disease_profile.disease_name,
            "trial_count": len(trials),
            "records": [
                {
                    "study_title": trial.study_title,
                    "nct_number": trial.nct_number,
                    "status": trial.status,
                    "conditions": list(trial.conditions),
                    "interventions": list(trial.interventions),
                    "sponsor": trial.sponsor,
                    "study_type": trial.study_type,
                }
                for trial in trials
            ],
        },
        "pipeline_timeline_and_competition_risk": {
            "disease_name": package.disease_profile.disease_name,
            "risk_records": [
                {
                    "nct_number": record.nct_number,
                    "study_title": record.study_title,
                    "sponsor": record.sponsor,
                    "status": record.status,
                    "intervention_category": record.intervention_category,
                    "timeline_signal": record.timeline_signal,
                    "timeline_evidence": record.timeline_evidence,
                    "competition_signal": record.competition_signal,
                    "competition_evidence": record.competition_evidence,
                }
                for record in risk_records
            ],
            "risk_distribution": {
                "timeline": dict(Counter(record.timeline_signal for record in risk_records)),
                "competition": dict(Counter(record.competition_signal for record in risk_records)),
            },
        },
    }


def _system_instruction(language: Literal["zh", "en"]) -> str:
    output_language = "Chinese" if language == "zh" else "English"
    length_instruction = "80-180 Chinese characters per chapter." if language == "zh" else "60-120 English words per chapter."
    return (
        "You write short descriptive summaries for a biomedical report.\n"
        "Use only the supplied JSON data.\n"
        "Do not infer missing facts.\n"
        "Do not create trials, sponsors, dates, risk labels, endpoints, or numeric values.\n"
        "Do not classify risk.\n"
        "Do not modify field values.\n"
        "Return strict JSON only.\n"
        f"Write in {output_language}.\n"
        f"{length_instruction}"
    )


def _latest_study_first_posted(package: DiseaseReportPackage) -> str | None:
    dates = [trial.study_first_posted for trial in package.clinical_trials if trial.study_first_posted is not None]
    return max(dates).isoformat() if dates else None


def _top_values(values: list[str], limit: int) -> list[str]:
    counter = Counter(value for value in values if value and value != "Unknown")
    return [value for value, count in counter.most_common(limit)]


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    return " ".join(text.split())


__all__ = ["DiseaseReportNarrativeService", "NARRATIVE_SCHEMA", "build_narrative_payload"]
```

- [ ] **Step 4: Run narrative tests**

Run:

```powershell
pytest tests/reports/disease/test_narrative.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
4 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git status --short
git add src/reports/disease/narrative.py tests/reports/disease/test_narrative.py
git commit -m "feat: add disease report narrative service"
```

Expected:

```text
[branch commit] feat: add disease report narrative service
```

---

### Task 3: Insert Narratives Into Disease Report IR

**Files:**
- Modify: `src/reports/disease/ir_builder.py`
- Modify: `tests/reports/disease/test_ir_builder.py`

- [ ] **Step 1: Add failing IR insertion test**

Append to `tests/reports/disease/test_ir_builder.py`:

```python
from src.reports.disease.models import DiseaseChapterNarratives


def test_ir_builder_inserts_narrative_paragraphs_without_changing_tables():
    narratives = DiseaseChapterNarratives(
        executive_summary="中文执行摘要段落。",
        clinical_trial_and_pipeline_landscape="中文管线格局段落。",
        pipeline_timeline_and_competition_risk="中文风险段落。",
        language="zh",
    )

    ir = DiseaseReportIRBuilder().build(_package(), narratives=narratives)

    chapters = {chapter["chapterId"]: chapter for chapter in ir["chapters"]}
    assert chapters["executive_summary"]["blocks"][1]["inlines"][0]["text"] == "中文执行摘要段落。"
    assert chapters["clinical_trial_and_pipeline_landscape"]["blocks"][1]["inlines"][0]["text"] == "中文管线格局段落。"
    assert chapters["pipeline_timeline_and_competition_risk"]["blocks"][1]["inlines"][0]["text"] == "中文风险段落。"

    landscape_table = _find_table(ir, "clinical_trial_and_pipeline_landscape")
    risk_table = _find_table(ir, "pipeline_timeline_and_competition_risk")
    assert _table_headers(landscape_table) == LANDSCAPE_COLUMNS
    assert _table_headers(risk_table) == RISK_COLUMNS
```

- [ ] **Step 2: Run test and verify expected failure**

Run:

```powershell
pytest tests/reports/disease/test_ir_builder.py::test_ir_builder_inserts_narrative_paragraphs_without_changing_tables -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
TypeError: DiseaseReportIRBuilder.build() got an unexpected keyword argument 'narratives'
```

- [ ] **Step 3: Update IR builder signatures and chapter methods**

In `src/reports/disease/ir_builder.py`, update imports:

```python
from .models import ClinicalTrialRecord, DiseaseChapterNarratives, DiseaseReportPackage, PipelineRiskRecord
```

Update `build()`:

```python
    def build(
        self,
        package: DiseaseReportPackage,
        narratives: DiseaseChapterNarratives | None = None,
    ) -> dict:
```

Update chapter construction:

```python
        narratives = narratives or DiseaseChapterNarratives()
        chapters = [
            self._executive_summary_chapter(package, narratives),
            self._landscape_chapter(package.clinical_trials, narratives),
            self._risk_chapter(package.risk_records, narratives),
        ]
```

Update method signatures:

```python
    def _executive_summary_chapter(self, package: DiseaseReportPackage, narratives: DiseaseChapterNarratives) -> dict:
```

```python
    def _landscape_chapter(self, trials: list[ClinicalTrialRecord], narratives: DiseaseChapterNarratives) -> dict:
```

```python
    def _risk_chapter(self, risk_records: list[PipelineRiskRecord], narratives: DiseaseChapterNarratives) -> dict:
```

In each chapter, insert narrative paragraphs after the heading. Executive summary blocks should become:

```python
            "blocks": [
                _heading("Executive Summary", "executive-summary"),
                _paragraph(narratives.executive_summary) if narratives.executive_summary else _paragraph(summary),
                {
                    "type": "kpiGrid",
                    "cols": 3,
                    "items": [
                        {"label": "Retained Records", "value": str(audit.retained_count)},
                        {"label": "Rejected Records", "value": str(audit.rejected_count)},
                        {"label": "Risk Records", "value": str(len(package.risk_records))},
                    ],
                },
            ],
```

Landscape chapter blocks should start:

```python
            "blocks": [
                _heading(
                    "Clinical Trial And Pipeline Landscape",
                    "clinical-trial-and-pipeline-landscape",
                ),
                _paragraph(
                    narratives.clinical_trial_and_pipeline_landscape
                    or f"Structured clinical landscape contains {len(trials)} retained records."
                ),
                _table(
```

Risk chapter blocks should start:

```python
            "blocks": [
                _heading(
                    "Pipeline Timeline And Competition Risk",
                    "pipeline-timeline-and-competition-risk",
                ),
                _paragraph(
                    narratives.pipeline_timeline_and_competition_risk
                    or f"Timeline and competition assessment uses {len(risk_records)} deterministic risk records."
                ),
                _table(
```

- [ ] **Step 4: Run IR tests**

Run:

```powershell
pytest tests/reports/disease/test_ir_builder.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
5 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git status --short
git add src/reports/disease/ir_builder.py tests/reports/disease/test_ir_builder.py
git commit -m "feat: insert disease report narrative paragraphs"
```

Expected:

```text
[branch commit] feat: insert disease report narrative paragraphs
```

---

### Task 4: Wire Narrative Service Through Orchestrator And Workflow Service

**Files:**
- Modify: `src/reports/disease/orchestrator.py`
- Modify: `src/services/workflow_service.py`
- Modify: `tests/reports/disease/test_workflow_service.py`

- [ ] **Step 1: Add failing workflow propagation tests**

Append to `tests/reports/disease/test_workflow_service.py`:

```python
from src.reports.disease.models import DiseaseChapterNarratives


class FakeNarrativeService:
    def __init__(self):
        self.calls = []

    def generate(self, package, language="zh"):
        self.calls.append({"package": package, "language": language})
        return DiseaseChapterNarratives(
            executive_summary="English narrative.",
            clinical_trial_and_pipeline_landscape="English landscape.",
            pipeline_timeline_and_competition_risk="English risk.",
            language=language,
        )


def test_orchestrator_passes_narrative_language_to_service(tmp_path):
    narrative_service = FakeNarrativeService()

    def fake_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        return {"studies": [_study("NCT_ALZHEIMER", "Alzheimer Disease")]}

    orchestrator = DiseaseReportOrchestrator(
        clinicaltrials_get_json=fake_get_json,
        clinicaltrials_get_text=lambda url: "",
        renderer_adapter=FakeRendererAdapter(),
        narrative_service=narrative_service,
        current_date_for_tests="2026-04-27",
    )

    state = orchestrator.run(
        "Alzheimer disease",
        output_dir=tmp_path,
        max_trials=50,
        narrative_language="en",
    )

    assert narrative_service.calls[0]["language"] == "en"
    assert state["report_ir"]["chapters"][0]["blocks"][1]["inlines"][0]["text"] == "English narrative."


def test_workflow_service_forwards_narrative_language(tmp_path):
    class LanguageOrchestrator(FakeOrchestrator):
        def run(self, *, user_query: str, output_dir: str, narrative_language: str = "zh"):
            return {
                "status": "writer_complete",
                "user_query": user_query,
                "output_dir": output_dir,
                "narrative_language": narrative_language,
            }

    orchestrator = LanguageOrchestrator()
    service = WorkflowService(orchestrator_factory=lambda: orchestrator, output_dir=tmp_path)

    state = service.run("Alzheimer disease", narrative_language="en")

    assert state["narrative_language"] == "en"
```

- [ ] **Step 2: Run tests and verify expected failure**

Run:

```powershell
pytest tests/reports/disease/test_workflow_service.py::test_orchestrator_passes_narrative_language_to_service tests/reports/disease/test_workflow_service.py::test_workflow_service_forwards_narrative_language -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
TypeError mentioning narrative_service or narrative_language
```

- [ ] **Step 3: Update orchestrator**

In `src/reports/disease/orchestrator.py`, import:

```python
from .narrative import DiseaseReportNarrativeService
```

Update `__init__`:

```python
        narrative_service: Any | None = None,
```

Assign:

```python
        self.narrative_service = narrative_service or DiseaseReportNarrativeService()
```

Update `run()` signature:

```python
        narrative_language: str = "zh",
```

Pass into `stream()`:

```python
            narrative_language=narrative_language,
```

Update `stream()` signature:

```python
        narrative_language: str = "zh",
```

After package enrichment and before handoff state, generate narratives:

```python
        narratives = self.narrative_service.generate(
            package,
            language="en" if narrative_language == "en" else "zh",
        )
```

Include narratives in handoff state:

```python
            "disease_report_narratives": narratives.model_dump(mode="json"),
```

Build IR with narratives:

```python
        report_ir = self.ir_builder.build(package, narratives=narratives)
```

- [ ] **Step 4: Update WorkflowService**

In `src/services/workflow_service.py`, add `narrative_language` to `run()`:

```python
        narrative_language: str = "zh",
```

Pass it:

```python
            narrative_language=narrative_language,
```

Add `narrative_language` to `stream()`:

```python
        narrative_language: str = "zh",
```

Include it in the ignored tuple only if not passed onward. The correct implementation passes it onward:

```python
        for node_name, state in orchestrator.stream(
            user_query=user_query,
            output_dir=str(self.output_dir),
            narrative_language=narrative_language,
        ):
```

- [ ] **Step 5: Run workflow tests**

Run:

```powershell
pytest tests/reports/disease/test_workflow_service.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
6 passed
```

- [ ] **Step 6: Commit**

Run:

```powershell
git status --short
git add src/reports/disease/orchestrator.py src/services/workflow_service.py tests/reports/disease/test_workflow_service.py
git commit -m "feat: wire disease report narratives"
```

Expected:

```text
[branch commit] feat: wire disease report narratives
```

---

### Task 5: Add API And Config Language Option

**Files:**
- Modify: `config.py`
- Modify: `app.py`
- Modify: `tests/test_kline_web_integration.py` is not used here.
- Modify: `tests/reports/disease/test_workflow_service.py`

- [ ] **Step 1: Add configuration default**

In `config.py`, add under Report Engine settings:

```python
    REPORT_NARRATIVE_LANGUAGE: str = Field(
        "zh",
        description="Disease report narrative language: zh or en. Affects only Gemini-generated descriptive paragraphs."
    )
```

- [ ] **Step 2: Update app analysis request parsing**

In `app.py`, inside `analyze()`, after reading request JSON and query, add:

```python
    narrative_language = str(data.get("narrative_language") or getattr(config, "REPORT_NARRATIVE_LANGUAGE", "zh")).strip().lower()
    if narrative_language not in {"zh", "en"}:
        narrative_language = "zh"
```

In the existing `_workflow_service.stream` call, add this keyword argument:

```python
                narrative_language=narrative_language,
```

In the existing `_workflow_service.run` call, add this keyword argument:

```python
                    narrative_language=narrative_language,
```

In the `completion_payload`, include:

```python
                "narrative_language": narrative_language,
```

- [ ] **Step 3: Add app route test for language forwarding**

Create `tests/test_report_narrative_api.py`:

```python
from __future__ import annotations

import app as app_module
from app import app


class FakeWorkflowService:
    def __init__(self):
        self.stream_calls = []

    def stream(self, **kwargs):
        self.stream_calls.append(kwargs)
        yield "writer", {
            "status": "writer_complete",
            "final_report": "# Report\nNarrative text",
            "final_report_markdown": "# Report\nNarrative text",
            "final_report_path": None,
            "final_report_html_path": None,
            "final_report_pdf_path": None,
            "clinical_data": {},
            "evidence_stats": {},
            "extension_payloads": {},
            "harvested_data": [],
            "disease_areas": [],
        }

    def run(self, **kwargs):
        return {
            "status": "writer_complete",
            "final_report": "# Report\nNarrative text",
            "final_report_markdown": "# Report\nNarrative text",
            "clinical_data": {},
            "evidence_stats": {},
            "extension_payloads": {},
            "harvested_data": [],
            "disease_areas": [],
        }


def test_analyze_accepts_english_narrative_language(monkeypatch):
    fake_service = FakeWorkflowService()
    monkeypatch.setattr(app_module, "_workflow_service", fake_service)
    monkeypatch.setattr(app_module, "NEO4J_AVAILABLE", False)

    client = app.test_client()
    response = client.post(
        "/api/analyze",
        json={"query": "Alzheimer disease report", "narrative_language": "en"},
    )

    assert response.status_code == 202
    thread = app_module.active_analysis["thread"]
    thread.join(timeout=10)

    assert fake_service.stream_calls[0]["narrative_language"] == "en"
    assert app_module.active_analysis["result_payload"]["narrative_language"] == "en"
```

- [ ] **Step 4: Run API test and verify expected result**

Run:

```powershell
pytest tests/test_report_narrative_api.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
1 passed
```

- [ ] **Step 5: Commit**

Run:

```powershell
git status --short
git add config.py app.py tests/test_report_narrative_api.py
git commit -m "feat: add report narrative language option"
```

Expected:

```text
[branch commit] feat: add report narrative language option
```

---

### Task 6: Verify Narrative Integration

**Files:**
- No source files.

- [ ] **Step 1: Run focused disease report tests**

Run:

```powershell
pytest tests/reports/disease tests/test_report_narrative_api.py -q --basetemp .pytest_tmp_report_narratives
```

Expected:

```text
Command exits with code 0 and the pytest summary contains only passed tests under:
tests/reports/disease
tests/test_report_narrative_api.py
```

- [ ] **Step 2: Run compile check**

Run:

```powershell
python -m compileall src/reports/disease src/services/workflow_service.py app.py config.py
```

Expected:

```text
No SyntaxError output.
```

- [ ] **Step 3: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected:

```text
No output.
```

- [ ] **Step 4: Confirm Gemini boundary with text search**

Run:

```powershell
rg -n "generate_json|generate_content|create_report_client|DiseaseReportNarrativeService" src/reports/disease src/backtest src/kline src/services
```

Expected:

```text
Matches only in src/reports/disease/narrative.py and any imports or tests for the narrative service; no matches in src/backtest or src/kline.
```

- [ ] **Step 5: Remove temporary pytest directory**

Run:

```powershell
$repo = (Resolve-Path -LiteralPath '.').Path
$target = (Resolve-Path -LiteralPath '.pytest_tmp_report_narratives' -ErrorAction SilentlyContinue)
if ($target) {
  if (-not $target.Path.StartsWith($repo)) { throw "Refusing to remove path outside repository root: $($target.Path)" }
  Remove-Item -LiteralPath $target.Path -Recurse -Force
}
```

Expected:

```text
No output.
```

- [ ] **Step 6: Confirm clean scoped status**

Run:

```powershell
git status --short src/reports/disease src/services/workflow_service.py app.py config.py tests/reports/disease tests/test_report_narrative_api.py
```

Expected:

```text
No uncommitted files from this plan.
```
