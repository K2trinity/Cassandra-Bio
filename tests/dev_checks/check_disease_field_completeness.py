"""
Disease-oriented field completeness checks.

This script provides two suites:
1) Stub suite (deterministic, offline): validates profile field completeness,
   drug-class normalization, target normalization, and chart/table readiness.
2) Live-harvest suite (optional): validates BioHarvest contract plus disease
   profile completeness built from real harvested payloads.

Usage:
    python scripts/dev_checks/check_disease_field_completeness.py
    python scripts/dev_checks/check_disease_field_completeness.py --live-harvest --query "cervical squamous cell carcinoma PD-1"
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.engines.harvest.agent import BioHarvestAgent
from src.agents.supervisor import _build_biomedical_profile
from src.graph.contracts import validate_bioharvest_output
from src.engines.report_engine.utils.chart_injector import ChartInjector


REQUIRED_PROFILE_FIELDS = {
    "analysis_focus",
    "disease_areas",
    "drug_baselines",
    "target_signals",
    "company_entities",
    "drug_class_distribution",
    "drug_catalog",
    "clinical_data",
    "evidence_stats",
}

REQUIRED_CLINICAL_DATA_FIELDS = {
    "trial_records",
    "phase_distribution",
    "status_distribution",
    "trial_field_coverage",
}

REQUIRED_CATALOG_FIELDS = {
    "asset_name",
    "drug_class",
    "target",
    "sponsor",
    "phase",
    "status",
    "reference",
}


def _build_stub_harvest_payload() -> Dict[str, Any]:
    results = [
        {
            "source": "ClinicalTrials.gov",
            "nct_id": "NCT10000001",
            "title": "Nivolumab anti-PD-1 monoclonal antibody in cervical cancer",
            "interventions": "Nivolumab monoclonal antibody",
            "target": "Programmed cell death protein 1 (PD1)",
            "sponsor": "Bristol Myers Squibb",
            "phase": "Phase 3",
            "status": "RECRUITING",
            "enrollment": "480",
            "primary_outcome_measures": "Overall survival",
            "secondary_outcome_measures": "PFS",
            "study_design": "Randomized",
            "metadata": {
                "nct_id": "NCT10000001",
                "target_description": "CD279",
                "interventions": "Nivolumab",
            },
        },
        {
            "source": "ClinicalTrials.gov",
            "nct_id": "NCT10000002",
            "title": "Atezolizumab anti PD-L1 mAb",
            "interventions": "Atezolizumab (anti-PD-L1 mAb)",
            "target": "CD274/PD-L1 axis",
            "sponsor": "Roche",
            "phase": "Phase 2",
            "status": "COMPLETED",
            "enrollment": "210",
            "primary_outcome_measures": "ORR",
            "secondary_outcome_measures": "DOR",
            "study_design": "Open label",
            "metadata": {
                "nct_id": "NCT10000002",
                "target_description": "Programmed death ligand 1",
                "interventions": "Atezolizumab",
            },
        },
        {
            "source": "ClinicalTrials.gov",
            "nct_id": "NCT10000003",
            "title": "Trastuzumab emtansine ADC",
            "interventions": "Trastuzumab emtansine antibody-drug conjugate",
            "target": "ERBB2/HER2",
            "sponsor": "Roche",
            "phase": "Phase 2",
            "status": "ACTIVE_NOT_RECRUITING",
            "metadata": {
                "nct_id": "NCT10000003",
                "interventions": "T-DM1 ADC",
            },
        },
        {
            "source": "ClinicalTrials.gov",
            "nct_id": "NCT10000004",
            "title": "Osimertinib EGFR inhibitor",
            "interventions": "Osimertinib small-molecule kinase inhibitor",
            "target": "Epidermal growth factor receptor",
            "sponsor": "AstraZeneca",
            "phase": "Phase 1",
            "status": "COMPLETED",
            "metadata": {
                "nct_id": "NCT10000004",
                "interventions": "EGFR inhibitor",
            },
        },
        {
            "source": "ClinicalTrials.gov",
            "nct_id": "NCT10000005",
            "title": "Tisagenlecleucel CAR-T",
            "interventions": "CAR-T cell therapy",
            "target": "CD19",
            "sponsor": "Novartis",
            "phase": "Phase 2",
            "status": "RECRUITING",
            "metadata": {
                "nct_id": "NCT10000005",
                "interventions": "CAR-T",
            },
        },
        {
            "source": "ClinicalTrials.gov",
            "nct_id": "NCT10000006",
            "title": "BNT122 mRNA vaccine",
            "interventions": "mRNA vaccine",
            "target": "neoantigen",
            "sponsor": "BioNTech",
            "phase": "Phase 1",
            "status": "NOT_YET_RECRUITING",
            "metadata": {
                "nct_id": "NCT10000006",
                "interventions": "mRNA platform",
            },
        },
    ]

    return {
        "results": results,
        "data_layers": {
            "disease_layer": {"conditions_from_trials": ["Cervical Squamous Cell Carcinoma"]},
            "target_layer": {
                "target_proxy_distribution": {
                    "PD1": 2,
                    "Programmed cell death protein 1": 1,
                    "CD279": 1,
                    "PD-L1": 2,
                    "CD274": 1,
                    "ERBB2": 2,
                    "HER2": 1,
                    "EGFR": 1,
                }
            },
            "pipeline_layer": {
                "phase_distribution": {"Phase 3": 1, "Phase 2": 3, "Phase 1": 2},
                "status_distribution": {
                    "RECRUITING": 2,
                    "COMPLETED": 2,
                    "ACTIVE_NOT_RECRUITING": 1,
                    "NOT_YET_RECRUITING": 1,
                },
            },
            "company_layer": {
                "sponsor_distribution": {
                    "Roche": 2,
                    "Bristol Myers Squibb": 1,
                    "AstraZeneca": 1,
                    "Novartis": 1,
                    "BioNTech": 1,
                }
            },
        },
        "source_payloads": {"openfda": {"counts": {"label": 0, "event": 0, "drugsfda": 0}}},
    }


def _check_profile_structure(profile: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    missing_top = sorted(REQUIRED_PROFILE_FIELDS - set(profile.keys()))
    if missing_top:
        errors.append(f"Missing top-level profile fields: {missing_top}")

    clinical_data = profile.get("clinical_data", {})
    if not isinstance(clinical_data, dict):
        errors.append("clinical_data is not a dict")
    else:
        missing_clinical = sorted(REQUIRED_CLINICAL_DATA_FIELDS - set(clinical_data.keys()))
        if missing_clinical:
            errors.append(f"Missing clinical_data fields: {missing_clinical}")

    catalog = profile.get("drug_catalog", [])
    if not isinstance(catalog, list):
        errors.append("drug_catalog is not a list")
    elif catalog:
        first_row = catalog[0] if isinstance(catalog[0], dict) else {}
        missing_catalog = sorted(REQUIRED_CATALOG_FIELDS - set(first_row.keys()))
        if missing_catalog:
            errors.append(f"drug_catalog row missing fields: {missing_catalog}")

    return errors


def run_stub_suite() -> bool:
    print("\n=== Stub Disease Completeness Suite ===")
    payload = _build_stub_harvest_payload()

    state = {
        "harvested_data": payload["results"],
        "harvest_data_layers": payload["data_layers"],
        "harvest_source_payloads": payload["source_payloads"],
        "text_evidence": [{"quote": "stub evidence"}],
        "forensic_evidence": [{"figure_id": "Figure 1"}],
        "project_name": "Cervical SCC",
    }

    profile = _build_biomedical_profile(state)

    errors = _check_profile_structure(profile)
    if errors:
        print("[FAIL] Stub profile structure checks failed")
        for err in errors:
            print(f"  - {err}")
        return False

    class_names = {x.get("name") for x in profile.get("drug_class_distribution", []) if isinstance(x, dict)}
    required_classes = {
        "Monoclonal Antibody",
        "ADC",
        "Small Molecule",
        "Cell Therapy",
        "RNA Therapy",
    }
    missing_classes = sorted(required_classes - class_names)
    if missing_classes:
        print("[FAIL] Drug class normalization failed")
        print(f"  - Missing classes: {missing_classes}")
        print(f"  - Observed classes: {sorted(class_names)}")
        return False

    target_counts = {
        x.get("name"): int(x.get("count", 0))
        for x in profile.get("target_signals", [])
        if isinstance(x, dict) and x.get("name")
    }

    if target_counts.get("PD-1", 0) < 4:
        print("[FAIL] Target normalization did not merge PD-1 synonyms as expected")
        print(f"  - target_counts: {target_counts}")
        return False

    if target_counts.get("PD-L1", 0) < 3:
        print("[FAIL] Target normalization did not merge PD-L1 synonyms as expected")
        print(f"  - target_counts: {target_counts}")
        return False

    if target_counts.get("HER2", 0) < 3:
        print("[FAIL] Target normalization did not merge HER2 synonyms as expected")
        print(f"  - target_counts: {target_counts}")
        return False

    injector = ChartInjector()
    evidence = {"harvested_data": payload["results"]}

    class_chart = injector._make_drug_class_chart(evidence)
    if class_chart is None:
        print("[FAIL] Drug class chart was not generated")
        return False

    target_chart = injector._make_target_signal_chart(evidence)
    if target_chart is None:
        print("[FAIL] Target signal chart was not generated")
        return False

    labels = set((target_chart.content or {}).get("labels", []))
    if "PD-1" not in labels or "PD-L1" not in labels:
        print("[FAIL] Target chart labels do not contain canonical terms")
        print(f"  - labels: {sorted(labels)}")
        return False

    asset_table = injector._make_asset_catalog_table(evidence)
    if asset_table is None:
        print("[FAIL] Asset catalog table was not generated")
        return False

    trial_matrix = injector._make_trial_matrix_table(evidence)
    if trial_matrix is None:
        print("[FAIL] Trial matrix table was not generated")
        return False

    matrix_headers = set((trial_matrix.content or {}).get("headers", []))
    required_matrix_headers = {"NCT", "Title", "Phase", "Status", "Enroll", "Primary EP", "Secondary EP", "Sponsor"}
    if not required_matrix_headers.issubset(matrix_headers):
        print("[FAIL] Trial matrix headers incomplete")
        print(f"  - headers: {sorted(matrix_headers)}")
        return False

    print("[PASS] Stub profile completeness + normalization + chart/table checks")
    return True


def run_live_suite(query: str, max_results: int) -> bool:
    print("\n=== Live Harvest Disease Completeness Suite ===")
    print(f"Query: {query}")

    if not os.getenv("GOOGLE_CLOUD_PROJECT"):
        print("[SKIP] Live harvest suite skipped: GOOGLE_CLOUD_PROJECT is not configured")
        return True

    try:
        payload = BioHarvestAgent().run(user_query=query, max_results_per_source=max_results)
    except Exception as exc:
        print(f"[FAIL] Live harvest execution failed: {exc}")
        return False

    valid, errors = validate_bioharvest_output(payload)
    if not valid:
        print("[FAIL] Live harvest output contract validation failed")
        for err in errors[:20]:
            print(f"  - {err}")
        return False

    state = {
        "harvested_data": payload.get("results", []),
        "harvest_data_layers": payload.get("data_layers", {}),
        "harvest_source_payloads": payload.get("source_payloads", {}),
        "text_evidence": [],
        "forensic_evidence": [],
        "project_name": query,
    }

    profile = _build_biomedical_profile(state)
    structure_errors = _check_profile_structure(profile)
    if structure_errors:
        print("[FAIL] Live profile structure checks failed")
        for err in structure_errors:
            print(f"  - {err}")
        return False

    trial_cov = (profile.get("clinical_data", {}) or {}).get("trial_field_coverage", {})
    if not isinstance(trial_cov, dict) or not trial_cov:
        print("[FAIL] trial_field_coverage is missing or empty")
        return False

    print("[PASS] Live harvest contract + disease profile completeness checks")
    print(
        "[INFO] Summary: "
        f"disease_areas={len(profile.get('disease_areas', []))}, "
        f"drug_classes={len(profile.get('drug_class_distribution', []))}, "
        f"target_signals={len(profile.get('target_signals', []))}, "
        f"trial_records={(profile.get('clinical_data', {}) or {}).get('trial_records', 0)}"
    )
    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Disease-oriented field completeness checks")
    parser.add_argument(
        "--query",
        default="cervical squamous cell carcinoma PD-1",
        help="Live harvest query",
    )
    parser.add_argument(
        "--live-harvest",
        action="store_true",
        help="Run live BioHarvest suite in addition to stub suite",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Max results per source for live harvest",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("=" * 88)
    print("Disease-Oriented Field Completeness Check")
    print("=" * 88)

    all_ok = run_stub_suite()
    if args.live_harvest:
        all_ok = run_live_suite(args.query, args.max_results) and all_ok

    print("\n" + "=" * 88)
    print("Final Result:", "PASS" if all_ok else "FAIL")
    print("=" * 88)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
