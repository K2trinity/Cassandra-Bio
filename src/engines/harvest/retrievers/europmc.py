"""Europe PMC retriever adapter."""

from typing import Any, Dict, List

from .._logging import logger

from src.tools.europmc_client import EuroPMCClient

from .base import BaseRetriever


class EuroPMCRetriever(BaseRetriever):
    """Primary literature retriever focused on open-access PDF availability."""

    def __init__(self, client: EuroPMCClient | None = None):
        self.client = client or EuroPMCClient()

    def retrieve(self, queries: List[str], max_results: int) -> List[Dict[str, Any]]:
        papers: List[Dict[str, Any]] = []

        for query in queries:
            try:
                result = self.client.search_papers(
                    query=query,
                    max_results=max_results,
                    open_access_only=True,
                )
                papers.extend(result)
            except Exception as exc:
                logger.warning(f"EuroPMC search failed for '{query}': {exc}")

        return papers
