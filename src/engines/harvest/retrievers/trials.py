"""ClinicalTrials retriever adapter."""

from typing import Any, Dict, List

from .._logging import logger

from src.tools.clinical_trials_client import search_trials

from .base import BaseRetriever


class ClinicalTrialsRetriever(BaseRetriever):
    """Retrieve and deduplicate studies from ClinicalTrials.gov."""

    def retrieve(self, queries: List[str], max_results: int) -> List[Dict[str, Any]]:
        all_trials: List[Dict[str, Any]] = []

        for query in queries:
            try:
                trials = search_trials(query, max_results=max_results, include_statuses=None)
                all_trials.extend(trials)
            except Exception as exc:
                logger.warning(f"ClinicalTrials search failed for '{query}': {exc}")

        seen = set()
        unique_trials: List[Dict[str, Any]] = []
        for item in all_trials:
            trial_id = item.get("nct_id")
            if trial_id and trial_id not in seen:
                seen.add(trial_id)
                unique_trials.append(item)

        return unique_trials
