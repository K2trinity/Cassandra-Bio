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


def _company_package() -> DiseaseReportPackage:
    profile = DiseaseProfile(
        query="Company pipeline for Eli Lilly and Company",
        target_type="company",
        target_name="Eli Lilly and Company",
        company_name="Eli Lilly and Company",
        disease_name="Eli Lilly and Company",
        canonical_condition="Eli Lilly and Company",
        condition_terms=[],
        normalized_terms=[],
        expert_topic_url="https://clinicaltrials.gov/search?query.spons=Eli%20Lilly%20and%20Company",
        expert_full_match_url="https://clinicaltrials.gov/search?query.spons=Eli%20Lilly%20and%20Company",
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
        phases=["PHASE3"],
        study_results="Results available",
        results_url="https://clinicaltrials.gov/study/NCT00000001/results",
        has_results=True,
        strata=["catalyst", "track_record"],
        primary_stratum="catalyst",
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
        competition_evidence="5 retained Eli Lilly and Company studies share intervention category amyloid antibody.",
    )
    audit = SourceAudit(
        topic_url=profile.expert_topic_url,
        full_match_url=profile.expert_full_match_url,
        selected_condition_terms=profile.condition_terms,
        raw_count=3,
        retained_count=1,
        rejected_count=2,
        rejected_nct_numbers=["NCT_REJECTED"],
        details={
            "target_type": "company",
            "target_name": "Eli Lilly and Company",
            "company_name": "Eli Lilly and Company",
            "expansion_condition_counts": {"Alzheimer Disease": 1},
            "stratum_counts": {"catalyst": 1, "track_record": 1},
        },
    )
    return DiseaseReportPackage(
        disease_profile=profile,
        clinical_trials=[trial],
        risk_records=[risk],
        source_audit=audit,
        generated_at=datetime(2026, 4, 28, tzinfo=timezone.utc),
    )


def _disease_package() -> DiseaseReportPackage:
    package = _company_package()
    profile = DiseaseProfile(
        query="Alzheimer disease",
        disease_name="Alzheimer Disease",
        canonical_condition="Alzheimer Disease",
        condition_terms=["Alzheimer Disease"],
        normalized_terms=["alzheimer disease"],
        expert_topic_url="https://clinicaltrials.gov/expert-search?term=Alzheimer%20Disease&viewType=Topic",
        expert_full_match_url="https://clinicaltrials.gov/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D",
    )
    trial = package.clinical_trials[0].model_copy(
        update={
            "phases": ["PHASE1"],
            "has_results": False,
            "study_results": "No posted results",
            "strata": ["frontier"],
            "primary_stratum": "frontier",
            "primary_outcome_measures": ["Change in iADRS"],
        }
    )
    audit = package.source_audit.model_copy(
        update={
            "details": {
                "target_type": "disease",
                "stratum_counts": {
                    "evidence": 0,
                    "foundation": 0,
                    "frontier": 1,
                    "unclassified": 0,
                },
            }
        }
    )
    return package.model_copy(
        update={
            "disease_profile": profile,
            "clinical_trials": [trial],
            "source_audit": audit,
        }
    )


def test_company_narrative_payload_is_chapter_scoped_and_read_only():
    package = _company_package()
    before = package.model_dump(mode="json")

    payload = build_narrative_payload(package)

    assert payload["executive_summary"]["target_type"] == "company"
    assert payload["clinical_trial_and_pipeline_landscape"]["target_type"] == "company"
    assert payload["clinical_trial_and_pipeline_landscape"]["stratum_counts"] == {
        "catalyst": 1,
        "track_record": 1,
    }
    assert payload["clinical_trial_and_pipeline_landscape"]["expansion_condition_counts"] == {
        "Alzheimer Disease": 1,
    }
    record = payload["clinical_trial_and_pipeline_landscape"]["records"][0]
    assert record["nct_number"] == "NCT00000001"
    assert record["phases"] == ["PHASE3"]
    assert record["study_results"] == "Results available"
    company_summary = payload["company_pipeline_summary"]
    assert company_summary["company_name"] == "Eli Lilly and Company"
    assert company_summary["section_order"] == [
        "Catalyst Tracker",
        "Expansion Map",
        "Track Record",
    ]
    assert company_summary["catalyst_tracker"]["records"][0]["nct_number"] == "NCT00000001"
    assert company_summary["track_record"]["records"][0]["results"] == "Results available"
    assert "disease_evidence_synthesis" not in payload
    assert package.model_dump(mode="json") == before


def test_disease_narrative_payload_exposes_architecture_and_disease_fourth_summary():
    payload = build_narrative_payload(_disease_package())

    assert payload["executive_summary"]["target_type"] == "disease"
    assert "company_pipeline_summary" not in payload
    assert payload["report_architecture"]["chapters"][-1] == {
        "id": "disease_evidence_synthesis_summary",
        "purpose": "Summarizes the first three disease chapters into a source-grounded disease-level conclusion.",
    }
    assert payload["clinical_trial_and_pipeline_landscape"]["stratum_counts"]["frontier"] == 1
    assert payload["clinical_trial_and_pipeline_landscape"]["phase_distribution"] == {"PHASE1": 1}
    assert payload["clinical_trial_and_pipeline_landscape"]["results_distribution"] == {
        "No posted results": 1,
    }
    assert payload["clinical_trial_and_pipeline_landscape"]["records"][0]["primary_stratum"] == "frontier"
    assert payload["clinical_trial_and_pipeline_landscape"]["records"][0]["primary_outcome_measures"] == [
        "Change in iADRS"
    ]
    disease_summary = payload["disease_evidence_synthesis"]
    assert disease_summary["target_type"] == "disease"
    assert disease_summary["section_order"] == [
        "Executive Summary",
        "Clinical Trial And Pipeline Landscape",
        "Pipeline Timeline And Competition Risk",
    ]


