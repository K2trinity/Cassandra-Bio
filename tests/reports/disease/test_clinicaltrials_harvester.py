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
        return payload

    result = ClinicalTrialsDiseaseHarvester(get_json=get_json).fetch_raw_studies(profile, max_records=50)

    assert calls[0][0] == "https://clinicaltrials.gov/api/v2/studies"
    assert calls[0][1]["query.cond"] == "Alzheimer Disease"
    assert result.raw_count == 3
    assert [study["protocolSection"]["identificationModule"]["nctId"] for study in result.studies] == [
        "NCT00000001",
        "NCT00000003",
    ]
    assert result.rejected_nct_numbers == ["NCT00000002"]


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
