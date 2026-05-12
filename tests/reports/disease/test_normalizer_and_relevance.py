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


def test_normalizer_preserves_clinicaltrials_intervention_types():
    payload = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT06500009", "briefTitle": "Company asset trial"},
            "statusModule": {"overallStatus": "RECRUITING"},
            "conditionsModule": {"conditions": ["Cystic Fibrosis"]},
            "armsInterventionsModule": {
                "interventions": [
                    {"type": "DRUG", "name": "VX-147"},
                    {"type": "BIOLOGICAL", "name": "LY3841136"},
                    {"type": "DIAGNOSTIC_TEST", "name": "Pharmacodynamic assay"},
                ],
            },
        },
    }

    record = normalize_trial_payload(payload)

    assert record.interventions == ["VX-147", "LY3841136", "Pharmacodynamic assay"]
    assert record.intervention_types == ["DRUG", "BIOLOGICAL", "DIAGNOSTIC_TEST"]


def test_normalizer_preserves_clinicaltrials_why_stopped_reason():
    payload = {
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT_STOPPED",
                "briefTitle": "Stopped Alzheimer Disease study",
            },
            "statusModule": {
                "overallStatus": "TERMINATED",
                "whyStopped": "Business decision after interim portfolio review.",
            },
        }
    }

    record = normalize_trial_payload(payload)

    assert record.status == "TERMINATED"
    assert record.why_stopped == "Business decision after interim portfolio review."


def test_normalizer_preserves_clinicaltrials_v2_results_phase_outcomes_and_strata():
    payload = {
        "hasResults": True,
        "metadata": {
            "strata": ["track_record", "catalyst"],
            "primary_stratum": "catalyst",
        },
        "protocolSection": {
            "identificationModule": {
                "nctId": "NCT06500004",
                "briefTitle": "Phase 2 sponsor trial",
            },
            "statusModule": {
                "overallStatus": "ACTIVE_NOT_RECRUITING",
                "resultsFirstPostDateStruct": {"date": "2026-03-15"},
            },
            "conditionsModule": {"conditions": ["Cystic Fibrosis"]},
            "sponsorCollaboratorsModule": {
                "leadSponsor": {"name": "Vertex Pharmaceuticals"}
            },
            "designModule": {
                "studyType": "INTERVENTIONAL",
                "phases": ["PHASE2", "PHASE3"],
                "enrollmentInfo": {"count": 480},
            },
            "outcomesModule": {
                "primaryOutcomes": [
                    {"measure": "Change in ppFEV1"},
                    {"measure": "Pulmonary exacerbation rate"},
                ],
                "secondaryOutcomes": [{"measure": "Safety and tolerability"}],
            },
        },
    }

    record = normalize_trial_payload(payload)

    assert record.phases == ["PHASE2", "PHASE3"]
    assert record.has_results is True
    assert record.study_results == "Results available"
    assert record.results_url == "https://clinicaltrials.gov/study/NCT06500004/results"
    assert record.results_first_posted == date(2026, 3, 15)
    assert record.enrollment == 480
    assert record.primary_outcome_measures == [
        "Change in ppFEV1",
        "Pulmonary exacerbation rate",
    ]
    assert record.secondary_outcome_measures == ["Safety and tolerability"]
    assert record.strata == ["track_record", "catalyst"]
    assert record.primary_stratum == "catalyst"


def test_normalizer_marks_absent_clinicaltrials_results_without_results_url():
    record = normalize_trial_payload(
        {
            "hasResults": False,
            "protocolSection": {
                "identificationModule": {"nctId": "NCT06500005", "briefTitle": "No results trial"},
                "statusModule": {"overallStatus": "RECRUITING"},
            },
        }
    )

    assert record.has_results is False
    assert record.study_results == "No posted results"
    assert record.results_url == ""


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


def test_normalizer_defaults_results_url_only_when_results_are_posted():
    base = {
        "nct_id": "NCT06500008",
        "study_title": "Flat Alzheimer results link study",
        "status": "COMPLETED",
        "conditions": ["Alzheimer Disease"],
        "interventions": ["Drug B"],
        "sponsor": "Sponsor B",
        "study_type": "INTERVENTIONAL",
    }

    without_results = normalize_trial_payload({**base, "has_results": False})
    with_results = normalize_trial_payload({**base, "has_results": True})
    explicit_url = normalize_trial_payload(
        {
            **base,
            "has_results": False,
            "results_url": "https://example.test/results/NCT06500008",
        }
    )

    assert without_results.results_url == ""
    assert with_results.results_url == "https://clinicaltrials.gov/study/NCT06500008/results"
    assert explicit_url.results_url == "https://example.test/results/NCT06500008"


def test_normalizer_preserves_flat_and_metadata_stratum_fields():
    flat = normalize_trial_payload(
        {
            "nct_id": "NCT06500007",
            "study_title": "Flat stratum study",
            "status": "COMPLETED",
            "conditions": ["Alzheimer Disease"],
            "interventions": ["Drug E"],
            "strata": ["evidence", {"label": "foundation"}],
            "primary_stratum": "evidence",
            "source_url": "https://clinicaltrials.gov/study/NCT06500007",
        }
    )
    metadata = normalize_trial_payload(
        {
            "nct_id": "NCT06500008",
            "study_title": "Metadata stratum study",
            "status": "RECRUITING",
            "conditions": ["Alzheimer Disease"],
            "interventions": ["Drug F"],
            "metadata": {
                "strata": "frontier",
                "primary_stratum": "frontier",
            },
            "source_url": "https://clinicaltrials.gov/study/NCT06500008",
        }
    )

    assert flat.strata == ["evidence", "foundation"]
    assert flat.primary_stratum == "evidence"
    assert metadata.strata == ["frontier"]
    assert metadata.primary_stratum == "frontier"


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


def test_normalizer_canonicalizes_human_readable_flat_phase_labels():
    single_phase = normalize_trial_payload(
        {
            "nct_id": "NCT06500005",
            "study_title": "Flat phase 3 study",
            "status": "COMPLETED",
            "phases": "Phase 3",
            "conditions": ["Alzheimer Disease"],
            "interventions": ["Drug C"],
            "source_url": "https://clinicaltrials.gov/study/NCT06500005",
        }
    )
    multi_phase = normalize_trial_payload(
        {
            "nct_id": "NCT06500006",
            "study_title": "Flat phase 1 and 2 study",
            "status": "RECRUITING",
            "phase": "Phase 1; Phase 2",
            "conditions": ["Alzheimer Disease"],
            "interventions": ["Drug D"],
            "source_url": "https://clinicaltrials.gov/study/NCT06500006",
        }
    )

    assert single_phase.phases == ["PHASE3"]
    assert multi_phase.phases == ["PHASE1", "PHASE2"]


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
