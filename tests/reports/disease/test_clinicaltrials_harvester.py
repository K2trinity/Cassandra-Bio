from datetime import date, timedelta

from src.reports.disease.clinicaltrials_harvester import (
    ClinicalTrialsConditionDiscovery,
    ClinicalTrialsCompanyHarvester,
    ClinicalTrialsDiseaseHarvester,
)
from src.reports.disease.models import DiseaseProfile
from src.reports.disease.resolver import DiseaseResolver


def _api_study(nct, title, conditions, first_posted, status="RECRUITING"):
    return {
        "protocolSection": {
            "identificationModule": {"nctId": nct, "briefTitle": title},
            "statusModule": {
                "overallStatus": status,
                "studyFirstPostDateStruct": {"date": first_posted},
            },
            "conditionsModule": {"conditions": conditions},
            "armsInterventionsModule": {"interventions": [{"name": "Donanemab"}]},
            "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Sponsor A"}},
            "designModule": {"studyType": "INTERVENTIONAL"},
        }
    }


def _nct_ids(studies):
    return [study["protocolSection"]["identificationModule"]["nctId"] for study in studies]


def _company_profile(company_name="Vertex Pharmaceuticals", sponsor_query=None):
    profile_data = {
        "query": f"Analyze {company_name} clinical pipeline",
        "target_type": "company",
        "company_name": company_name,
        "target_name": company_name,
        "disease_name": company_name,
        "canonical_condition": company_name,
        "condition_terms": [],
        "normalized_terms": [],
        "expert_topic_url": "https://clinicaltrials.gov/search?viewType=Topic",
        "expert_full_match_url": "https://clinicaltrials.gov/search",
    }
    if sponsor_query is not None:
        profile_data["sponsor_query"] = sponsor_query
    return DiseaseProfile(**profile_data)


def test_condition_discovery_prefers_full_match_condition_link():
    html = """
    <a href="/expert-search?term=AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%27s%20Disease%5D%5D&viewType=Card">
      Alzheimer's Disease
    </a>
    """

    def get_text(url):
        assert "viewType=Topic" in url
        return html

    profile = DiseaseResolver().resolve("Alzheimer disease")
    updated = ClinicalTrialsConditionDiscovery(get_text=get_text).discover(profile)

    assert updated.canonical_condition == "Alzheimer Disease"
    assert "Alzheimer's Disease" in updated.condition_terms
    assert "Alzheimer Disease" in updated.condition_terms


def test_condition_discovery_uses_visible_equivalent_topic_link_when_full_match_absent():
    html = """
    <a href="/search?cond=parkinson">Parkinson's Disease</a>
    <a href="/search?cond=alzheimers">Alzheimer's Disease</a>
    """

    profile = DiseaseResolver().resolve("Parkinson disease")
    updated = ClinicalTrialsConditionDiscovery(get_text=lambda url: html).discover(profile)

    assert "Parkinson Disease" in updated.condition_terms
    assert "Parkinson's Disease" in updated.condition_terms
    assert "Alzheimer's Disease" not in updated.condition_terms


def test_harvester_uses_condition_query_and_filters_full_match_locally():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    payload = {
        "studies": [
            _api_study("NCT00000001", "Newest AD", ["Alzheimer's Disease"], "2026-04-20"),
            _api_study("NCT00000002", "Parkinson title mentions Alzheimer", ["Parkinson Disease"], "2026-04-21"),
            _api_study("NCT00000003", "Older AD", ["Alzheimer Disease"], "2025-01-10"),
        ]
    }
    calls = []

    def get_json(url, params):
        calls.append((url, dict(params)))
        if params["query.cond"] != "Alzheimer Disease" or "aggFilters" in params:
            return {"studies": []}
        return payload

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    assert calls[0][0] == "https://clinicaltrials.gov/api/v2/studies"
    assert calls[0][1]["query.cond"] == "Alzheimer Disease"
    assert result.raw_count == 3
    assert _nct_ids(result.studies) == ["NCT00000001", "NCT00000003"]
    assert result.rejected_nct_numbers == ["NCT00000002"]


