# tests/test_disease_survey_renderer.py
"""Tests for disease survey renderer functions."""
import pytest

from src.engines.report_engine.disease_survey.models import (
    CNSBenchmarkEntry,
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    SponsorProfile,
    TrialRecord,
)
from src.engines.report_engine.disease_survey.renderer import (
    render_cns_benchmark,
    render_drug_pipeline,
    render_executive_summary,
    render_literature_review,
    render_market_landscape,
    render_safety_profile,
    render_sponsor_analysis,
    render_target_biology,
    render_trial_landscape,
)


# ── Fixtures ──────────────────────────────────────────────────────────

def make_state(**kwargs) -> DiseaseSurveyState:
    defaults = dict(
        disease_name="Alzheimer's Disease",
        query="AD drug pipeline",
        drug_assets=[
            DrugAsset(asset_name="Lecanemab", targets=["Aβ"], sponsor="Eisai", phase="Phase 3", modality="Monoclonal Antibody", status="Approved"),
            DrugAsset(asset_name="Donanemab", targets=["Aβ"], sponsor="Eli Lilly", phase="Phase 3", modality="Monoclonal Antibody", status="Completed"),
            DrugAsset(asset_name="GV-971", targets=["Neuroinflammation"], sponsor="Green Valley", phase="Phase 3", modality="Small Molecule", status="Approved"),
        ],
        trials=[
            TrialRecord(nct_id="NCT01767311", title="Clarity AD", sponsor="Eisai", phase="Phase 3", status="Completed", enrollment="1795", primary_endpoint="CDR-SB", ae_grade3plus="ARIA-E 12.6%"),
            TrialRecord(nct_id="NCT04468659", title="TRAILBLAZER-ALZ 2", sponsor="Eli Lilly", phase="Phase 3", status="Completed", enrollment="1736", primary_endpoint="iADRS"),
        ],
        sponsors=[
            SponsorProfile(company_name="Eisai", pipeline_count=2, lead_phase="Phase 3", ticker="ESALY", market_cap=30e9),
            SponsorProfile(company_name="Eli Lilly", pipeline_count=1, lead_phase="Phase 3", ticker="LLY", market_cap=700e9),
        ],
        literature=[
            LiteratureRecord(pmid="38001234", title="Lecanemab in early AD", journal="NEJM", year=2023, authors="van Dyck CH et al."),
            LiteratureRecord(pmid="38001235", title="Donanemab Phase 3 results", journal="JAMA", year=2023),
            LiteratureRecord(pmid="38001236", title="ARIA management guidelines", journal="Lancet Neurology", year=2024),
        ],
        cns_benchmark=[
            CNSBenchmarkEntry(target_name="Aβ", publication_count_5yr=120, trial_count_5yr=45, top_journal_citations=30, trend="rising", matched=True),
            CNSBenchmarkEntry(target_name="Tau", publication_count_5yr=80, trial_count_5yr=20, top_journal_citations=15, trend="stable", matched=False),
        ],
        summary_text="Alzheimer's disease pipeline shows strong Phase 3 activity with two approved anti-amyloid therapies.",
    )
    defaults.update(kwargs)
    return DiseaseSurveyState(**defaults)


FULL_STATE = make_state()
EMPTY_STATE = DiseaseSurveyState(disease_name="Unknown Disease", query="test")


# ── render_executive_summary ──────────────────────────────────────────

def test_executive_summary_keys():
    result = render_executive_summary(FULL_STATE)
    assert "disease_name" in result
    assert "total_assets" in result
    assert "total_trials" in result
    assert "total_sponsors" in result
    assert "summary_text" in result
    assert "phase_breakdown" in result


def test_executive_summary_counts():
    result = render_executive_summary(FULL_STATE)
    assert result["total_assets"] == 3
    assert result["total_trials"] == 2
    assert result["total_sponsors"] == 2


def test_executive_summary_empty():
    result = render_executive_summary(EMPTY_STATE)
    assert result["total_assets"] == 0
    assert result["phase_breakdown"] == {}


# ── render_drug_pipeline ──────────────────────────────────────────────

def test_drug_pipeline_keys():
    result = render_drug_pipeline(FULL_STATE)
    assert "assets" in result
    assert "by_phase" in result
    assert "by_target" in result
    assert "by_modality" in result


