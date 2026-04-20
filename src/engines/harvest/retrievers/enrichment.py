"""Unified enrichment adapter for multi-source payload collection."""

from typing import Any, Dict

from src.tools.multi_source_harvester import collect_multi_source_data

from ..core.field_mappings import project_source_payloads_for_frontend


class MultiSourceEnricher:
    """Adapter over src.tools unified collector and frontend projection."""

    def collect(self, query: str, max_results_per_source: int) -> Dict[str, Any]:
        return collect_multi_source_data(
            query=query,
            max_results_per_source=max_results_per_source,
        )

    def project_for_frontend(self, source_payloads: Dict[str, Any], max_items: int) -> Dict[str, Any]:
        return project_source_payloads_for_frontend(
            source_payloads=source_payloads,
            max_items=max_items,
        )
