# tests/test_disease_survey_aggregator.py
"""Tests for disease survey aggregator functions."""
import pytest

from src.engines.report_engine.disease_survey.aggregator import (
    aggregate_survey_data,
    build_chart_data,
    compute_cns_benchmark,
    compute_publication_trend,
    group_by_phase,
    group_by_sponsor,
    group_by_target,
)
from src.engines.report_engine.disease_survey.models import (
    DiseaseSurveyState,
    DrugAsset,
    LiteratureRecord,
    TrialRecord,
)


# ── Fixtures ──────────────────────────────────────────────────────────

SAMPLE_PUBMED_ROW = {
    "source": "PubMed",
    "pmid": "38001234",
    "title": "BACE1 inhibitor trial results in early Alzheimer's",
    "summary": "A Phase 2 trial of verubecestat targeting BACE1 showed no efficacy.",
    "journal": "NEJM",
    "year": 2023,
    "authors": "Smith J et al.",
    "doi": "10.1000/test",
}

SAMPLE_TRIAL_ROW = {
    "source": "ClinicalTrials",
    "nct_id": "NCT05310071",
    "title": "Lecanemab Phase 3 Extension Study",
    "summary": "Open-label extension of Clarity AD evaluating long-term safety.",
    "metadata": {
        "intervention": "Lecanemab (BAN2401), anti-Aβ monoclonal antibody",
        "sponsor": "Eisai",
        "phase": "Phase 3",
        "status": "Recruiting",
        "enrollment": "1500",
        "primary_endpoint": "CDR-SB change from baseline",
        "ae_grade3plus": "ARIA-E 12.6%",
    },
}

SAMPLE_TRIAL_ROW_2 = {
    "source": "ClinicalTrials",
    "nct_id": "NCT04468659",
    "title": "Donanemab TRAILBLAZER-ALZ 2",
    "summary": "Phase 3 trial of donanemab targeting N3pG-Aβ in early AD.",
    "metadata": {
        "intervention": "Donanemab, anti-Aβ monoclonal antibody",
        "sponsor": "Eli Lilly",
        "phase": "Phase 3",
        "status": "Completed",
        "enrollment": "1736",
        "primary_endpoint": "iADRS change",
    },
}


# ── aggregate_survey_data ─────────────────────────────────────────────

def test_aggregate_empty_rows():
    state = aggregate_survey_data([], "AD pipeline")
    assert isinstance(state, DiseaseSurveyState)
    assert state.disease_name == "AD pipeline"
    assert state.drug_assets == []
    assert state.trials == []
    assert state.literature == []


def test_aggregate_pubmed_row():
    state = aggregate_survey_data([SAMPLE_PUBMED_ROW], "AD pipeline")
    assert len(state.literature) == 1
    assert state.literature[0].pmid == "38001234"
    assert state.literature[0].journal == "NEJM"


def test_aggregate_trial_row():
    state = aggregate_survey_data([SAMPLE_TRIAL_ROW], "AD pipeline")
    assert len(state.trials) == 1
    assert state.trials[0].nct_id == "NCT05310071"
    assert state.trials[0].sponsor == "Eisai"
    assert len(state.drug_assets) >= 1
    assert len(state.sponsors) >= 1


def test_aggregate_mixed_rows():
    rows = [SAMPLE_PUBMED_ROW, SAMPLE_TRIAL_ROW, SAMPLE_TRIAL_ROW_2]
    state = aggregate_survey_data(rows, "AD drug pipeline survey")
    assert len(state.literature) == 1
    assert len(state.trials) == 2
    assert len(state.drug_assets) >= 2
    assert len(state.sponsors) >= 2
    assert state.query == "AD drug pipeline survey"


def test_aggregate_deduplicates_sponsors():
    row_a = {**SAMPLE_TRIAL_ROW}
    row_b = {**SAMPLE_TRIAL_ROW, "nct_id": "NCT99999999", "title": "Another Eisai trial"}
    row_b["metadata"] = {**SAMPLE_TRIAL_ROW["metadata"]}
    state = aggregate_survey_data([row_a, row_b], "test")
    eisai_sponsors = [s for s in state.sponsors if s.company_name == "Eisai"]
    assert len(eisai_sponsors) == 1
    assert eisai_sponsors[0].pipeline_count >= 1


