from __future__ import annotations

from datetime import date, datetime, timezone

from src.reports.disease.models import (
    ClinicalTrialRecord,
    DiseaseProfile,
    DiseaseReportPackage,
    PipelineRiskRecord,
    SourceAudit,
)
from src.reports.disease.narrative import (
    DiseaseReportNarrativeService,
    build_narrative_payload,
)


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


def test_narrative_service_falls_back_to_empty_on_missing_fields():
    client = FakeClient({"executive_summary": "Partial output should not be used."})
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_package(), language="en")

    assert narratives.language == "en"
    assert narratives.executive_summary == ""
    assert narratives.clinical_trial_and_pipeline_landscape == ""
    assert narratives.pipeline_timeline_and_competition_risk == ""


def test_narrative_service_falls_back_to_empty_on_non_string_fields():
    client = FakeClient(
        {
            "executive_summary": {"text": "Not a string."},
            "clinical_trial_and_pipeline_landscape": "Valid landscape.",
            "pipeline_timeline_and_competition_risk": "Valid risk.",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_package(), language="zh")

    assert narratives.language == "zh"
    assert narratives.executive_summary == ""
    assert narratives.clinical_trial_and_pipeline_landscape == ""
    assert narratives.pipeline_timeline_and_competition_risk == ""
