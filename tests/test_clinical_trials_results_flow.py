import unittest
from unittest.mock import patch

from src.tools.clinical_trials_client import fetch_trial_results, is_trial_results_candidate
from src.tools.multi_source_harvester import MultiSourceHarvester


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class ClinicalTrialsResultsFlowTest(unittest.TestCase):
    def test_is_trial_results_candidate_requires_terminal_status_and_has_results(self):
        self.assertTrue(
            is_trial_results_candidate(
                {
                    "nct_id": "NCT_A",
                    "status": "COMPLETED",
                    "has_results": "True",
                }
            )
        )
        self.assertFalse(
            is_trial_results_candidate(
                {
                    "nct_id": "NCT_B",
                    "status": "RECRUITING",
                    "has_results": "True",
                }
            )
        )
        self.assertFalse(
            is_trial_results_candidate(
                {
                    "nct_id": "NCT_C",
                    "status": "COMPLETED",
                    "has_results": "False",
                }
            )
        )

    @patch("src.tools.clinical_trials_client.requests.get")
    def test_fetch_trial_results_supports_single_study_payload(self, mock_get):
        mock_get.return_value = _FakeResponse(
            {
                "hasResults": True,
                "resultsSection": {
                    "outcomeMeasuresModule": {
                        "outcomeMeasures": [{"measure": "Overall Response Rate"}]
                    },
                    "adverseEventsModule": {"eventGroups": [{"id": "EG1"}]},
                    "participantFlowModule": {"groups": [{"id": "PG1"}]},
                    "baselineCharacteristicsModule": {"population": "All randomized"},
                },
            }
        )

        payload = fetch_trial_results("NCT01341964")

        self.assertIsNotNone(payload)
        self.assertTrue(payload["has_results"])
        self.assertEqual(payload["nct_id"], "NCT01341964")
        self.assertEqual(len(payload.get("outcome_measures", [])), 1)
        self.assertTrue(payload.get("adverse_events"))

    def test_multi_source_pre_filter_skips_non_result_trials(self):
        trials = [
            {"nct_id": "NCT_1", "status": "RECRUITING", "has_results": "True"},
            {"nct_id": "NCT_2", "status": "COMPLETED", "has_results": "False"},
            {"nct_id": "NCT_3", "status": "COMPLETED", "has_results": "True"},
            {"nct_id": "NCT_4", "status": "TERMINATED", "has_results": True},
        ]

        selected = MultiSourceHarvester._select_trials_for_results_fetch(trials)
        selected_ids = [trial.get("nct_id") for trial in selected]

        self.assertEqual(selected_ids, ["NCT_3", "NCT_4"])


if __name__ == "__main__":
    unittest.main()