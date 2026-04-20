"""Harvest-scoped source field whitelist and mapping tables."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


CLINICALTRIALS_STUDY_FIELD_WHITELIST: List[str] = [
    "nct_number",
    "nct_id",
    "study_url",
    "title",
    "official_title",
    "url",
    "acronym",
    "study_status",
    "status",
    "why_stopped",
    "brief_summary",
    "has_results",
    "study_results",
    "results_url",
    "conditions",
    "interventions",
    "primary_outcome_measures",
    "secondary_outcome_measures",
    "other_outcome_measures",
    "phases",
    "phase",
    "enrollment",
    "study_type",
    "study_design",
    "sponsor",
    "collaborators",
    "funder_type",
    "sex",
    "age",
    "start_date",
    "primary_completion_date",
    "completion_date",
    "first_posted",
    "results_first_posted",
    "last_update_posted",
    "study_documents",
]

NCBI_DB_SUMMARY_WHITELIST: List[str] = [
    "db",
    "query",
    "count",
    "ids",
]

PUBMED_ARTICLE_WHITELIST: List[str] = [
    "pmid",
    "pmcid",
    "title",
    "abstract",
    "authors",
    "journal",
    "pub_date",
    "doi",
    "pmc_link",
    "pubmed_link",
    "pdf_url",
]

OPENFDA_ENDPOINT_FIELD_WHITELIST: Dict[str, List[str]] = {
    "label": [
        "id",
        "effective_time",
        "indications_and_usage",
        "dosage_and_administration",
        "contraindications",
        "boxed_warning",
        "warnings",
        "adverse_reactions",
        "purpose",
        "openfda.brand_name",
        "openfda.generic_name",
        "openfda.manufacturer_name",
        "openfda.application_number",
        "openfda.product_type",
    ],
    "event": [
        "safetyreportid",
        "receivedate",
        "occurcountry",
        "serious",
        "seriousnessdeath",
        "seriousnesslifethreatening",
        "patient.patientsex",
        "patient.patientonsetage",
        "patient.reaction.reactionmeddrapt",
        "patient.drug.medicinalproduct",
        "patient.drug.drugcharacterization",
    ],
    "drugsfda": [
        "application_number",
        "sponsor_name",
        "openfda.brand_name",
        "openfda.generic_name",
        "openfda.manufacturer_name",
        "products.brand_name",
        "products.active_ingredients.name",
        "products.route",
        "products.marketing_status",
        "products.dosage_form",
        "submissions.submission_type",
        "submissions.submission_status",
        "submissions.submission_status_date",
    ],
}

SOURCE_FIELD_MAPPING_TABLE: Dict[str, List[Dict[str, str]]] = {
    "clinicaltrials": [
        {"canonical": "nct_number", "source_path": "studies[].nct_number", "type": "string", "label": "NCT Number"},
        {"canonical": "trial_id", "source_path": "studies[].nct_id", "type": "string", "label": "NCT ID"},
        {"canonical": "study_url", "source_path": "studies[].study_url", "type": "string", "label": "Study URL"},
        {"canonical": "trial_title", "source_path": "studies[].title", "type": "string", "label": "Trial Title"},
        {"canonical": "trial_acronym", "source_path": "studies[].acronym", "type": "string", "label": "Acronym"},
        {"canonical": "trial_results_state", "source_path": "studies[].study_results", "type": "string", "label": "Study Results"},
        {"canonical": "trial_status", "source_path": "studies[].status", "type": "string", "label": "Overall Status"},
        {"canonical": "trial_brief_summary", "source_path": "studies[].brief_summary", "type": "string", "label": "Brief Summary"},
        {"canonical": "trial_phase", "source_path": "studies[].phase", "type": "string", "label": "Phase"},
        {"canonical": "trial_phases", "source_path": "studies[].phases", "type": "string", "label": "Phases"},
        {"canonical": "trial_design", "source_path": "studies[].study_design", "type": "string", "label": "Study Design"},
        {"canonical": "trial_conditions", "source_path": "studies[].conditions", "type": "string", "label": "Conditions"},
        {"canonical": "trial_interventions", "source_path": "studies[].interventions", "type": "string", "label": "Interventions"},
        {"canonical": "trial_has_results", "source_path": "studies[].has_results", "type": "string", "label": "Has Results"},
        {"canonical": "trial_primary_outcomes", "source_path": "studies[].primary_outcome_measures", "type": "string", "label": "Primary Outcomes"},
        {"canonical": "trial_secondary_outcomes", "source_path": "studies[].secondary_outcome_measures", "type": "string", "label": "Secondary Outcomes"},
        {"canonical": "trial_other_outcomes", "source_path": "studies[].other_outcome_measures", "type": "string", "label": "Other Outcomes"},
        {"canonical": "trial_sponsor", "source_path": "studies[].sponsor", "type": "string", "label": "Lead Sponsor"},
        {"canonical": "trial_collaborators", "source_path": "studies[].collaborators", "type": "string", "label": "Collaborators"},
        {"canonical": "trial_sex", "source_path": "studies[].sex", "type": "string", "label": "Sex"},
        {"canonical": "trial_age", "source_path": "studies[].age", "type": "string", "label": "Age"},
        {"canonical": "trial_enrollment", "source_path": "studies[].enrollment", "type": "string", "label": "Enrollment"},
        {"canonical": "trial_funder_type", "source_path": "studies[].funder_type", "type": "string", "label": "Funder Type"},
        {"canonical": "trial_study_type", "source_path": "studies[].study_type", "type": "string", "label": "Study Type"},
        {"canonical": "trial_other_ids", "source_path": "studies[].other_ids", "type": "string", "label": "Other IDs"},
        {"canonical": "trial_start_date", "source_path": "studies[].start_date", "type": "string", "label": "Start Date"},
        {"canonical": "trial_primary_completion_date", "source_path": "studies[].primary_completion_date", "type": "string", "label": "Primary Completion Date"},
        {"canonical": "trial_completion_date", "source_path": "studies[].completion_date", "type": "string", "label": "Completion Date"},
        {"canonical": "trial_first_posted", "source_path": "studies[].first_posted", "type": "string", "label": "First Posted"},
        {"canonical": "trial_results_first_posted", "source_path": "studies[].results_first_posted", "type": "string", "label": "Results First Posted"},
        {"canonical": "trial_last_update_posted", "source_path": "studies[].last_update_posted", "type": "string", "label": "Last Update Posted"},
        {"canonical": "trial_study_documents", "source_path": "studies[].study_documents", "type": "string", "label": "Study Documents"},
    ],
    "ncbi": [
        {"canonical": "ncbi_db", "source_path": "ncbi.<db>.db", "type": "string", "label": "NCBI Database"},
        {"canonical": "ncbi_query", "source_path": "ncbi.<db>.query", "type": "string", "label": "NCBI Query"},
        {"canonical": "ncbi_count", "source_path": "ncbi.<db>.count", "type": "integer", "label": "Hit Count"},
        {"canonical": "ncbi_ids", "source_path": "ncbi.<db>.ids", "type": "array", "label": "Record IDs"},
        {"canonical": "pubmed_article_title", "source_path": "pubmed.articles[].title", "type": "string", "label": "PubMed Title"},
        {"canonical": "pubmed_article_doi", "source_path": "pubmed.articles[].doi", "type": "string", "label": "DOI"},
    ],
    "openfda": [
        {"canonical": "fda_label_generic_name", "source_path": "openfda.label.results[].openfda.generic_name", "type": "array", "label": "Generic Name"},
        {"canonical": "fda_label_brand_name", "source_path": "openfda.label.results[].openfda.brand_name", "type": "array", "label": "Brand Name"},
        {"canonical": "fda_label_manufacturer", "source_path": "openfda.label.results[].openfda.manufacturer_name", "type": "array", "label": "Manufacturer"},
        {"canonical": "fda_label_indication", "source_path": "openfda.label.results[].indications_and_usage", "type": "array", "label": "Indications"},
        {"canonical": "fda_label_purpose", "source_path": "openfda.label.results[].purpose", "type": "array", "label": "Purpose"},
        {"canonical": "fda_label_contraindications", "source_path": "openfda.label.results[].contraindications", "type": "array", "label": "Contraindications"},
        {"canonical": "fda_label_warnings", "source_path": "openfda.label.results[].warnings", "type": "array", "label": "Warnings"},
        {"canonical": "fda_event_reactions", "source_path": "openfda.event.results[].patient.reaction.reactionmeddrapt", "type": "array", "label": "Adverse Reactions"},
        {"canonical": "fda_event_serious", "source_path": "openfda.event.results[].serious", "type": "string", "label": "Serious Event Flag"},
        {"canonical": "fda_event_report_date", "source_path": "openfda.event.results[].receivedate", "type": "string", "label": "Report Date"},
        {"canonical": "fda_approval_application", "source_path": "openfda.drugsfda.results[].application_number", "type": "string", "label": "Application Number"},
        {"canonical": "fda_approval_sponsor", "source_path": "openfda.drugsfda.results[].sponsor_name", "type": "string", "label": "Sponsor"},
        {"canonical": "fda_approval_brand", "source_path": "openfda.drugsfda.results[].products.brand_name", "type": "string", "label": "Product Brand"},
        {"canonical": "fda_approval_route", "source_path": "openfda.drugsfda.results[].products.route", "type": "string", "label": "Route"},
    ],
}


def _get_nested_value(record: Dict[str, Any], path: str) -> Any:
    parts = path.split(".")
    current: Any = record

    for idx, key in enumerate(parts):
        if isinstance(current, list):
            remaining = ".".join(parts[idx:])
            values = [
                _get_nested_value(item, remaining)
                for item in current
                if isinstance(item, (dict, list))
            ]
            values = [v for v in values if v is not None]
            return values if values else None

        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]

    return current


def _pick_fields(record: Dict[str, Any], whitelist: List[str]) -> Dict[str, Any]:
    selected: Dict[str, Any] = {}
    for field in whitelist:
        if "." in field:
            selected[field] = _get_nested_value(record, field)
        else:
            selected[field] = record.get(field)
    return selected


def project_source_payloads_for_frontend(source_payloads: Dict[str, Any], max_items: int = 50) -> Dict[str, Any]:
    clinical_studies = (source_payloads.get("clinicaltrials", {}) or {}).get("studies", []) or []
    projected_trials = [_pick_fields(s, CLINICALTRIALS_STUDY_FIELD_WHITELIST) for s in clinical_studies[:max_items]]

    results_modules = (source_payloads.get("clinicaltrials", {}) or {}).get("results_modules", {}) or {}
    projected_results_modules = []
    for nct_id, module in list(results_modules.items())[:max_items]:
        module = module or {}
        projected_results_modules.append(
            {
                "nct_id": nct_id,
                "has_results": bool(module.get("has_results")),
                "results_url": module.get("results_url"),
                "outcome_measure_count": len(module.get("outcome_measures", []) or []),
                "has_adverse_events": bool(module.get("adverse_events")),
            }
        )

    ncbi_payload = source_payloads.get("ncbi", {}) or {}
    projected_ncbi: Dict[str, Any] = {}
    for db in ["pubmed", "gene", "protein", "clinvar", "gds"]:
        db_payload = ncbi_payload.get(db, {}) or {}
        projected_ncbi[db] = _pick_fields(db_payload, NCBI_DB_SUMMARY_WHITELIST)

    pubmed_articles = (source_payloads.get("pubmed", {}) or {}).get("articles", []) or []
    projected_pubmed_articles = [_pick_fields(a, PUBMED_ARTICLE_WHITELIST) for a in pubmed_articles[:max_items]]

    openfda_payload = source_payloads.get("openfda", {}) or {}
    projected_openfda: Dict[str, Any] = {"counts": openfda_payload.get("counts", {})}
    for endpoint in ["label", "event", "drugsfda"]:
        endpoint_records = (openfda_payload.get(endpoint, {}) or {}).get("results", []) or []
        whitelist = OPENFDA_ENDPOINT_FIELD_WHITELIST[endpoint]
        projected_openfda[endpoint] = [_pick_fields(r, whitelist) for r in endpoint_records[:max_items]]

    return {
        "clinicaltrials": projected_trials,
        "clinicaltrial_results_modules": projected_results_modules,
        "ncbi": projected_ncbi,
        "pubmed_articles": projected_pubmed_articles,
        "openfda": projected_openfda,
        "mapping_table": SOURCE_FIELD_MAPPING_TABLE,
    }


def get_mapping_table(source: Optional[str] = None) -> Dict[str, Any]:
    if source:
        return {source: SOURCE_FIELD_MAPPING_TABLE.get(source, [])}
    return SOURCE_FIELD_MAPPING_TABLE