def test_company_harvester_issues_exact_sponsor_layer_queries():
    profile = _company_profile()
    calls = []

    def get_json(url, params):
        calls.append((url, dict(params)))
        return {"studies": []}

    result = ClinicalTrialsCompanyHarvester(get_json=get_json).fetch_raw_studies(
        profile,
        max_records=80,
    )

    assert [call[0] for call in calls] == [
        "https://clinicaltrials.gov/api/v2/studies",
        "https://clinicaltrials.gov/api/v2/studies",
        "https://clinicaltrials.gov/api/v2/studies",
    ]
    assert [call[1] for call in calls] == [
        {
            "query.spons": "Vertex Pharmaceuticals",
            "filter.overallStatus": "ACTIVE_NOT_RECRUITING",
            "filter.advanced": "AREA[Phase](PHASE2 OR PHASE3)",
            "sort": "PrimaryCompletionDate:asc",
            "pageSize": 30,
            "format": "json",
        },
        {
            "query.spons": "Vertex Pharmaceuticals",
            "filter.overallStatus": "RECRUITING",
            "sort": "StudyFirstPostDate:desc",
            "pageSize": 50,
            "format": "json",
        },
            {
                "query.spons": "Vertex Pharmaceuticals",
                "filter.advanced": "AREA[HasResults]true",
                "sort": "LastUpdatePostDate:desc",
                "pageSize": 20,
                "format": "json",
            },
        ]
    assert result.raw_count == 0


def test_company_harvester_uses_sponsor_query_without_overwriting_company_name():
    profile = _company_profile("Moderna, Inc.", sponsor_query="ModernaTX, Inc.")
    calls = []

    def get_json(url, params):
        calls.append((url, dict(params)))
        if params["sort"] == "StudyFirstPostDate:desc":
            return {
                "studies": [
                    _api_study(
                        "NCT88888881",
                        "Moderna expansion study",
                        ["COVID-19"],
                        "2026-03-01",
                    )
                ]
            }
        return {"studies": []}

    result = ClinicalTrialsCompanyHarvester(get_json=get_json).fetch_raw_studies(
        profile,
        max_records=10,
    )

    assert {call[1]["query.spons"] for call in calls} == {"ModernaTX, Inc."}
    assert result.raw_count == 1
    assert result.studies[0]["metadata"]["company_name"] == "Moderna, Inc."
    assert result.studies[0]["metadata"]["sponsor_query"] == "ModernaTX, Inc."


def test_company_harvester_deduplicates_across_layers_and_preserves_strata():
    profile = _company_profile()

    def get_json(url, params):
        if params["sort"] == "PrimaryCompletionDate:asc":
            return {
                "studies": [
                    _api_study("NCT77777771", "Catalyst duplicate", ["Cancer"], "2026-01-01"),
                    _api_study("NCT77777772", "Catalyst only", ["Cancer"], "2026-01-02"),
                ]
            }
        if params["sort"] == "StudyFirstPostDate:desc":
            return {
                "studies": [
                    _api_study("NCT77777771", "Expansion duplicate", ["Rare Disease"], "2026-01-03"),
                    _api_study("NCT77777773", "Expansion only", ["Rare Disease"], "2026-01-04"),
                ]
            }
        if params["sort"] == "LastUpdatePostDate:desc":
            return {
                "studies": [
                    _api_study("NCT77777771", "Track duplicate", ["Cancer"], "2026-01-05"),
                    _api_study("NCT77777773", "Track expansion duplicate", ["Rare Disease"], "2026-01-06"),
                ]
            }
        raise AssertionError(f"unexpected params: {params}")

    result = ClinicalTrialsCompanyHarvester(get_json=get_json).fetch_raw_studies(
        profile,
        max_records=80,
    )

    assert result.raw_count == 6
    assert _nct_ids(result.studies) == ["NCT77777771", "NCT77777772", "NCT77777773"]

    metadata_by_nct = {
        study["protocolSection"]["identificationModule"]["nctId"]: study["metadata"]
        for study in result.studies
    }
    assert metadata_by_nct["NCT77777771"]["strata"] == [
        "catalyst",
        "track_record",
        "expansion",
    ]
    assert metadata_by_nct["NCT77777771"]["primary_stratum"] == "catalyst"
    assert metadata_by_nct["NCT77777771"]["analysis_target_type"] == "company"
    assert metadata_by_nct["NCT77777771"]["company_name"] == "Vertex Pharmaceuticals"
    assert metadata_by_nct["NCT77777772"]["strata"] == ["catalyst"]
    assert metadata_by_nct["NCT77777772"]["primary_stratum"] == "catalyst"
    assert metadata_by_nct["NCT77777773"]["strata"] == ["track_record", "expansion"]
    assert metadata_by_nct["NCT77777773"]["primary_stratum"] == "track_record"


