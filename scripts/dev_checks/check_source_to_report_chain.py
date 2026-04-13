"""
End-to-end chain checker for:
Clinical/API source payloads -> Supervisor workflow engines -> final report output.

What this script verifies:
1) BioHarvest output matches contract schema.
2) ClinicalTrials/OpenFDA source fields are preserved in payload projection.
3) Full supervisor pipeline runs through harvester/miner/auditor/writer.
4) Legacy risk-like keys are stripped before writer handoff.
5) Legacy risk sentinel values do not appear in the final report.

Default mode is fully stubbed (offline, deterministic).

Optional mode:
- --live-harvest: run real BioHarvest API harvesting and validate contract only.

Usage:
    python scripts/dev_checks/check_source_to_report_chain.py
    python scripts/dev_checks/check_source_to_report_chain.py --live-harvest
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from src.agents import supervisor
from src.graph.contracts import validate_bioharvest_output, validate_writer_input
from src.tools.source_field_mappings import project_source_payloads_for_frontend
from BioHarvestEngine.agent import BioHarvestAgent


LEGACY_RISK_SENTINEL = "LEGACY_RISK_SENTINEL_SHOULD_NOT_APPEAR"

REQUIRED_CLINICAL_FIELDS = {
    "nct_number",
    "study_url",
    "study_status",
    "study_results",
    "results_url",
    "phases",
    "study_design",
    "conditions",
    "interventions",
    "primary_outcome_measures",
    "secondary_outcome_measures",
    "other_outcome_measures",
    "sponsor",
    "collaborators",
    "funder_type",
    "sex",
    "age",
    "enrollment",
    "study_type",
    "start_date",
    "primary_completion_date",
    "completion_date",
    "first_posted",
    "results_first_posted",
    "last_update_posted",
    "study_documents",
}


@dataclass
class StubReportOutput:
    markdown_content: str
    markdown_path: str
    html_path: str
    pdf_path: str


def collect_risk_key_paths(obj: Any, path: str = "$") -> List[str]:
    """Collect paths of keys containing 'risk' (case-insensitive)."""
    matches: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            next_path = f"{path}.{key}"
            if "risk" in str(key).lower():
                matches.append(next_path)
            matches.extend(collect_risk_key_paths(value, next_path))
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            matches.extend(collect_risk_key_paths(item, f"{path}[{idx}]"))
    return matches


def contains_value(obj: Any, needle: str) -> bool:
    if isinstance(obj, dict):
        return any(contains_value(v, needle) for v in obj.values())
    if isinstance(obj, list):
        return any(contains_value(v, needle) for v in obj)
    return needle in str(obj)


def collect_value_paths(obj: Any, needle: str, path: str = "$") -> List[str]:
    """Collect object paths where a specific value substring appears."""
    matches: List[str] = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            matches.extend(collect_value_paths(value, needle, f"{path}.{key}"))
        return matches
    if isinstance(obj, list):
        for idx, item in enumerate(obj):
            matches.extend(collect_value_paths(item, needle, f"{path}[{idx}]"))
        return matches
    if needle in str(obj):
        matches.append(path)
    return matches


def build_stub_source_payloads() -> Dict[str, Any]:
    """Create a realistic multi-source payload with required trial/fda fields."""
    study = {
        "nct_number": "NCT01234567",
        "nct_id": "NCT01234567",
        "study_url": "https://clinicaltrials.gov/study/NCT01234567",
        "title": "Synthetic Trial Title",
        "official_title": "Synthetic Official Trial Title",
        "url": "https://clinicaltrials.gov/study/NCT01234567",
        "acronym": "SYN-CT",
        "study_status": "COMPLETED",
        "status": "COMPLETED",
        "why_stopped": "",
        "brief_summary": "Synthetic summary for chain checks.",
        "has_results": True,
        "study_results": "Results available",
        "results_url": "https://clinicaltrials.gov/study/NCT01234567/results",
        "conditions": "Melanoma",
        "interventions": "Nivolumab",
        "primary_outcome_measures": "Overall survival",
        "secondary_outcome_measures": "PFS",
        "other_outcome_measures": "QoL",
        "phases": "Phase 3",
        "phase": "Phase 3",
        "enrollment": "240",
        "study_type": "Interventional",
        "study_design": "Randomized; Double Blind",
        "sponsor": "Synthetic Biotech",
        "collaborators": "Synthetic CRO",
        "funder_type": "Industry",
        "sex": "All",
        "age": "Adult",
        "start_date": "2020-01-01",
        "primary_completion_date": "2024-01-01",
        "completion_date": "2024-06-01",
        "first_posted": "2019-12-01",
        "results_first_posted": "2024-09-01",
        "last_update_posted": "2025-01-15",
        "study_documents": "Protocol PDF",
        # Legacy noise field (must be removed before writer handoff)
        "legacy_risk_payload": LEGACY_RISK_SENTINEL,
    }

    source_payloads = {
        "clinicaltrials": {
            "studies": [study],
            "results_modules": {
                "NCT01234567": {
                    "has_results": True,
                    "results_url": "https://clinicaltrials.gov/study/NCT01234567/results",
                    "outcome_measures": [{"name": "Overall survival"}],
                    "adverse_events": {"serious": []},
                    "legacy_risk_module": LEGACY_RISK_SENTINEL,
                }
            },
        },
        "pubmed": {
            "pmids": ["12345678"],
            "articles": [
                {
                    "pmid": "12345678",
                    "title": "Synthetic PubMed Article",
                    "abstract": "Synthetic abstract.",
                    "authors": ["Alice", "Bob"],
                    "journal": "Synthetic Journal",
                    "pub_date": "2026-01-01",
                    "doi": "10.1000/synthetic.1",
                    "risk_comment_legacy": LEGACY_RISK_SENTINEL,
                }
            ],
        },
        "europe_pmc": {
            "papers": [],
        },
        "ncbi": {
            "pubmed": {"db": "pubmed", "query": "melanoma nivolumab", "count": 1, "ids": ["12345678"]},
            "gene": {"db": "gene", "query": "melanoma nivolumab", "count": 1, "ids": ["1"]},
            "protein": {"db": "protein", "query": "melanoma nivolumab", "count": 1, "ids": ["P1"]},
            "clinvar": {"db": "clinvar", "query": "melanoma nivolumab", "count": 0, "ids": []},
            "gds": {"db": "gds", "query": "melanoma nivolumab", "count": 0, "ids": []},
        },
        "openfda": {
            "label": {
                "results": [
                    {
                        "id": "L1",
                        "effective_time": "20250101",
                        "indications_and_usage": ["Melanoma"],
                        "dosage_and_administration": ["IV"],
                        "contraindications": ["None"],
                        "boxed_warning": ["Immune adverse reactions"],
                        "warnings": ["Use caution"],
                        "adverse_reactions": ["Fatigue"],
                        "purpose": ["Antineoplastic"],
                        "openfda": {
                            "brand_name": ["Opdivo"],
                            "generic_name": ["nivolumab"],
                            "manufacturer_name": ["Synthetic Pharma"],
                            "application_number": ["BLA125554"],
                            "product_type": ["HUMAN PRESCRIPTION DRUG"],
                        },
                    }
                ]
            },
            "event": {
                "results": [
                    {
                        "safetyreportid": "E1",
                        "receivedate": "20250201",
                        "occurcountry": "US",
                        "serious": "1",
                        "seriousnessdeath": "0",
                        "seriousnesslifethreatening": "0",
                        "patient": {
                            "patientsex": "1",
                            "patientonsetage": "63",
                            "reaction": [{"reactionmeddrapt": "Fatigue"}],
                            "drug": [{"medicinalproduct": "NIVOLUMAB", "drugcharacterization": "1"}],
                        },
                        "legacy_risk_flag": LEGACY_RISK_SENTINEL,
                    }
                ]
            },
            "drugsfda": {
                "results": [
                    {
                        "application_number": "BLA125554",
                        "sponsor_name": "Synthetic Pharma",
                        "openfda": {
                            "brand_name": ["Opdivo"],
                            "generic_name": ["nivolumab"],
                            "manufacturer_name": ["Synthetic Pharma"],
                        },
                        "products": [
                            {
                                "brand_name": "Opdivo",
                                "active_ingredients": [{"name": "nivolumab"}],
                                "route": "INTRAVENOUS",
                                "marketing_status": "Prescription",
                                "dosage_form": "Injection",
                            }
                        ],
                        "submissions": [
                            {
                                "submission_type": "ORIG",
                                "submission_status": "AP",
                                "submission_status_date": "20141222",
                            }
                        ],
                    }
                ]
            },
            "counts": {"label": 1, "event": 1, "drugsfda": 1},
        },
        "legacy_risk_source": LEGACY_RISK_SENTINEL,
    }

    return source_payloads


class StubBioHarvestAgent:
    def __init__(self, pdf_path: str):
        self._pdf_path = pdf_path

    def run(self, user_query: str, max_results_per_source: int = 20) -> Dict[str, Any]:
        source_payloads = build_stub_source_payloads()
        frontend_payload = project_source_payloads_for_frontend(source_payloads, max_items=max_results_per_source)

        return {
            "results": [
                {
                    "title": f"Stub PubMed paper for: {user_query}",
                    "source": "PubMed",
                    "snippet": "Synthetic evidence snippet",
                    "link": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                    "status": "PUBLISHED",
                    "date": "2026-01-01",
                    "year": 2026,
                    "authors": ["Alice", "Bob"],
                    "pmid": "12345678",
                    "local_path": self._pdf_path,
                    "legacy_risk_note": LEGACY_RISK_SENTINEL,
                },
                {
                    "title": "Stub Clinical Trial",
                    "source": "ClinicalTrials.gov",
                    "status": "COMPLETED",
                    "nct_id": "NCT01234567",
                    "metadata": {
                        "nct_id": "NCT01234567",
                        "risk_score": 9.8,
                        "legacy_risk_note": LEGACY_RISK_SENTINEL,
                    },
                },
            ],
            "stats": {
                "total": 2,
                "pubmed": 1,
                "trials": 1,
                "pdfs_downloaded": 1,
                "ncbi_records": 2,
                "openfda_records": 3,
                "legacy_risk_score": 9.9,
            },
            "data_layers": {
                "disease_layer": {"conditions_from_trials": ["Melanoma"]},
                "target_layer": {"target_proxy_distribution": {"PD-1": 3}},
                "pipeline_layer": {
                    "phase_distribution": {"Phase 3": 1},
                    "status_distribution": {"COMPLETED": 1},
                },
                "company_layer": {"sponsor_distribution": {"Synthetic Biotech": 1}},
                "legacy_risk_layer": LEGACY_RISK_SENTINEL,
            },
            "source_payloads": source_payloads,
            "frontend_payload": frontend_payload,
            "legacy_risk_payload": LEGACY_RISK_SENTINEL,
        }


class StubEvidenceAgent:
    def mine_evidence(self, pdf_path: str) -> Dict[str, Any]:
        return {
            "filename": Path(pdf_path).name,
            "paper_summary": "Synthetic paper summary for chain validation. " * 80,
            "risk_signals": [
                {
                    "source": "PMC123456",
                    "page_estimate": "12",
                    "quote": "Synthetic adverse event signal for normalization.",
                    "risk_level": "HIGH",
                    "risk_type": "safety_signal",
                    "explanation": "Synthetic explanation.",
                    "legacy_risk_payload": LEGACY_RISK_SENTINEL,
                }
            ],
        }


class StubForensicAgent:
    def audit_paper(self, pdf_path: str) -> List[Dict[str, Any]]:
        return [
            {
                "pdf_name": Path(pdf_path).name,
                "figure_id": "Figure 1",
                "caption": "Synthetic figure caption",
                "image_url": "/static/images/synthetic_fig1.png",
                "status": "UNASSESSED",
                "tampering_risk_score": 0.7,
                "legacy_risk_payload": LEGACY_RISK_SENTINEL,
            }
        ]


class SpyReportAgent:
    """Capture writer payload to assert that legacy risk keys were stripped."""

    last_payload: Dict[str, Any] | None = None

    def write_report_segmented(self, **payload: Any) -> StubReportOutput:
        return self._write(payload)

    def write_report(self, **payload: Any) -> StubReportOutput:
        return self._write(payload)

    @staticmethod
    def _write(payload: Dict[str, Any]) -> StubReportOutput:
        SpyReportAgent.last_payload = payload

        payload_for_validation = dict(payload)
        payload_for_validation.pop("use_segmented", None)

        writer_valid, writer_errors = validate_writer_input(payload_for_validation)
        if not writer_valid:
            raise AssertionError(f"Writer payload contract mismatch: {writer_errors}")

        # These three sections must be risk-key free before writer receives them.
        for section_name in ["harvest_data", "forensic_data", "evidence_data"]:
            section_obj = payload.get(section_name)
            risk_paths = collect_risk_key_paths(section_obj)
            if risk_paths:
                raise AssertionError(
                    f"Risk keys leaked into writer payload section '{section_name}': {risk_paths[:8]}"
                )

            sentinel_paths = collect_value_paths(section_obj, LEGACY_RISK_SENTINEL)
            if sentinel_paths:
                raise AssertionError(
                    f"Legacy risk sentinel leaked into writer payload section '{section_name}': {sentinel_paths[:8]}"
                )

        source_payloads = (payload.get("harvest_data") or {}).get("source_payloads", {})
        clinical_count = len((source_payloads.get("clinicaltrials") or {}).get("studies", []) or [])
        openfda_counts = (source_payloads.get("openfda") or {}).get("counts", {})

        markdown = "\n".join(
            [
                "# Chain Check Report",
                "",
                f"Query: {payload.get('user_query', '')}",
                f"Clinical studies in payload: {clinical_count}",
                f"openFDA counts: {json.dumps(openfda_counts, ensure_ascii=True)}",
                f"Evidence records: {len(payload.get('evidence_data', []) or [])}",
                f"Forensic records: {len(payload.get('forensic_data', []) or [])}",
                "Legacy risk sentinel visible: no",
            ]
        )

        reports_dir = PROJECT_ROOT / "final_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        md_path = reports_dir / "chain_check_report.md"
        html_path = reports_dir / "chain_check_report.html"
        pdf_path = reports_dir / "chain_check_report.pdf"
        md_path.write_text(markdown, encoding="utf-8")

        return StubReportOutput(
            markdown_content=markdown,
            markdown_path=str(md_path),
            html_path=str(html_path),
            pdf_path=str(pdf_path),
        )


def validate_clinical_field_coverage(source_payloads: Dict[str, Any]) -> Tuple[bool, List[str]]:
    studies = (source_payloads.get("clinicaltrials") or {}).get("studies", []) or []
    if not studies:
        return False, ["source_payloads.clinicaltrials.studies is empty"]

    study = studies[0]
    missing = sorted(field for field in REQUIRED_CLINICAL_FIELDS if field not in study)
    return len(missing) == 0, missing


def run_live_harvest_check(query: str, max_results: int) -> bool:
    print("\n=== Live Harvest Contract Check ===")
    try:
        payload = BioHarvestAgent().run(user_query=query, max_results_per_source=max_results)
    except Exception as exc:
        print(f"[FAIL] Live harvest execution failed: {exc}")
        return False

    valid, errors = validate_bioharvest_output(payload)
    if not valid:
        print("[FAIL] Live harvest contract validation failed")
        for err in errors[:20]:
            print(f"  - {err}")
        return False

    print("[PASS] Live harvest output matches contract")
    return True


def run_stubbed_chain_check(query: str) -> bool:
    print("\n=== Stubbed Source -> Engines -> Report Chain Check ===")

    temp_pdf = PROJECT_ROOT / "downloads" / "temp" / "stub_chain_test.pdf"
    temp_pdf.parent.mkdir(parents=True, exist_ok=True)
    temp_pdf.write_bytes(b"%PDF-1.4\n% synthetic test pdf\n")

    # 1) Validate stub harvester contract and source field coverage up-front.
    stub_harvest_payload = StubBioHarvestAgent(str(temp_pdf)).run(user_query=query, max_results_per_source=10)

    harvest_valid, harvest_errors = validate_bioharvest_output(stub_harvest_payload)
    if not harvest_valid:
        print("[FAIL] Stub harvest contract mismatch")
        for err in harvest_errors[:20]:
            print(f"  - {err}")
        return False
    print("[PASS] Stub harvest output matches contract")

    source_payloads = stub_harvest_payload.get("source_payloads", {})
    field_ok, missing = validate_clinical_field_coverage(source_payloads)
    if not field_ok:
        print("[FAIL] ClinicalTrials required field coverage failed")
        for item in missing:
            print(f"  - {item}")
        return False
    print("[PASS] ClinicalTrials required fields are present in source payloads")

    projected = project_source_payloads_for_frontend(source_payloads, max_items=10)
    projected_trials = projected.get("clinicaltrials", [])
    if not projected_trials:
        print("[FAIL] Frontend projection has no clinicaltrials rows")
        return False
    missing_projected = sorted(field for field in REQUIRED_CLINICAL_FIELDS if field not in projected_trials[0])
    if missing_projected:
        print("[FAIL] Frontend projection missing required clinical fields")
        for item in missing_projected:
            print(f"  - {item}")
        return False
    print("[PASS] Frontend projection retains required clinical fields")

    # 2) Patch supervisor factories and run the full workflow.
    original_bioharvest = supervisor.BioHarvestAgent
    original_evidence_factory = supervisor.create_evidence_agent
    original_forensic = supervisor.ForensicAuditorAgent
    original_report_factory = supervisor.create_report_agent

    SpyReportAgent.last_payload = None

    try:
        supervisor.BioHarvestAgent = lambda: StubBioHarvestAgent(str(temp_pdf))
        supervisor.create_evidence_agent = lambda: StubEvidenceAgent()
        supervisor.ForensicAuditorAgent = StubForensicAgent
        supervisor.create_report_agent = lambda: SpyReportAgent()

        final_state = supervisor.run_bio_short_seller(user_query=query, pdf_paths=[])
    finally:
        supervisor.BioHarvestAgent = original_bioharvest
        supervisor.create_evidence_agent = original_evidence_factory
        supervisor.ForensicAuditorAgent = original_forensic
        supervisor.create_report_agent = original_report_factory

    checks = {
        "status_complete": final_state.get("status") == "complete",
        "harvested_nonempty": len(final_state.get("harvested_data", [])) > 0,
        "evidence_nonempty": len(final_state.get("text_evidence", [])) > 0,
        "forensic_nonempty": len(final_state.get("forensic_evidence", [])) > 0,
        "report_nonempty": bool(final_state.get("final_report")),
        "writer_payload_captured": SpyReportAgent.last_payload is not None,
    }

    failed_checks = [name for name, ok in checks.items() if not ok]
    if failed_checks:
        print("[FAIL] End-to-end chain check failed")
        for item in failed_checks:
            print(f"  - {item}")
        return False

    print("[PASS] Supervisor chain completed through writer")

    report_markdown = str(final_state.get("final_report") or "")
    report_lower = report_markdown.lower()
    forbidden_tokens = [
        LEGACY_RISK_SENTINEL.lower(),
        "risk_score",
        "total_risk_score",
        "legacy_risk_payload",
    ]
    leaked_tokens = [token for token in forbidden_tokens if token in report_lower]
    if leaked_tokens:
        print("[FAIL] Final report leaked legacy risk tokens")
        for token in leaked_tokens:
            print(f"  - {token}")
        return False

    print("[PASS] Final report is not polluted by legacy risk fields")
    print(
        "[INFO] Summary: "
        f"harvested={len(final_state.get('harvested_data', []))}, "
        f"evidence={len(final_state.get('text_evidence', []))}, "
        f"forensic={len(final_state.get('forensic_evidence', []))}"
    )

    return True


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check Clinical/API -> engines -> report chain integrity and legacy risk isolation"
    )
    parser.add_argument(
        "--query",
        default="analyze nivolumab melanoma evidence chain",
        help="Query used for chain checks",
    )
    parser.add_argument(
        "--live-harvest",
        action="store_true",
        help="Also run real BioHarvest API check (network/API credentials required)",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Max results per source for --live-harvest",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    print("=" * 84)
    print("Clinical/API -> Engines -> Report Chain Integrity Check")
    print("=" * 84)

    all_ok = True

    if args.live_harvest:
        all_ok = run_live_harvest_check(args.query, args.max_results) and all_ok

    all_ok = run_stubbed_chain_check(args.query) and all_ok

    print("\n" + "=" * 84)
    print("Final Result:", "PASS" if all_ok else "FAIL")
    print("=" * 84)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
