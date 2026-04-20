"""Tests for disease survey composer."""
import pytest
from src.engines.report_engine.disease_survey import (
    CNSBenchmarkEntry,
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    SponsorProfile,
    TrialRecord,
    aggregate_survey_data,
)
from src.engines.report_engine.disease_survey.composer import (
    build_disease_survey_document,
    compose_disease_survey_report_bundle,
    compose_disease_survey_report,
)


def make_state():
    return DiseaseSurveyState(
        disease_name="Alzheimer's Disease",
        query="AD pipeline",
        drug_assets=[DrugAsset(asset_name="Lecanemab", targets=["Aβ"], sponsor="Eisai", phase="Phase 3")],
        trials=[TrialRecord(nct_id="NCT01767311", title="Clarity AD", phase="Phase 3")],
        sponsors=[SponsorProfile(company_name="Eisai", pipeline_count=1)],
        literature=[LiteratureRecord(pmid="1", title="Test paper", year=2023)],
    )


def make_rich_state(summary_text: str | None = None):
    return DiseaseSurveyState(
        disease_name="Alzheimer's Disease",
        query="AD pipeline",
        drug_assets=[
            DrugAsset(
                asset_name="Lecanemab",
                targets=["Aβ"],
                sponsor="Eisai",
                phase="Phase 3",
                modality="Monoclonal Antibody",
            ),
            DrugAsset(
                asset_name="AADvac1",
                targets=["Tau"],
                sponsor="Axon",
                phase="Phase 2",
                modality="Vaccine",
            ),
        ],
        trials=[
            TrialRecord(
                nct_id="NCT01767311",
                title="Clarity AD",
                asset_name="Lecanemab",
                sponsor="Eisai",
                phase="Phase 3",
                status="Completed",
                enrollment="1795",
                primary_endpoint="CDR-SB",
                ae_grade3plus="ARIA-E 12.6%",
                sae="Serious ARIA observed",
            ),
            TrialRecord(
                nct_id="NCT01234567",
                title="AADvac1 study",
                asset_name="AADvac1",
                sponsor="Axon",
                phase="Phase 2",
                status="Recruiting",
                enrollment="220",
                primary_endpoint="ADAS-Cog",
            ),
        ],
        sponsors=[
            SponsorProfile(
                company_name="Eisai",
                pipeline_count=1,
                lead_phase="Phase 3",
                ticker="4523.T",
                market_cap=20_000_000_000,
                cash_runway_months=24,
                rd_ratio=0.18,
            ),
            SponsorProfile(
                company_name="Axon",
                pipeline_count=1,
                lead_phase="Phase 2",
                ticker="AXON",
                market_cap=1_500_000_000,
                cash_runway_months=18,
                rd_ratio=0.32,
            ),
        ],
        literature=[
            LiteratureRecord(
                pmid="1",
                title="Amyloid beta paper",
                journal="NEJM",
                year=2023,
                authors="Doe et al.",
            ),
            LiteratureRecord(
                pmid="2",
                title="Tau vaccine paper",
                journal="Nature Reviews Neurology",
                year=2024,
                authors="Roe et al.",
            ),
        ],
        cns_benchmark=[
            CNSBenchmarkEntry(
                target_name="Aβ",
                publication_count_5yr=8,
                trial_count_5yr=3,
                top_journal_citations=2,
                trend="rising",
                matched=True,
            ),
            CNSBenchmarkEntry(
                target_name="Tau",
                publication_count_5yr=5,
                trial_count_5yr=2,
                top_journal_citations=1,
                trend="stable",
                matched=True,
            ),
        ],
        summary_text=summary_text,
    )


def _paragraph_text(block: dict) -> str:
    return "".join(
        inline.get("text", "") if isinstance(inline, dict) else str(inline)
        for inline in block.get("inlines", [])
    )


def test_compose_returns_all_sections():
    state = make_state()
    report = compose_disease_survey_report(state)
    expected_sections = [
        "executive_summary", "drug_pipeline", "trial_landscape",
        "sponsor_analysis", "target_biology", "safety_profile",
        "literature_review", "cns_benchmark", "market_landscape",
    ]
    for section in expected_sections:
        assert section in report, f"Missing section: {section}"


