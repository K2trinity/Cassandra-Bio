from datetime import date

from src.reports.disease.models import ClinicalTrialRecord
from src.reports.disease.risk_engine import RuleBasedRiskEngine, categorize_interventions


def _trial(
    nct_number: str,
    *,
    status: str = "RECRUITING",
    posted: date | None = date(2026, 1, 1),
    interventions: list[str] | None = None,
    intervention_types: list[str] | None = None,
) -> ClinicalTrialRecord:
    return ClinicalTrialRecord(
        study_title=f"Study {nct_number}",
        nct_number=nct_number,
        status=status,
        conditions=["Alzheimer Disease"],
        interventions=interventions or ["Investigational amyloid monoclonal antibody"],
        intervention_types=intervention_types or [],
        sponsor=f"Sponsor {nct_number}",
        study_type="INTERVENTIONAL",
        study_first_posted=posted,
        source_url=f"https://clinicaltrials.gov/study/{nct_number}",
    )


def test_categorize_interventions_covers_taxonomy_examples():
    examples = [
        (["Anti-amyloid monoclonal antibody"], "amyloid antibody"),
        (["A beta mAb infusion"], "amyloid antibody"),
        (["Anti-tau therapy"], "tau therapy"),
        (["Tau PET imaging biomarker"], "diagnostic or imaging"),
        (["Oral beta secretase inhibitor"], "small molecule"),
        (["Stem cell transplant"], "cell therapy"),
        (["Neurostimulation device"], "device"),
        (["Amyloid PET imaging biomarker"], "diagnostic or imaging"),
        (["Cognitive behavioral psychotherapy"], "behavioral intervention"),
        (["Caregiver telehealth care program"], "care delivery"),
        (["Dietary supplement"], "other"),
        ([], ""),
        (["   "], ""),
    ]

    for interventions, expected in examples:
        assert categorize_interventions(interventions) == expected


def test_categorize_interventions_uses_clinicaltrials_source_types_for_named_assets():
    examples = [
        (["VX-147"], ["DRUG"], "drug"),
        (["LY3841136"], ["BIOLOGICAL"], "biological"),
        (["At-home monitoring patch"], ["DEVICE"], "device"),
        (["Sponsor dietary product"], ["DIETARY_SUPPLEMENT"], "dietary supplement"),
        (["Pharmacodynamic assay"], ["DIAGNOSTIC_TEST"], "diagnostic test"),
        (["Gene editing regimen"], ["GENETIC"], "genetic intervention"),
        (["Procedure arm"], ["PROCEDURE"], "procedure"),
        (["Radiation arm"], ["RADIATION"], "radiation"),
        (["Combination product"], ["COMBINATION_PRODUCT"], "combination product"),
    ]

    for interventions, intervention_types, expected in examples:
        assert categorize_interventions(interventions, intervention_types) == expected


def test_clinicaltrials_types_keep_company_pipeline_drugs_out_of_other_category():
    records = [
        _trial("NCTVX00001", interventions=["VX-147"], intervention_types=["DRUG"]),
        _trial("NCTLY00001", interventions=["LY3841136"], intervention_types=["BIOLOGICAL"]),
        _trial("NCTDEV0001", interventions=["At-home monitoring patch"], intervention_types=["DEVICE"]),
    ]

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        records,
        "Vertex Pharmaceuticals",
    )

    assert [risk.intervention_category for risk in risks] == [
        "drug",
        "biological",
        "device",
    ]


def test_old_non_terminal_trial_yields_high_timeline_with_evidence():
    record = _trial("NCT00000001", posted=date(2018, 4, 27), status="RECRUITING")

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        [record],
        "Alzheimer Disease",
    )

    assert risks[0].timeline_signal == "High"
    assert risks[0].timeline_evidence == (
        "Study first posted 2018-04-27; status RECRUITING; age 8.0 years."
    )


