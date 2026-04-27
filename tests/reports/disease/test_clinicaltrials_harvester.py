from datetime import date, timedelta

from src.reports.disease.clinicaltrials_harvester import (
    ClinicalTrialsConditionDiscovery,
    ClinicalTrialsDiseaseHarvester,
)
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
        if params["query.cond"] != "Alzheimer Disease":
            return {"studies": []}
        return payload

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    assert calls[0][0] == "https://clinicaltrials.gov/api/v2/studies"
    assert calls[0][1]["query.cond"] == "Alzheimer Disease"
    assert result.raw_count == 3
    assert _nct_ids(result.studies) == ["NCT00000001", "NCT00000003"]
    assert result.rejected_nct_numbers == ["NCT00000002"]


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

    assert [call["query.cond"] for call in calls] == [
        "Alzheimer Disease",
        "Alzheimer's Disease",
        "Alzheimers Disease",
    ]
    assert result.raw_count == 2
    assert _nct_ids(result.studies) == ["NCT11111111"]
    assert result.rejected_nct_numbers == []


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

    assert result.raw_count == 3
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

    assert len(calls) == 2
    assert "pageToken" not in calls[0]
    assert calls[1]["pageToken"] == "PAGE2"
    assert result.raw_count == 2
    assert _nct_ids(result.studies) == ["NCT33333332", "NCT33333331"]


def test_harvester_stops_on_repeated_page_token():
    profile = DiseaseResolver().resolve("Parkinson disease")
    calls = []

    def get_json(url, params):
        calls.append(dict(params))
        if len(calls) > 2:
            raise AssertionError("repeated page token should stop pagination")
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

    assert len(calls) == 2
    assert "pageToken" not in calls[0]
    assert calls[1]["pageToken"] == "LOOP"
    assert result.raw_count == 2


def test_harvester_stops_at_max_pages_when_tokens_advance():
    profile = DiseaseResolver().resolve("Parkinson disease")
    calls = []

    def get_json(url, params):
        calls.append(dict(params))
        if len(calls) > 2:
            raise AssertionError("max_pages should cap pagination")
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

    assert len(calls) == 2
    assert result.raw_count == 2


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
