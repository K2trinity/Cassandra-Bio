"""
openFDA Client

Official API base: https://api.fda.gov/
Endpoints covered:
- /drug/label.json
- /drug/event.json
- /drug/drugsfda.json
"""

from __future__ import annotations

from typing import Any, Dict, Optional, List
import uuid
from datetime import datetime

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


def normalize_biotech_events(
    payload: Dict[str, Any],
    source: str = "openfda",
    requested_ticker: str | None = None,
) -> List[Dict[str, Any]]:
    """
    Normalize openFDA payloads into consistent biotech_events schema.

    Args:
        payload: Raw openFDA API response
        source: Data source identifier (default: "openfda")
        requested_ticker: Chart ticker requested by the user; FDA entity data remains metadata.

    Returns:
        List of normalized event dictionaries with schema:
        {
            "id": "...",
            "date": "YYYY-MM-DD",
            "type": "fda_decision" | "regulatory_change",
            "priority": 1-5,
            "ticker": "MRNA",
            "disease_area": "",
            "catalyst": "...",
            "sentiment": "positive" | "negative" | "neutral",
            "price_impact": None,
            "source": "openfda",
        }
    """
    events = []
    results = payload.get("results", [])

    for result in results:
        try:
            # Extract key fields
            action_type = result.get("action_type", "").upper()
            approval_date = result.get("approval_date")
            recall_date = result.get("recall_initiation_date")
            event_date = approval_date or recall_date

            if not event_date:
                logger.warning("Skipping openFDA record with no date")
                continue

            # Parse date from YYYYMMDD format to YYYY-MM-DD
            try:
                date_obj = datetime.strptime(str(event_date), "%Y%m%d")
                date_str = date_obj.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                logger.warning(f"Invalid date format: {event_date}")
                continue

            # Determine event type and sentiment
            if action_type == "APPROVAL":
                event_type = "fda_decision"
                sentiment = "positive"
                priority = 5
            elif "RECALL" in action_type or result.get("recall_number"):
                event_type = "regulatory_change"
                sentiment = "negative"
                priority = 4
            else:
                logger.debug(f"Skipping unknown action type: {action_type}")
                continue

            openfda = result.get("openfda", {})
            brand_names = openfda.get("brand_name", [])
            generic_names = openfda.get("generic_name", [])
            sponsor_name = result.get("sponsor_name")
            if requested_ticker is not None:
                ticker = requested_ticker.strip().upper()
            else:
                ticker = brand_names[0] if brand_names else result.get("sponsor_name", "UNKNOWN")
            raw_ticker = brand_names[0] if brand_names else sponsor_name
            application_number = result.get("application_number")
            recall_number = result.get("recall_number")
            source_ids = []
            if application_number:
                source_ids.append(application_number)
            elif recall_number:
                source_ids.append(recall_number)

            # Extract catalyst description
            if action_type == "APPROVAL":
                products = result.get("products", [])
                product_desc = products[0].get("brand_name", "") if products else ""
                catalyst = f"FDA Approval: {product_desc}"
            else:
                reason = result.get("reason_for_recall", "Regulatory action")
                catalyst = f"Regulatory Change: {reason}"

            event = {
                "id": str(uuid.uuid4()),
                "date": date_str,
                "type": event_type,
                "priority": priority,
                "ticker": ticker,
                "disease_area": "",
                "catalyst": catalyst,
                "sentiment": sentiment,
                "price_impact": None,
                "source": source,
                "source_entity": sponsor_name,
                "source_url": None,
                "source_ids": source_ids,
                "confidence": "medium",
                "metadata": {
                    "brand_names": brand_names,
                    "generic_names": generic_names,
                    "application_number": application_number,
                    "recall_number": recall_number,
                    "raw_ticker": raw_ticker,
                },
            }

            events.append(event)

        except Exception as e:
            logger.error(f"Error normalizing openFDA record: {e}")
            continue

    return events