def test_disease_narrative_service_requests_disease_fourth_chapter():
    client = FakeClient(
        {
            "executive_summary": "该报告保留一项阿尔茨海默病临床试验，展示近期管线活动。",
            "clinical_trial_and_pipeline_landscape": "入组试验集中在干预性研究，赞助方和干预手段清晰。",
            "pipeline_timeline_and_competition_risk": "时间线风险较低，竞争风险由同类干预数量决定。",
            "disease_evidence_synthesis_summary": "前三章共同说明该疾病证据仍需按来源字段谨慎解释。",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_disease_package(), language="zh")

    assert narratives.language == "zh"
    assert narratives.executive_summary.startswith("该报告")
    assert narratives.disease_evidence_synthesis_summary.startswith("前三章")
    assert client.calls[0]["response_schema"]["required"] == [
        "executive_summary",
        "clinical_trial_and_pipeline_landscape",
        "pipeline_timeline_and_competition_risk",
        "disease_evidence_synthesis_summary",
    ]
    assert "company_catalyst_and_rd_summary" not in client.calls[0]["response_schema"]["properties"]
    assert "Do not reuse company labels" in client.calls[0]["system_instruction"]
    assert client.calls[0]["kwargs"]["max_output_tokens"] == 2400


def test_company_narrative_service_requests_short_bold_company_summary():
    client = FakeClient(
        {
            "executive_summary": "公司报告保留一项临床试验。",
            "clinical_trial_and_pipeline_landscape": "管线表格展示三层数据。",
            "pipeline_timeline_and_competition_risk": "风险表使用确定性标签。",
            "company_catalyst_and_rd_summary": "**Catalyst Tracker:** 近期读出有限。 **Expansion Map:** 招募方向集中。 **Track Record:** 仅代表有结果基准。",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_company_package(), language="zh")

    assert narratives.company_catalyst_and_rd_summary.startswith("**Catalyst Tracker:**")
    assert client.calls[0]["response_schema"]["required"] == [
        "executive_summary",
        "clinical_trial_and_pipeline_landscape",
        "pipeline_timeline_and_competition_risk",
        "company_catalyst_and_rd_summary",
    ]
    assert "disease_evidence_synthesis_summary" not in client.calls[0]["response_schema"]["properties"]
    assert "company-oriented clinical pipeline summary" in client.calls[0]["system_instruction"]
    assert "Use bold labels" in client.calls[0]["system_instruction"]


def test_narrative_service_returns_english_strings_from_mocked_gemini():
    client = FakeClient(
        {
            "executive_summary": "The report retains one Alzheimer Disease clinical trial.",
            "clinical_trial_and_pipeline_landscape": "The landscape is centered on interventional development.",
            "pipeline_timeline_and_competition_risk": "Risk discussion remains grounded in deterministic labels.",
            "disease_evidence_synthesis_summary": "The first three chapters support a source-grounded disease synthesis.",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_disease_package(), language="en")

    assert narratives.language == "en"
    assert narratives.executive_summary.startswith("The report")
    assert narratives.disease_evidence_synthesis_summary.startswith("The first three")
    assert "English" in client.calls[0]["system_instruction"]


def test_narrative_service_falls_back_to_empty_on_invalid_payload():
    client = FakeClient({"error": "JSON parse failed"})
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_company_package(), language="zh")

    assert narratives.language == "zh"
    assert narratives.executive_summary == ""
    assert narratives.clinical_trial_and_pipeline_landscape == ""
    assert narratives.pipeline_timeline_and_competition_risk == ""
    assert narratives.company_catalyst_and_rd_summary == ""


def test_narrative_service_falls_back_to_empty_on_missing_mode_specific_field():
    client = FakeClient(
        {
            "executive_summary": "Partial output should not be used.",
            "clinical_trial_and_pipeline_landscape": "Partial.",
            "pipeline_timeline_and_competition_risk": "Partial.",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_disease_package(), language="en")

    assert narratives.language == "en"
    assert narratives.executive_summary == ""
    assert narratives.disease_evidence_synthesis_summary == ""


def test_narrative_service_falls_back_to_empty_on_non_string_fields():
    client = FakeClient(
        {
            "executive_summary": {"text": "Not a string."},
            "clinical_trial_and_pipeline_landscape": "Valid landscape.",
            "pipeline_timeline_and_competition_risk": "Valid risk.",
            "company_catalyst_and_rd_summary": "Valid company.",
        }
    )
    service = DiseaseReportNarrativeService(client_factory=lambda: client)

    narratives = service.generate(_company_package(), language="zh")

    assert narratives.language == "zh"
    assert narratives.executive_summary == ""
    assert narratives.clinical_trial_and_pipeline_landscape == ""
    assert narratives.pipeline_timeline_and_competition_risk == ""
    assert narratives.company_catalyst_and_rd_summary == ""
