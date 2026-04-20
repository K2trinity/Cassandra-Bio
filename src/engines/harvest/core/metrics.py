"""Objective report-layer metrics generation."""

from typing import Any, Dict, List

from .normalization import extract_normalized_targets, normalize_drug_class

from ..schemas import DataCandidate, model_dump_compat


def build_data_layers(
    query: str,
    data_candidates: List[DataCandidate],
    source_payloads: Dict[str, Any],
) -> Dict[str, Any]:
    """Build normalized report-oriented objective data layers."""
    trials = source_payloads.get("clinicaltrials", {}).get("studies", [])
    pubmed_articles = source_payloads.get("pubmed", {}).get("articles", [])
    openfda_payload = source_payloads.get("openfda", {}) or {}
    label_results = (openfda_payload.get("label", {}) or {}).get("results", []) or []
    event_results = (openfda_payload.get("event", {}) or {}).get("results", []) or []
    drugsfda_results = (openfda_payload.get("drugsfda", {}) or {}).get("results", []) or []

    target_counts: Dict[str, int] = {}
    drug_class_counts: Dict[str, int] = {}
    phase_counts: Dict[str, int] = {}
    status_counts: Dict[str, int] = {}
    sponsor_counts: Dict[str, int] = {}

    required_trial_fields = [
        "nct_id",
        "title",
        "url",
        "acronym",
        "status",
        "brief_summary",
        "has_results",
        "study_results",
        "conditions",
        "interventions",
        "primary_outcome_measures",
        "secondary_outcome_measures",
        "other_outcome_measures",
        "phase",
        "enrollment",
        "funder_type",
        "study_type",
        "study_design",
        "other_ids",
        "start_date",
        "primary_completion_date",
        "completion_date",
        "first_posted",
        "results_first_posted",
        "last_update_posted",
        "study_documents",
        "sponsor",
        "collaborators",
        "sex",
        "age",
    ]

    def _is_present(value: Any) -> bool:
        return value not in (None, "", "N/A", "Unknown", "Not specified", "None", [], {})

    trial_field_coverage = {
        field: sum(1 for t in trials if _is_present(t.get(field)))
        for field in required_trial_fields
    }

    for trial in trials:
        trial_target_text = " ; ".join(
            [
                str(trial.get("target", "")),
                str(trial.get("targets", "")),
                str(trial.get("interventions", "")),
            ]
        )
        for target in extract_normalized_targets(trial_target_text):
            target_counts[target] = target_counts.get(target, 0) + 1

        trial_class = normalize_drug_class(
            raw_text=" ".join(
                [
                    str(trial.get("interventions", "")),
                    str(trial.get("title", "")),
                    str(trial.get("brief_summary", "")),
                ]
            ),
            explicit_label=trial.get("drug_class") or trial.get("modality") or trial.get("platform"),
        )
        drug_class_counts[trial_class] = drug_class_counts.get(trial_class, 0) + 1

        phase = str(trial.get("phase", "Not specified"))
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        status = str(trial.get("status", "UNKNOWN"))
        status_counts[status] = status_counts.get(status, 0) + 1
        sponsor = str(trial.get("sponsor", "Unknown"))
        sponsor_counts[sponsor] = sponsor_counts.get(sponsor, 0) + 1

    for candidate in data_candidates:
        item = model_dump_compat(candidate, exclude_none=True)
        metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}

        target_text = " ; ".join(
            [
                str(item.get("target", "")),
                str(item.get("targets", "")),
                str(item.get("target_description", "")),
                str(metadata.get("target", "")),
                str(metadata.get("target_description", "")),
                str(item.get("interventions", "")),
                str(metadata.get("interventions", "")),
            ]
        )
        for target in extract_normalized_targets(target_text):
            target_counts[target] = target_counts.get(target, 0) + 1

        item_class = normalize_drug_class(
            raw_text=" ".join(
                [
                    str(item.get("interventions", "")),
                    str(metadata.get("interventions", "")),
                    str(item.get("title", "")),
                    str(item.get("snippet", "")),
                    str(item.get("mechanism", "")),
                    str(metadata.get("mechanism", "")),
                ]
            ),
            explicit_label=item.get("drug_class")
            or metadata.get("drug_class")
            or item.get("modality")
            or metadata.get("modality"),
        )
        drug_class_counts[item_class] = drug_class_counts.get(item_class, 0) + 1

    return {
        "disease_layer": {
            "query_anchor": query,
            "conditions_from_trials": list({t.get("conditions", "") for t in trials if t.get("conditions")}),
        },
        "biology_layer": {
            "ncbi_gene_hits": (source_payloads.get("ncbi", {}).get("gene", {}) or {}).get("count", 0),
            "ncbi_protein_hits": (source_payloads.get("ncbi", {}).get("protein", {}) or {}).get("count", 0),
            "ncbi_clinvar_hits": (source_payloads.get("ncbi", {}).get("clinvar", {}) or {}).get("count", 0),
            "ncbi_gds_hits": (source_payloads.get("ncbi", {}).get("gds", {}) or {}).get("count", 0),
        },
        "target_layer": {
            "target_proxy_distribution": target_counts,
        },
        "drug_layer": {
            "openfda_counts": openfda_payload.get("counts", {}),
            "class_distribution": dict(sorted(drug_class_counts.items(), key=lambda kv: kv[1], reverse=True)),
            "openfda_label_snapshot": [
                {
                    "generic_name": ((r.get("openfda", {}) or {}).get("generic_name") or [None])[0],
                    "brand_name": ((r.get("openfda", {}) or {}).get("brand_name") or [None])[0],
                    "manufacturer_name": ((r.get("openfda", {}) or {}).get("manufacturer_name") or [None])[0],
                    "application_number": ((r.get("openfda", {}) or {}).get("application_number") or [None])[0],
                    "effective_time": r.get("effective_time"),
                }
                for r in label_results[:20]
            ],
            "openfda_event_snapshot": [
                {
                    "safetyreportid": r.get("safetyreportid"),
                    "receivedate": r.get("receivedate"),
                    "serious": r.get("serious"),
                    "seriousnessdeath": r.get("seriousnessdeath"),
                    "reaction_terms": [
                        x.get("reactionmeddrapt")
                        for x in ((r.get("patient", {}) or {}).get("reaction") or [])[:10]
                        if isinstance(x, dict) and x.get("reactionmeddrapt")
                    ],
                }
                for r in event_results[:20]
            ],
            "sample_drugsfda_records": drugsfda_results[:10],
        },
        "pipeline_layer": {
            "phase_distribution": phase_counts,
            "status_distribution": status_counts,
        },
        "company_layer": {
            "sponsor_distribution": sponsor_counts,
        },
        "regulatory_layer": {
            "openfda_approval_records": len(drugsfda_results),
            "openfda_approval_snapshot": [
                {
                    "application_number": r.get("application_number"),
                    "sponsor_name": r.get("sponsor_name"),
                    "brand_name": ((r.get("products", []) or [{}])[0] or {}).get("brand_name"),
                    "marketing_status": ((r.get("products", []) or [{}])[0] or {}).get("marketing_status"),
                    "dosage_form": ((r.get("products", []) or [{}])[0] or {}).get("dosage_form"),
                    "submission_status": ((r.get("submissions", []) or [{}])[0] or {}).get("submission_status"),
                    "submission_status_date": ((r.get("submissions", []) or [{}])[0] or {}).get("submission_status_date"),
                }
                for r in drugsfda_results[:20]
            ],
        },
        "trial_registry_layer": {
            "required_field_coverage": trial_field_coverage,
            "sample_studies": [{field: t.get(field) for field in required_trial_fields} for t in trials[:20]],
        },
        "landscape_layer": {
            "total_data_candidates": len(data_candidates),
            "trial_count": len(trials),
            "pubmed_article_count": len(pubmed_articles),
            "europe_pmc_count": len((source_payloads.get("europe_pmc", {}) or {}).get("papers", []) or []),
        },
        "insight_inputs": {
            "note": "Objective evidence inputs only. Subjective recommendations are intentionally excluded.",
        },
    }