def test_company_harvester_balances_large_layers_before_capping_to_100():
    profile = _company_profile()

    def make_many(prefix, count):
        return [
            _api_study(
                f"NCT{prefix}{index:05d}",
                f"{prefix} study {index}",
                [f"{prefix} Condition"],
                f"2026-01-{(index % 28) + 1:02d}",
            )
            for index in range(count)
        ]

    def get_json(url, params):
        if params["sort"] == "PrimaryCompletionDate:asc":
            return {"studies": make_many("CAT", 120)}
        if params["sort"] == "StudyFirstPostDate:desc":
            return {"studies": make_many("EXP", 70)}
        if params["sort"] == "LastUpdatePostDate:desc":
            return {"studies": make_many("TRK", 60)}
        raise AssertionError(f"unexpected params: {params}")

    result = ClinicalTrialsCompanyHarvester(get_json=get_json).fetch_raw_studies(
        profile,
        max_records=100,
    )

    nct_ids = _nct_ids(result.studies)
    assert len(nct_ids) == 100
    assert sum(nct_id.startswith("NCTCAT") for nct_id in nct_ids) == 30
    assert sum(nct_id.startswith("NCTEXP") for nct_id in nct_ids) == 50
    assert sum(nct_id.startswith("NCTTRK") for nct_id in nct_ids) == 20


def test_company_harvester_scales_layer_queries_and_selection_for_large_modes():
    profile = _company_profile()
    calls = []

    def make_many(prefix, count):
        return [
            _api_study(
                f"NCT{prefix}{index:05d}",
                f"{prefix} study {index}",
                [f"{prefix} Condition"],
                f"2026-01-{(index % 28) + 1:02d}",
            )
            for index in range(count)
        ]

    def get_json(url, params):
        calls.append(dict(params))
        if params["sort"] == "PrimaryCompletionDate:asc":
            return {"studies": make_many("CAT", 200)}
        if params["sort"] == "StudyFirstPostDate:desc":
            return {"studies": make_many("EXP", 200)}
        if params["sort"] == "LastUpdatePostDate:desc":
            return {"studies": make_many("TRK", 200)}
        raise AssertionError(f"unexpected params: {params}")

    result = ClinicalTrialsCompanyHarvester(get_json=get_json).fetch_raw_studies(
        profile,
        max_records=250,
    )

    assert [call["pageSize"] for call in calls] == [75, 125, 50]
    nct_ids = _nct_ids(result.studies)
    assert len(nct_ids) == 250
    assert sum(nct_id.startswith("NCTCAT") for nct_id in nct_ids) == 75
    assert sum(nct_id.startswith("NCTEXP") for nct_id in nct_ids) == 125
    assert sum(nct_id.startswith("NCTTRK") for nct_id in nct_ids) == 50


def test_harvester_queries_each_literal_condition_term_and_deduplicates_retained_ncts():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    calls = []

    def get_json(url, params):
        calls.append(dict(params))
        if params["query.cond"] == "Alzheimer Disease":
            return {
                "studies": [
                    _api_study("NCT11111111", "AD canonical", ["Alzheimer Disease"], "2026-02-01"),
                ]
            }
        if params["query.cond"] == "Alzheimer's Disease":
            return {
                "studies": [
                    _api_study("NCT11111111", "AD possessive duplicate", ["Alzheimer's Disease"], "2026-02-01"),
                ]
            }
        return {"studies": []}

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    broad_terms = [
        call["query.cond"]
        for call in calls
        if "aggFilters" not in call
    ]
    assert broad_terms == [
        "Alzheimer Disease",
        "Alzheimer's Disease",
        "Alzheimers Disease",
    ]
    assert result.raw_count == 8
    assert _nct_ids(result.studies) == ["NCT11111111"]
    assert result.rejected_nct_numbers == []


def test_harvester_expands_candidate_queries_and_dedupes_before_stratification():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    calls = []

    foundation = _api_study(
        "NCTFOUNDATION",
        "Foundation AD",
        ["Alzheimer Disease"],
        "2024-01-01",
        status="COMPLETED",
    )
    foundation["protocolSection"]["designModule"]["phases"] = ["PHASE3"]
    foundation["hasResults"] = True

    frontier = _api_study(
        "NCTFRONTIER",
        "Frontier AD",
        ["Alzheimer Disease"],
        "2026-04-01",
        status="RECRUITING",
    )
    frontier["protocolSection"]["designModule"]["phases"] = ["EARLY_PHASE1"]

    def get_json(url, params):
        calls.append(dict(params))
        if params["query.cond"] != "Alzheimer Disease":
            return {"studies": []}
        if params.get("aggFilters") == "phase:3 4,status:act com":
            return {"studies": [foundation]}
        if params.get("aggFilters") == "phase:0 1 2,status:rec not":
            return {"studies": [frontier]}
        if params.get("aggFilters") == "results:with":
            return {"studies": [foundation]}
        return {"studies": [foundation]}

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(
        profile,
        max_records=80,
    )

    assert [call.get("aggFilters", "broad") for call in calls[:4]] == [
        "broad",
        "phase:3 4,status:act com",
        "phase:0 1 2,status:rec not",
        "results:with",
    ]
    assert _nct_ids(result.studies) == ["NCTFRONTIER", "NCTFOUNDATION"]
    assert result.raw_count == 4


