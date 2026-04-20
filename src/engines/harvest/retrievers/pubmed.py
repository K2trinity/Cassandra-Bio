"""PubMed retriever adapter."""

from typing import Any, Dict, List

from .._logging import logger

from src.tools.pubmed_client import fetch_details, search_pubmed

from .base import BaseRetriever


class PubMedRetriever(BaseRetriever):
    """Retrieve PubMed articles using shared src.tools clients."""

    def retrieve(self, queries: List[str], max_results: int) -> List[Dict[str, Any]]:
        all_pmids: List[str] = []

        for query in queries:
            try:
                pmids = search_pubmed(query, max_results=max_results)
                all_pmids.extend(pmids)
            except Exception as exc:
                logger.warning(f"PubMed search failed for '{query}': {exc}")

        unique_pmids = list(dict.fromkeys(all_pmids))
        if not unique_pmids:
            return []

        try:
            return fetch_details(unique_pmids)
        except Exception as exc:
            logger.warning(f"PubMed detail fetch failed: {exc}")
            return []
