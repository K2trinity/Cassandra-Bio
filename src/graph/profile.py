"""Biomedical profile aggregation helpers for harvest-first workflows."""

from __future__ import annotations

from typing import Any, Dict, List, Set

from src.graph.state import AgentState
from src.tools.biomedical_normalization import (
    extract_normalized_targets,
    normalize_drug_class,
    normalize_target_term,
)


def top_ranked_pairs(counter: Dict[str, Any], limit: int = 8) -> List[Dict[str, Any]]:
    """Return top-N {name, count} pairs sorted by count desc."""
    if not isinstance(counter, dict):
        return []

    ranked = []
    for key, value in counter.items():
        name = str(key or "").strip()
        if not name:
            continue
        try:
            count = int(value)
        except (TypeError, ValueError):
            continue
        ranked.append((name, count))

    ranked.sort(key=lambda item: item[1], reverse=True)
    return [{"name": name, "count": count} for name, count in ranked[:limit]]


def add_terms(target: Set[str], raw_value: Any) -> None:
    """Parse a scalar/list field into normalized biomedical terms."""
    if raw_value is None:
        return

    if isinstance(raw_value, list):
        for item in raw_value:
            add_terms(target, item)
        return

    if isinstance(raw_value, dict):
        for _, value in raw_value.items():
            add_terms(target, value)
        return

    text = str(raw_value).strip()
    if not text:
        return

    for part in text.replace(";", ",").replace("|", ",").split(","):
        token = part.strip()
        if token and len(token) > 1:
            target.add(token)


def infer_drug_class_from_text(raw_text: Any) -> str:
    """Conservative heuristic for modality/class labels from intervention text."""
    return normalize_drug_class(raw_text)


def build_biomedical_profile(state: AgentState) -> Dict[str, Any]:
    """Build disease-oriented summary fields for API/frontend consumption."""
    harvested_data = state.get("harvested_data", []) or []
    data_layers = state.get("harvest_data_layers", {}) or {}
    source_payloads = state.get("harvest_source_payloads", {}) or {}

    disease_layer = data_layers.get("disease_layer", {}) or {}
    target_layer = data_layers.get("target_layer", {}) or {}
    pipeline_layer = data_layers.get("pipeline_layer", {}) or {}
    company_layer = data_layers.get("company_layer", {}) or {}

    disease_terms: Set[str] = set()
    add_terms(disease_terms, disease_layer.get("conditions_from_trials", []))
    for item in harvested_data:
        if not isinstance(item, dict):
            continue
        add_terms(disease_terms, item.get("conditions"))
        add_terms(disease_terms, item.get("condition"))
        add_terms(disease_terms, (item.get("metadata") or {}).get("conditions"))

    drug_terms: Set[str] = set()
    add_terms(drug_terms, state.get("project_name"))

    openfda_payload = source_payloads.get("openfda", {}) or {}
    label_results = (openfda_payload.get("label", {}) or {}).get("results", []) or []
    for rec in label_results:
        if not isinstance(rec, dict):
            continue
        openfda = rec.get("openfda", {}) or {}
        add_terms(drug_terms, openfda.get("generic_name"))
        add_terms(drug_terms, openfda.get("brand_name"))

    drugsfda_results = (openfda_payload.get("drugsfda", {}) or {}).get("results", []) or []
    for rec in drugsfda_results:
        if not isinstance(rec, dict):
            continue
        openfda = rec.get("openfda", {}) or {}
        add_terms(drug_terms, openfda.get("generic_name"))
        add_terms(drug_terms, openfda.get("brand_name"))
        products = rec.get("products", []) or []
        for product in products if isinstance(products, list) else []:
            if isinstance(product, dict):
                add_terms(drug_terms, product.get("brand_name"))

    for item in harvested_data:
        if not isinstance(item, dict):
            continue
        add_terms(drug_terms, item.get("interventions"))
        add_terms(drug_terms, (item.get("metadata") or {}).get("interventions"))

    trial_records = sum(
        1
        for item in harvested_data
        if isinstance(item, dict)
        and (
            item.get("source") == "ClinicalTrials.gov"
            or bool(item.get("nct_id"))
            or bool((item.get("metadata") or {}).get("nct_id"))
        )
    )

    normalized_target_counter: Dict[str, int] = {}
    raw_target_counter = target_layer.get("target_proxy_distribution", {})
    if isinstance(raw_target_counter, dict):
        for raw_name, raw_count in raw_target_counter.items():
            canonical = normalize_target_term(raw_name)
            if not canonical:
                continue
            try:
                count = int(raw_count)
            except (TypeError, ValueError):
                continue
            normalized_target_counter[canonical] = normalized_target_counter.get(canonical, 0) + count

    drug_class_counter: Dict[str, int] = {}
    for item in harvested_data:
        if not isinstance(item, dict):
            continue
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}
        target_text = " ; ".join(
            [
                str(item.get("target", "")),
                str(item.get("targets", "")),
                str(item.get("target_description", "")),
                str(metadata.get("target", "")),
                str(metadata.get("target_description", "")),
                str(item.get("mechanism", "")),
                str(metadata.get("mechanism", "")),
                str(item.get("interventions", "")),
                str(metadata.get("interventions", "")),
            ]
        )
        for target in extract_normalized_targets(target_text):
            normalized_target_counter[target] = normalized_target_counter.get(target, 0) + 1

        modality_text = " ; ".join(
            [
                str(item.get("drug_class", "")),
                str(item.get("modality", "")),
                str(item.get("interventions", "")),
                str(metadata.get("interventions", "")),
            ]
        )
        normalized_class = infer_drug_class_from_text(modality_text)
        drug_class_counter[normalized_class] = drug_class_counter.get(normalized_class, 0) + 1

    publication_records = sum(
        1
        for item in harvested_data
        if isinstance(item, dict)
        and (
            item.get("source") == "PubMed"
            or bool(item.get("pmid"))
            or bool((item.get("metadata") or {}).get("pmid"))
        )
    )

    trial_field_coverage = {
        "nct_id": sum(1 for item in harvested_data if isinstance(item, dict) and bool(item.get("nct_id"))),
        "phase": sum(1 for item in harvested_data if isinstance(item, dict) and bool(item.get("phase"))),
        "status": sum(1 for item in harvested_data if isinstance(item, dict) and bool(item.get("status"))),
    }

    drug_catalog = sorted(drug_terms)
    disease_catalog = sorted(disease_terms)

    return {
        "analysis_focus": "HARVEST_AND_REPORT_ONLY",
        "disease_areas": disease_catalog,
        "drug_baselines": drug_catalog,
        "target_signals": top_ranked_pairs(normalized_target_counter, limit=10),
        "company_entities": top_ranked_pairs(company_layer.get("sponsor_distribution", {}), limit=10),
        "drug_class_distribution": top_ranked_pairs(drug_class_counter, limit=10),
        "drug_catalog": drug_catalog,
        "clinical_data": {
            "trial_records": trial_records,
            "phase_distribution": pipeline_layer.get("phase_distribution", {}),
            "status_distribution": pipeline_layer.get("status_distribution", {}),
            "trial_field_coverage": trial_field_coverage,
        },
        "evidence_stats": {
            "publication_records": publication_records,
            "total_harvested_records": len(harvested_data),
        },
    }


__all__ = ["build_biomedical_profile", "top_ranked_pairs", "add_terms", "infer_drug_class_from_text"]