def test_aggregate_backfills_alternate_asset_and_sponsor_fields():
    row = {
        "source": "ClinicalTrials",
        "nct_id": "NCT77777777",
        "title": "Alternate metadata trial",
        "summary": "Backfill test",
        "metadata": {
            "interventions": "Drug Z",
            "trial_sponsor": "Sponsor Z",
            "phase": "Phase 2",
            "status": "Recruiting",
        },
    }

    state = aggregate_survey_data([row], "test")

    assert state.drug_assets[0].asset_name == "Drug Z"
    assert state.trials[0].sponsor == "Sponsor Z"
    assert state.sponsors[0].company_name == "Sponsor Z"


def test_aggregate_records_field_audit_metadata():
    row = {
        "source": "ClinicalTrials",
        "nct_id": "NCT88888888",
        "title": "Missing sponsor trial",
        "summary": "Audit test",
        "metadata": {
            "interventions": "Drug Audit",
            "phase": "Phase 1",
        },
    }

    state = aggregate_survey_data([row], "test")

    audit = state.metadata.get("field_audit", {})
    assert "missing_asset_count" in audit
    assert "missing_sponsor_count" in audit
    assert audit["missing_sponsor_count"] >= 1


# ── group_by helpers ──────────────────────────────────────────────────

def test_group_by_target():
    assets = [
        DrugAsset(asset_name="A", targets=["Aβ", "Tau"], sponsor="X"),
        DrugAsset(asset_name="B", targets=["Aβ"], sponsor="Y"),
        DrugAsset(asset_name="C", targets=["TREM2"], sponsor="Z"),
    ]
    groups = group_by_target(assets)
    assert len(groups["Aβ"]) == 2
    assert len(groups["Tau"]) == 1
    assert len(groups["TREM2"]) == 1


def test_group_by_phase():
    trials = [
        TrialRecord(nct_id="A", title="T1", phase="Phase 1"),
        TrialRecord(nct_id="B", title="T2", phase="Phase 3"),
        TrialRecord(nct_id="C", title="T3", phase="Phase 3"),
        TrialRecord(nct_id="D", title="T4", phase=None),
    ]
    groups = group_by_phase(trials)
    assert groups["Phase 1"] == 1
    assert groups["Phase 3"] == 2
    assert groups["Unknown"] == 1


def test_group_by_sponsor():
    assets = [
        DrugAsset(asset_name="A", sponsor="Eisai"),
        DrugAsset(asset_name="B", sponsor="Eisai"),
        DrugAsset(asset_name="C", sponsor="Lilly"),
    ]
    sponsors = group_by_sponsor(assets)
    assert sponsors["Eisai"].pipeline_count == 2
    assert sponsors["Lilly"].pipeline_count == 1


# ── compute helpers ───────────────────────────────────────────────────

def test_compute_publication_trend():
    lit = [
        LiteratureRecord(pmid="1", title="A", year=2022),
        LiteratureRecord(pmid="2", title="B", year=2022),
        LiteratureRecord(pmid="3", title="C", year=2024),
        LiteratureRecord(pmid="4", title="D", year=None),
    ]
    trend = compute_publication_trend(lit, window=5)
    assert trend[2022] == 2
    assert trend[2024] == 1
    assert None not in trend


def test_compute_cns_benchmark():
    lit = [
        LiteratureRecord(pmid="1", title="Aβ clearance study", journal="Nature Neuroscience", year=2023),
        LiteratureRecord(pmid="2", title="Tau PET imaging", journal="Lancet Neurology", year=2022),
        LiteratureRecord(pmid="3", title="Random paper", journal="Some Journal", year=2023),
    ]
    targets = ["Aβ", "Tau", "TREM2"]
    benchmark = compute_cns_benchmark(lit, targets)
    assert len(benchmark) == 3
    ab_entry = next(e for e in benchmark if e.target_name == "Aβ")
    assert ab_entry.top_journal_citations >= 1
    assert ab_entry.matched is True
    trem2_entry = next(e for e in benchmark if e.target_name == "TREM2")
    assert trem2_entry.top_journal_citations == 0


# ── build_chart_data ──────────────────────────────────────────────────

def test_build_chart_data_pie():
    group = {"Aβ": 5, "Tau": 3, "TREM2": 1}
    chart = build_chart_data(group, "pie")
    assert "labels" in chart
    assert "datasets" in chart
    assert len(chart["labels"]) == 3
    assert chart["datasets"][0]["data"] == [5, 3, 1]


def test_build_chart_data_bar():
    group = {"Phase 1": 2, "Phase 2": 5, "Phase 3": 3}
    chart = build_chart_data(group, "bar")
    assert chart["labels"] == ["Phase 1", "Phase 2", "Phase 3"]
    assert len(chart["datasets"]) == 1
