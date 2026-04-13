"""
NCBI E-utilities Client

Lightweight requests-based wrapper for the official NCBI E-utilities API:
https://eutils.ncbi.nlm.nih.gov/entrez/eutils/

Supported operations:
- esearch.fcgi (search PMIDs / gene IDs / etc.)
- esummary.fcgi (document summaries)
- efetch.fcgi (detailed records, XML or text)
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

import requests
from loguru import logger


class NCBIEutilsClient:
    """Official NCBI E-utilities API client with polite rate limiting."""

    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

    def __init__(
        self,
        api_key: Optional[str] = None,
        email: Optional[str] = None,
        tool: str = "Cassandra-BioHarvest",
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key or os.getenv("NCBI_API_KEY")
        self.email = email or os.getenv("PUBMED_EMAIL") or "bio-harvest@example.com"
        self.tool = tool
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Cassandra-BioHarvest/1.0"})

        # NCBI guidance: 3 req/s without key, up to 10 req/s with key.
        self._min_interval = 0.11 if self.api_key else 0.34
        self._last_request_ts = 0.0

    def _throttle(self) -> None:
        now = time.time()
        delta = now - self._last_request_ts
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last_request_ts = time.time()

    def _request(self, endpoint: str, params: Dict[str, Any], retries: int = 3) -> requests.Response:
        merged = {
            "tool": self.tool,
            "email": self.email,
            **params,
        }
        if self.api_key:
            merged["api_key"] = self.api_key

        url = f"{self.BASE_URL}/{endpoint}"
        last_error: Optional[Exception] = None
        for attempt in range(retries):
            try:
                self._throttle()
                response = self.session.get(url, params=merged, timeout=self.timeout)
                response.raise_for_status()
                return response
            except Exception as e:  # noqa: BLE001
                last_error = e
                logger.warning(f"NCBI request failed ({endpoint}) attempt {attempt + 1}/{retries}: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)

        raise RuntimeError(f"NCBI request failed after retries: {last_error}")

    def esearch(self, db: str, term: str, retmax: int = 20) -> Dict[str, Any]:
        """Search IDs in a target NCBI database."""
        response = self._request(
            "esearch.fcgi",
            {
                "db": db,
                "term": term,
                "retmode": "json",
                "retmax": retmax,
            },
        )
        return response.json()

    def esummary(self, db: str, ids: List[str]) -> Dict[str, Any]:
        """Fetch summary metadata for IDs."""
        if not ids:
            return {}
        response = self._request(
            "esummary.fcgi",
            {
                "db": db,
                "id": ",".join(ids),
                "retmode": "json",
            },
        )
        return response.json()

    def efetch(self, db: str, ids: List[str], retmode: str = "xml") -> str:
        """Fetch detailed record payload (XML/text)."""
        if not ids:
            return ""
        response = self._request(
            "efetch.fcgi",
            {
                "db": db,
                "id": ",".join(ids),
                "retmode": retmode,
            },
        )
        return response.text

    def search_and_collect(
        self,
        db: str,
        term: str,
        retmax: int = 20,
        include_efetch: bool = False,
    ) -> Dict[str, Any]:
        """One-stop collection for a given DB: esearch + esummary (+ optional efetch)."""
        search_payload = self.esearch(db=db, term=term, retmax=retmax)
        id_list = (search_payload.get("esearchresult") or {}).get("idlist", [])

        summary_payload = self.esummary(db=db, ids=id_list)
        result: Dict[str, Any] = {
            "db": db,
            "query": term,
            "count": int((search_payload.get("esearchresult") or {}).get("count", 0) or 0),
            "ids": id_list,
            "summary": summary_payload,
        }

        if include_efetch and id_list:
            # PubMed often needs XML for abstract + MeSH details.
            result["details_xml"] = self.efetch(db=db, ids=id_list, retmode="xml")

        return result
