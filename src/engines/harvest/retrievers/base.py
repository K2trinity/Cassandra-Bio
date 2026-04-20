"""Retriever abstraction interfaces."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List


class BaseRetriever(ABC):
    """Abstract retrieval contract for query-based source adapters."""

    @abstractmethod
    def retrieve(self, queries: List[str], max_results: int) -> List[Dict[str, Any]]:
        """Execute source retrieval against a list of normalized queries."""