def test_harvester_counts_raw_rows_before_dedupe_and_keeps_rejected_ncts_unique():
    profile = DiseaseResolver().resolve("Parkinson disease")
    payload = {
        "studies": [
            _api_study("NCT22222221", "Noise 1", ["Alzheimer Disease"], "2026-01-03"),
            _api_study("NCT22222221", "Noise duplicate", ["Alzheimer Disease"], "2026-01-02"),
            _api_study("NCT22222222", "Parkinson", ["Parkinson Disease"], "2026-01-01"),
        ]
    }

    result = ClinicalTrialsDiseaseHarvester(get_json=lambda url, params: payload).fetch_raw_studies(
        profile,
        max_records=50,
    )

    assert result.raw_count == 12
    assert _nct_ids(result.studies) == ["NCT22222222"]
    assert result.rejected_nct_numbers == ["NCT22222221"]


def test_harvester_paginates_with_page_token():
    profile = DiseaseResolver().resolve("Parkinson disease")
    calls = []

    def get_json(url, params):
        calls.append(dict(params))
        if params.get("pageToken") == "PAGE2":
            return {
                "studies": [
                    _api_study("NCT33333332", "Page 2", ["Parkinson Disease"], "2026-02-02"),
                ]
            }
        return {
            "studies": [
                _api_study("NCT33333331", "Page 1", ["Parkinson Disease"], "2026-02-01"),
            ],
            "nextPageToken": "PAGE2",
        }

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    assert len(calls) == 8
    assert "pageToken" not in calls[0]
    assert calls[1]["pageToken"] == "PAGE2"
    assert result.raw_count == 8
    assert _nct_ids(result.studies) == ["NCT33333332", "NCT33333331"]


def test_harvester_stops_on_repeated_page_token():
    profile = DiseaseResolver().resolve("Parkinson disease")
    calls = []

    def get_json(url, params):
        calls.append(dict(params))
        return {
            "studies": [
                _api_study(
                    f"NCT4444444{len(calls)}",
                    f"Loop page {len(calls)}",
                    ["Parkinson Disease"],
                    f"2026-03-0{len(calls)}",
                )
            ],
            "nextPageToken": "LOOP",
        }

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json, max_pages=10).fetch_raw_studies(
        profile,
        max_records=50,
    )

    assert len(calls) == 8
    assert "pageToken" not in calls[0]
    assert calls[1]["pageToken"] == "LOOP"
    assert result.raw_count == 8


def test_harvester_stops_at_max_pages_when_tokens_advance():
    profile = DiseaseResolver().resolve("Parkinson disease")
    calls = []

    def get_json(url, params):
        calls.append(dict(params))
        return {
            "studies": [
                _api_study(
                    f"NCT5555555{len(calls)}",
                    f"Max page {len(calls)}",
                    ["Parkinson Disease"],
                    f"2026-04-0{len(calls)}",
                )
            ],
            "nextPageToken": f"PAGE{len(calls) + 1}",
        }

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json, max_pages=2).fetch_raw_studies(
        profile,
        max_records=50,
    )

    assert len(calls) == 8
    assert result.raw_count == 8


def test_harvester_sorts_by_study_first_posted_desc_and_caps_to_50():
    profile = DiseaseResolver().resolve("Alzheimer disease")
    studies = []
    for i in range(60):
        first_posted = (date(2026, 1, 1) + timedelta(days=i)).isoformat()
        studies.append(
            _api_study(
                f"NCT{i:08d}",
                f"AD trial {i}",
                ["Alzheimer Disease"],
                first_posted,
            )
        )

    def get_json(url, params):
        return {"studies": studies}

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    assert len(result.studies) == 50
    first_dates = [
        study["protocolSection"]["statusModule"]["studyFirstPostDateStruct"]["date"]
        for study in result.studies[:3]
    ]
    assert first_dates == ["2026-03-01", "2026-02-28", "2026-02-27"]