def test_drug_pipeline_assets_structure():
    result = render_drug_pipeline(FULL_STATE)
    assert len(result["assets"]) == 3
    first = result["assets"][0]
    assert "asset_name" in first
    assert "phase" in first
    assert "targets" in first
    assert "sponsor" in first


def test_drug_pipeline_by_phase():
    result = render_drug_pipeline(FULL_STATE)
    assert result["by_phase"].get("Phase 3") == 3


def test_drug_pipeline_empty():
    result = render_drug_pipeline(EMPTY_STATE)
    assert result["assets"] == []
    assert result["by_phase"] == {}


# ── render_trial_landscape ────────────────────────────────────────────

def test_trial_landscape_keys():
    result = render_trial_landscape(FULL_STATE)
    assert "trials" in result
    assert "by_phase" in result
    assert "by_status" in result
    assert "total" in result


def test_trial_landscape_total():
    result = render_trial_landscape(FULL_STATE)
    assert result["total"] == 2


def test_trial_landscape_trial_structure():
    result = render_trial_landscape(FULL_STATE)
    trial = result["trials"][0]
    assert "nct_id" in trial
    assert "title" in trial
    assert "sponsor" in trial
    assert "phase" in trial
    assert "enrollment" in trial


# ── render_sponsor_analysis ───────────────────────────────────────────

def test_sponsor_analysis_keys():
    result = render_sponsor_analysis(FULL_STATE)
    assert "sponsors" in result
    assert "total" in result


def test_sponsor_analysis_structure():
    result = render_sponsor_analysis(FULL_STATE)
    assert result["total"] == 2
    sponsor = result["sponsors"][0]
    assert "company_name" in sponsor
    assert "pipeline_count" in sponsor
    assert "lead_phase" in sponsor


def test_sponsor_analysis_empty():
    result = render_sponsor_analysis(EMPTY_STATE)
    assert result["sponsors"] == []
    assert result["total"] == 0


# ── render_target_biology ─────────────────────────────────────────────

def test_target_biology_keys():
    result = render_target_biology(FULL_STATE)
    assert "targets" in result
    assert "total_unique" in result


def test_target_biology_deduplicates():
    result = render_target_biology(FULL_STATE)
    target_names = [t["target_name"] for t in result["targets"]]
    assert len(target_names) == len(set(target_names))


def test_target_biology_empty():
    result = render_target_biology(EMPTY_STATE)
    assert result["targets"] == []
    assert result["total_unique"] == 0


# ── render_safety_profile ─────────────────────────────────────────────

def test_safety_profile_keys():
    result = render_safety_profile(FULL_STATE)
    assert "trials_with_ae_data" in result
    assert "ae_entries" in result
    assert "total_trials" in result


def test_safety_profile_ae_entries():
    result = render_safety_profile(FULL_STATE)
    assert result["trials_with_ae_data"] >= 1
    entry = result["ae_entries"][0]
    assert "nct_id" in entry
    assert "ae_grade3plus" in entry


# ── render_literature_review ──────────────────────────────────────────

def test_literature_review_keys():
    result = render_literature_review(FULL_STATE)
    assert "records" in result
    assert "total" in result
    assert "by_year" in result
    assert "top_journals" in result


def test_literature_review_total():
    result = render_literature_review(FULL_STATE)
    assert result["total"] == 3


def test_literature_review_by_year():
    result = render_literature_review(FULL_STATE)
    assert result["by_year"].get(2023) == 2
    assert result["by_year"].get(2024) == 1


# ── render_cns_benchmark ──────────────────────────────────────────────

def test_cns_benchmark_keys():
    result = render_cns_benchmark(FULL_STATE)
    assert "entries" in result
    assert "matched_targets" in result
    assert "total" in result


def test_cns_benchmark_matched():
    result = render_cns_benchmark(FULL_STATE)
    matched = result["matched_targets"]
    assert "Aβ" in matched
    assert "Tau" not in matched


# ── render_market_landscape ───────────────────────────────────────────

def test_market_landscape_keys():
    result = render_market_landscape(FULL_STATE)
    assert "sponsors_with_financials" in result
    assert "total_sponsors" in result


def test_market_landscape_financials():
    result = render_market_landscape(FULL_STATE)
    entries = result["sponsors_with_financials"]
    assert len(entries) >= 1
    entry = entries[0]
    assert "company_name" in entry
    assert "ticker" in entry
    assert "market_cap" in entry
