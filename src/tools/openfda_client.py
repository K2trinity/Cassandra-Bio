"""
openFDA Client

Official API base: https://api.fda.gov/
Endpoints covered:
- /drug/label.json
- /drug/event.json
- /drug/drugsfda.json
"""

from __future__ import annotations

from typing import Any, Dict, Optional

import requests
from loguru import logger


class OpenFDAClient:
    """Minimal openFDA wrapper for drug label/safety/approval data."""

    BASE_URL = "https://api.fda.gov"

    def __init__(self, timeout: int = 30) -> None:
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "Cassandra-BioHarvest/1.0"})

    def _get(self, endpoint: str, search: str, limit: int = 20) -> Dict[str, Any]:
        url = f"{self.BASE_URL}{endpoint}"
        params = {
            "search": search,
            "limit": min(max(limit, 1), 100),
        }
        try:
            response = self.session.get(url, params=params, timeout=self.timeout)
            response.raise_for_status()
            return response.json()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"openFDA request failed for {endpoint}: {e}")
            return {"meta": {"results": {"total": 0}}, "results": []}

    def drug_label(self, ingredient_or_term: str, limit: int = 20) -> Dict[str, Any]:
        query = f'active_ingredient:"{ingredient_or_term}"+OR+openfda.brand_name:"{ingredient_or_term}"'
        return self._get("/drug/label.json", search=query, limit=limit)

    def drug_event(self, ingredient_or_term: str, limit: int = 20) -> Dict[str, Any]:
        query = f'patient.drug.medicinalproduct:"{ingredient_or_term}"+OR+patient.drug.openfda.generic_name:"{ingredient_or_term}"'
        return self._get("/drug/event.json", search=query, limit=limit)

    def drugs_fda(self, ingredient_or_term: str, limit: int = 20) -> Dict[str, Any]:
        query = f'openfda.generic_name:"{ingredient_or_term}"+OR+sponsor_name:"{ingredient_or_term}"+OR+products.brand_name:"{ingredient_or_term}"'
        return self._get("/drug/drugsfda.json", search=query, limit=limit)

    def collect(self, ingredient_or_term: str, limit: int = 20) -> Dict[str, Any]:
        """Collect all three core openFDA slices in one payload."""
        label = self.drug_label(ingredient_or_term, limit=limit)
        event = self.drug_event(ingredient_or_term, limit=limit)
        approval = self.drugs_fda(ingredient_or_term, limit=limit)
        return {
            "query": ingredient_or_term,
            "label": label,
            "event": event,
            "drugsfda": approval,
            "counts": {
                "label": len(label.get("results", []) or []),
                "event": len(event.get("results", []) or []),
                "drugsfda": len(approval.get("results", []) or []),
            },
        }