def test_compose_empty_state():
    state = DiseaseSurveyState(disease_name="Unknown", query="test")
    report = compose_disease_survey_report(state)
    assert report["executive_summary"]["total_assets"] == 0
    assert report["drug_pipeline"]["assets"] == []


def test_public_api_imports():
    from src.engines.report_engine.disease_survey import (
        aggregate_survey_data,
        render_executive_summary,
        render_drug_pipeline,
        DiseaseSurveyState,
        DrugAsset,
    )
    assert callable(aggregate_survey_data)
    assert callable(render_executive_summary)


def test_build_disease_survey_document_includes_chart_widgets():
    state = aggregate_survey_data(
        [
            {
                "source": "ClinicalTrials",
                "nct_id": "NCT001",
                "title": "Trial A",
                "summary": "Trial summary",
                "metadata": {
                    "intervention": "Drug A",
                    "sponsor": "Company A",
                    "phase": "Phase 2",
                    "status": "Recruiting",
                },
            },
            {
                "source": "ClinicalTrials",
                "nct_id": "NCT002",
                "title": "Trial B",
                "summary": "Trial summary",
                "metadata": {
                    "intervention": "Drug B",
                    "sponsor": "Company B",
                    "phase": "Phase 3",
                    "status": "Completed",
                },
            },
            {
                "source": "PubMed",
                "pmid": "100",
                "title": "Drug A biology",
                "journal": "NEJM",
                "year": 2024,
            },
        ],
        "Alzheimer disease landscape",
    )

    document = build_disease_survey_document(state)
    widget_blocks = [
        block
        for chapter in document["chapters"]
        for block in chapter.get("blocks", [])
        if block.get("type") == "widget"
    ]

    assert widget_blocks, "expected disease IR document to expose chart widgets"


class _FakeLLM:
    model_name = "fake-llm"

    def invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        return "Integrated summary from model."

    def get_model_info(self):
        return {"model_name": self.model_name}


class _MultiParagraphLLM:
    model_name = "fake-llm"

    def invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        return (
            "Integrated first paragraph with 38 assets called out.\n\n"
            "Second paragraph explains why late-stage momentum matters."
        )

    def get_model_info(self):
        return {"model_name": self.model_name}


def test_build_disease_survey_document_uses_structured_tables_for_data_rich_sections():
    state = make_rich_state(summary_text="Overview paragraph.\n\nFollow-up detail paragraph.")

    document = build_disease_survey_document(state)
    chapters = {chapter["chapterId"]: chapter for chapter in document["chapters"]}

    for chapter_id in (
        "sponsor_analysis",
        "target_biology",
        "safety_profile",
        "literature_review",
        "cns_benchmark",
        "market_landscape",
    ):
        blocks = chapters[chapter_id]["blocks"]
        assert any(block.get("type") == "table" for block in blocks), chapter_id
        assert not any(
            "Structured data available" in _paragraph_text(block)
            for block in blocks
            if block.get("type") == "paragraph"
        ), chapter_id


def test_compose_bundle_places_llm_summary_before_executive_widgets():
    state = make_state()

    bundle = compose_disease_survey_report_bundle(state, llm_client=_MultiParagraphLLM())
    executive = next(
        chapter
        for chapter in bundle["document_ir"]["chapters"]
        if chapter["chapterId"] == "executive_summary"
    )
    blocks = executive["blocks"]

    widget_index = next(
        idx for idx, block in enumerate(blocks) if block.get("type") == "widget"
    )
    summary_indices = [
        idx
        for idx, block in enumerate(blocks)
        if block.get("type") == "paragraph"
        and _paragraph_text(block).startswith(("Integrated first paragraph", "Second paragraph"))
    ]

    assert len(summary_indices) == 2
    assert max(summary_indices) < widget_index
    assert "Integrated first paragraph with 38 assets called out." in bundle["markdown"]
    assert "Second paragraph explains why late-stage momentum matters." in bundle["markdown"]


def test_compose_bundle_includes_llm_analysis_metadata():
    state = make_state()

    bundle = compose_disease_survey_report_bundle(state, llm_client=_FakeLLM())

    assert bundle["analysis_metadata"]["summary_source"] == "llm"
    assert bundle["analysis_metadata"]["model_name"] == "fake-llm"
    assert bundle["document_ir"]["chapters"]
    assert "Integrated summary from model." in bundle["markdown"]