def test_completed_old_trial_and_recent_recruiting_trial_yield_low_timeline():
    records = [
        _trial("NCT00000002", posted=date(2018, 4, 27), status="COMPLETED"),
        _trial("NCT00000003", posted=date(2025, 4, 27), status="RECRUITING"),
    ]

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        records,
        "Alzheimer Disease",
    )

    assert [risk.timeline_signal for risk in risks] == ["Low", "Low"]
    assert "status COMPLETED" in risks[0].timeline_evidence
    assert "age 8.0 years" in risks[0].timeline_evidence
    assert "status RECRUITING" in risks[1].timeline_evidence
    assert "age 1.0 years" in risks[1].timeline_evidence


def test_timeline_status_handling_is_case_insensitive_and_age_based_for_paused_or_unknown():
    records = [
        _trial("NCTLOWERDONE", posted=date(2018, 4, 27), status="completed"),
        _trial("NCTUNKNOWN", posted=date(2018, 4, 27), status="Unknown"),
        _trial("NCTSUSPENDED", posted=date(2018, 4, 27), status="SUSPENDED"),
    ]

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        records,
        "Alzheimer Disease",
    )

    assert [risk.timeline_signal for risk in risks] == [
        "Low",
        "High",
        "High",
    ]
    assert "status COMPLETED" in risks[0].timeline_evidence
    assert "status UNKNOWN" in risks[1].timeline_evidence
    assert "status SUSPENDED" in risks[2].timeline_evidence


def test_calendar_year_boundaries_drive_non_terminal_timeline_signal():
    records = [
        _trial("NCTEXACT5", posted=date(2021, 4, 27), status="RECRUITING"),
        _trial("NCTOLDER5", posted=date(2021, 4, 26), status="RECRUITING"),
        _trial("NCTEXACT2", posted=date(2024, 4, 27), status="RECRUITING"),
        _trial("NCTRECENT", posted=date(2024, 4, 28), status="RECRUITING"),
    ]

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        records,
        "Alzheimer Disease",
    )

    assert [risk.timeline_signal for risk in risks] == [
        "Medium",
        "High",
        "Medium",
        "Low",
    ]
    assert "age 5.0 years" in risks[0].timeline_evidence


def test_missing_first_posted_yields_data_insufficient_timeline():
    record = _trial("NCT00000004", posted=None, status="RECRUITING")

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        [record],
        "Alzheimer Disease",
    )

    assert risks[0].timeline_signal == "Data insufficient"
    assert risks[0].timeline_evidence == (
        "Study first posted missing; status RECRUITING; age unavailable."
    )


def test_competition_counts_high_for_eight_amyloid_and_low_for_single_cell_therapy():
    records = [
        _trial(
            f"NCTAMY{i:05d}",
            interventions=[f"Amyloid monoclonal antibody {i}"],
        )
        for i in range(8)
    ]
    records.append(
        _trial(
            "NCTCELL00001",
            interventions=["Autologous stem cell therapy"],
        )
    )

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        records,
        "Alzheimer Disease",
    )

    amyloid_risks = [risk for risk in risks if risk.intervention_category == "amyloid antibody"]
    cell_risk = next(risk for risk in risks if risk.intervention_category == "cell therapy")

    assert len(amyloid_risks) == 8
    assert {risk.competition_signal for risk in amyloid_risks} == {"High"}
    assert amyloid_risks[0].competition_evidence == (
        "8 retained Alzheimer Disease studies share intervention category amyloid antibody."
    )
    assert cell_risk.competition_signal == "Low"
    assert cell_risk.competition_evidence == (
        "1 retained Alzheimer Disease studies share intervention category cell therapy."
    )
    assert cell_risk.nct_number == "NCTCELL00001"
    assert cell_risk.study_title == "Study NCTCELL00001"
    assert cell_risk.sponsor == "Sponsor NCTCELL00001"
    assert cell_risk.status == "RECRUITING"


def test_build_preserves_category_per_input_when_nct_numbers_repeat():
    records = [
        _trial("NCTDUPLICATE", interventions=["Amyloid monoclonal antibody"]),
        _trial("NCTDUPLICATE", interventions=["Autologous stem cell therapy"]),
    ]

    risks = RuleBasedRiskEngine(current_date=date(2026, 4, 27)).build(
        records,
        "Alzheimer Disease",
    )

    assert [risk.intervention_category for risk in risks] == [
        "amyloid antibody",
        "cell therapy",
    ]
