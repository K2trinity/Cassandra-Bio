"""
Multi-source biomedical harvester.

Unifies data collection from:
- ClinicalTrials.gov API v2
- NCBI E-utilities (PubMed/gene/protein/clinvar/gds)
- Europe PMC
- openFDA
"""

from __future__ import annotations

from typing import Any, Dict, List

from loguru import logger

from .clinical_trials_client import search_trials, fetch_trial_results
from .europmc_client import search_europmc
from .ncbi_eutils_client import NCBIEutilsClient
from .openfda_client import OpenFDAClient
from .pubmed_client import search_pubmed, fetch_details


class MultiSourceHarvester:
    """Collects objective evidence payloads for downstream report layers."""

    def __init__(self) -> None:
        self.ncbi = NCBIEutilsClient()
        self.openfda = OpenFDAClient()

    def collect(self, query: str, max_results_per_source: int = 20) -> Dict[str, Any]:
        logger.info(f"Collecting multi-source biomedical data for query: {query}")

        trials = search_trials(
            keyword=query,
            max_results=max_results_per_source,
            include_statuses=None,
        )

        # Collect rich result modules for trials with posted results (bounded for latency).
        results_modules: Dict[str, Any] = {}
        for trial in trials[: min(len(trials), 15)]:
            nct_id = trial.get("nct_id")
            if not nct_id:
                continue
            result_payload = fetch_trial_results(nct_id)
            if result_payload:
                results_modules[nct_id] = result_payload

        pmids = search_pubmed(query, max_results=max_results_per_source)
        pubmed_articles = fetch_details(pmids)

        europmc_papers = search_europmc(
            query=query,
            max_results=max_results_per_source,
            open_access_only=False,
        )

        ncbi_bundle = {
            "pubmed": self.ncbi.search_and_collect("pubmed", query, retmax=max_results_per_source, include_efetch=True),
            "gene": self.ncbi.search_and_collect("gene", query, retmax=max_results_per_source, include_efetch=False),
            "protein": self.ncbi.search_and_collect("protein", query, retmax=max_results_per_source, include_efetch=False),
            "clinvar": self.ncbi.search_and_collect("clinvar", query, retmax=max_results_per_source, include_efetch=False),
            "gds": self.ncbi.search_and_collect("gds", query, retmax=max_results_per_source, include_efetch=False),
        }

        openfda_bundle = self.openfda.collect(query, limit=min(max_results_per_source, 50))

        return {
            "query": query,
            "clinicaltrials": {
                "studies": trials,
                "results_modules": results_modules,
            },
            "pubmed": {
                "pmids": pmids,
                "articles": pubmed_articles,
            },
            "europe_pmc": {
                "papers": europmc_papers,
            },
            "ncbi": ncbi_bundle,
            "openfda": openfda_bundle,
            "stats": {
                "trials": len(trials),
                "trial_results_modules": len(results_modules),
                "pubmed_articles": len(pubmed_articles),
                "europe_pmc_papers": len(europmc_papers),
                "openfda_label_records": openfda_bundle.get("counts", {}).get("label", 0),
                "openfda_event_records": openfda_bundle.get("counts", {}).get("event", 0),
                "openfda_approval_records": openfda_bundle.get("counts", {}).get("drugsfda", 0),
            },
        }


def collect_multi_source_data(query: str, max_results_per_source: int = 20) -> Dict[str, Any]:
    """Convenience function for one-shot multi-source collection."""
    return MultiSourceHarvester().collect(query=query, max_results_per_source=max_results_per_source)
