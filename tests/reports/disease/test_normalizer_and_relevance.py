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
    assert normalize_trial_payload({**base, "metadata": {"status": "TERMINATED"}}).status == "TERMINATED"
    assert normalize_trial_payload({**base, "metadata": {"overall_status": "WITHDRAWN"}}).status == "WITHDRAWN"
    assert normalize_trial_payload({**base, "metadata": {"study_status": "SUSPENDED"}}).status == "SUSPENDED"


def test_normalizer_preserves_enrollment_without_removed_endpoint_field():
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

    assert payload["enrollment"] == 100
    assert "primary_endpoint" not in payload


def test_normalizer_preserves_phase_results_outcomes_and_enrollment():
    payload = {
        "hasResults": True,
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT99999999",
                "briefTitle": "Phase 3 antibody study in Alzheimer Disease",
            },
            "statusModule": {
                "overallStatus": "COMPLETED",
                "studyFirstPostDateStruct": {"date": "2024-01-10"},
                "resultsFirstPostDateStruct": {"date": "2026-03-01"},
                "lastUpdatePostDateStruct": {"date": "2026-04-02"},
            },
            "conditionsModule": {"conditions": ["Alzheimer Disease"]},
            "armsInterventionsModule": {
                "interventions": [{"name": "Antibody A"}],
            },
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Sponsor A"},
            },
            "designModule": {
                "phases": ["PHASE3"],
                "studyType": "INTERVENTIONAL",
                "enrollmentInfo": {"count": 1800},
            },
            "outcomesModule": {
                "primaryOutcomes": [{"measure": "Change in CDR-SB"}],
                "secondaryOutcomes": [{"measure": "Change in ADCS-ADL"}],
            },
        },
    }

    record = normalize_trial_payload(payload)

    assert record.nct_number == "NCT99999999"
    assert record.phases == ["PHASE3"]
    assert record.has_results is True
    assert record.study_results == "Results available"
    assert record.results_url == "https://clinicaltrials.gov/study/NCT99999999/results"
    assert record.results_first_posted == date(2026, 3, 1)
    assert record.last_update_posted == date(2026, 4, 2)
    assert record.enrollment == 1800
    assert record.primary_outcome_measures == ["Change in CDR-SB"]
    assert record.secondary_outcome_measures == ["Change in ADCS-ADL"]


def test_normalizer_preserves_flat_outcome_measure_aliases():
    record = normalize_trial_payload(
        {
            "nct_id": "NCT06500004",
            "study_title": "Flat Alzheimer outcome study",
            "status": "COMPLETED",
            "phases": "PHASE2; PHASE3",
            "has_results": True,
            "study_results": "Posted results summary",
            "results_url": "https://example.test/results/NCT06500004",
            "conditions": ["Alzheimer Disease"],
            "interventions": ["Drug B"],
            "sponsor": "Sponsor B",
            "study_type": "INTERVENTIONAL",
            "enrollment": 250,
            "primary_outcome_measures": "ADAS-Cog; CDR-SB",
            "secondary_outcome_measures": ["ADCS-ADL", "NPI"],
        }
    )

    assert record.nct_number == "NCT06500004"
    assert record.phases == ["PHASE2", "PHASE3"]
    assert record.has_results is True
    assert record.study_results == "Posted results summary"
    assert record.results_url == "https://example.test/results/NCT06500004"
    assert record.enrollment == 250
    assert record.primary_outcome_measures == ["ADAS-Cog", "CDR-SB"]
    assert record.secondary_outcome_measures == ["ADCS-ADL", "NPI"]


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


def test_relevance_gate_retains_later_matching_duplicate():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    records = [
        normalize_trial_payload(
            {
                "nct_id": "NCT_DUPLICATE",
                "title": "Parkinson biomarker study",
                "status": "RECRUITING",
                "conditions": ["Parkinson Disease"],
                "interventions": ["Biomarker panel"],
            }
        ),
        normalize_trial_payload(
            {
                "nct_id": "NCT_DUPLICATE",
                "title": "Alzheimer antibody study",
                "status": "RECRUITING",
                "conditions": ["Alzheimer's Disease"],
                "interventions": ["Donanemab"],
            }
        ),
        normalize_trial_payload(
            {
                "nct_id": "NCT_OTHER",
                "title": "Parkinson motor study",
                "status": "RECRUITING",
                "conditions": ["Parkinson Disease"],
                "interventions": ["Levodopa"],
            }
        ),
    ]

    result = DiseaseRelevanceGate().filter_records(records, profile)

    assert [record.study_title for record in result.retained] == ["Alzheimer antibody study"]
    assert [record.nct_number for record in result.retained] == ["NCT_DUPLICATE"]
    assert result.rejected_nct_numbers == ["NCT_OTHER"]
