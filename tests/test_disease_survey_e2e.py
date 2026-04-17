# tests/test_disease_survey_e2e.py
"""End-to-end integration tests: raw rows → aggregate → render → compose → ReportWriterAgent."""
import pytest

from src.engines.report_engine.disease_survey import aggregate_survey_data
from src.engines.report_engine.disease_survey.composer import compose_disease_survey_report

# Try to import ReportWriterAgent — adjust path based on what exists
try:
    from src.agents.report_writer import ReportWriterAgent
    HAS_AGENT = True
except ImportError:
    HAS_AGENT = False


# ── Realistic AD pipeline fixture ────────────────────────────────────

AD_ROWS = [
    {
        "source": "ClinicalTrials",
        "nct_id": "NCT01767311",
        "title": "Clarity AD — Lecanemab Phase 3",
        "summary": "Phase 3 trial of lecanemab targeting amyloid beta in early Alzheimer's disease.",
        "metadata": {
            "intervention": "Lecanemab (BAN2401), anti-Aβ monoclonal antibody",
            "sponsor": "Eisai",
            "phase": "Phase 3",
            "status": "Completed",
            "enrollment": "1795",
            "primary_endpoint": "CDR-SB change from baseline at 18 months",
            "ae_grade3plus": "ARIA-E 12.6%, ARIA-H 17.3%",
        },
    },
    {
        "source": "ClinicalTrials",
        "nct_id": "NCT04468659",
        "title": "TRAILBLAZER-ALZ 2 — Donanemab Phase 3",
        "summary": "Phase 3 trial of donanemab targeting N3pG-Aβ in early symptomatic AD.",
        "metadata": {
            "intervention": "Donanemab, anti-N3pG-Aβ monoclonal antibody",
            "sponsor": "Eli Lilly",
            "phase": "Phase 3",
            "status": "Completed",
            "enrollment": "1736",
            "primary_endpoint": "iADRS change from baseline",
            "ae_grade3plus": "ARIA-E 24.0%",
        },
    },
    {
        "source": "ClinicalTrials",
        "nct_id": "NCT05310071",
        "title": "AHEAD 3-45 — A4 Study Extension",
        "summary": "Phase 3 prevention trial in cognitively unimpaired amyloid-positive adults.",
        "metadata": {
            "intervention": "Lecanemab, anti-Aβ monoclonal antibody",
            "sponsor": "Eisai",
            "phase": "Phase 3",
            "status": "Recruiting",
            "enrollment": "1400",
            "primary_endpoint": "Preclinical Alzheimer Cognitive Composite",
        },
    },
    {
        "source": "PubMed",
        "pmid": "36449413",
        "title": "Lecanemab in Early Alzheimer's Disease",
        "summary": "Phase 3 trial results showing 27% slowing of cognitive decline.",
        "journal": "New England Journal of Medicine",
        "year": 2023,
        "authors": "van Dyck CH et al.",
        "doi": "10.1056/NEJMoa2212948",
    },
    {
        "source": "PubMed",
        "pmid": "37454592",
        "title": "Donanemab in Early Symptomatic Alzheimer Disease",
        "summary": "TRAILBLAZER-ALZ 2 results: 35% slowing in early tau population.",
        "journal": "JAMA",
        "year": 2023,
        "authors": "Sims JR et al.",
        "doi": "10.1001/jama.2023.13239",
    },
    {
        "source": "PubMed",
        "pmid": "38001236",
        "title": "ARIA Management in Anti-Amyloid Therapy",
        "summary": "Guidelines for monitoring and managing ARIA in clinical practice.",
        "journal": "Lancet Neurology",
        "year": 2024,
        "authors": "Cummings J et al.",
    },
]


# ── Full pipeline E2E ─────────────────────────────────────────────────

def test_e2e_aggregate_produces_valid_state():
    state = aggregate_survey_data(AD_ROWS, "Alzheimer's disease anti-amyloid pipeline")
    assert state.disease_name == "Alzheimer's Disease"
    assert len(state.trials) == 3
    assert len(state.literature) == 3
    assert len(state.drug_assets) >= 2
    assert len(state.sponsors) >= 2


def test_e2e_compose_produces_all_sections():
    state = aggregate_survey_data(AD_ROWS, "Alzheimer's disease pipeline")
    report = compose_disease_survey_report(state)
    required = [
        "executive_summary", "drug_pipeline", "trial_landscape",
        "sponsor_analysis", "target_biology", "safety_profile",
        "literature_review", "cns_benchmark", "market_landscape",
    ]
    for section in required:
        assert section in report, f"Missing section: {section}"


def test_e2e_executive_summary_counts():
    state = aggregate_survey_data(AD_ROWS, "AD pipeline")
    report = compose_disease_survey_report(state)
    summary = report["executive_summary"]
    assert summary["total_trials"] == 3
    assert summary["total_assets"] >= 2
    assert summary["total_sponsors"] >= 2


def test_e2e_safety_profile_captures_aria():
    state = aggregate_survey_data(AD_ROWS, "AD pipeline")
    report = compose_disease_survey_report(state)
    safety = report["safety_profile"]
    assert safety["trials_with_ae_data"] >= 2
    ae_texts = " ".join(e["ae_grade3plus"] or "" for e in safety["ae_entries"])
    assert "ARIA" in ae_texts


def test_e2e_literature_review_by_year():
    state = aggregate_survey_data(AD_ROWS, "AD pipeline")
    report = compose_disease_survey_report(state)
    by_year = report["literature_review"]["by_year"]
    assert by_year.get(2023) == 2
    assert by_year.get(2024) == 1


def test_e2e_drug_pipeline_phase_breakdown():
    state = aggregate_survey_data(AD_ROWS, "AD pipeline")
    report = compose_disease_survey_report(state)
    by_phase = report["drug_pipeline"]["by_phase"]
    assert by_phase.get("Phase 3", 0) >= 2


def test_e2e_sponsor_deduplication():
    state = aggregate_survey_data(AD_ROWS, "AD pipeline")
    report = compose_disease_survey_report(state)
    sponsor_names = [s["company_name"] for s in report["sponsor_analysis"]["sponsors"]]
    assert len(sponsor_names) == len(set(sponsor_names))
    assert "Eisai" in sponsor_names


def test_e2e_eisai_pipeline_count():
    state = aggregate_survey_data(AD_ROWS, "AD pipeline")
    report = compose_disease_survey_report(state)
    sponsors = {s["company_name"]: s for s in report["sponsor_analysis"]["sponsors"]}
    assert sponsors["Eisai"]["pipeline_count"] >= 1


@pytest.mark.skipif(not HAS_AGENT, reason="ReportWriterAgent not available")
def test_e2e_via_report_writer_agent():
    agent = ReportWriterAgent()
    report = agent.run("disease_survey", AD_ROWS, query="Alzheimer's disease pipeline")
    assert "executive_summary" in report
    assert report["executive_summary"]["total_trials"] == 3


@pytest.mark.skipif(not HAS_AGENT, reason="ReportWriterAgent not available")
def test_e2e_agent_empty_rows():
    agent = ReportWriterAgent()
    report = agent.run("disease_survey", [], query="empty test")
    assert report["drug_pipeline"]["assets"] == []
    assert report["trial_landscape"]["total"] == 0
