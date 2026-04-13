
"""
Harvest contract + end-to-end dataflow smoke test.

What this script verifies:
1) BioHarvest output structure matches the contract schema.
2) Full supervisor dataflow can run through all nodes end-to-end.

Default behavior:
- Runs full dataflow in stub mode (no external API calls).

Optional:
- --live-harvest: run real BioHarvestAgent and validate its output contract.

Usage:
    python scripts/dev_checks/check_harvest_dataflow.py
    python scripts/dev_checks/check_harvest_dataflow.py --live-harvest
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.agents import supervisor
from src.graph.contracts import validate_bioharvest_output
from BioHarvestEngine.agent import BioHarvestAgent


@dataclass
class StubReportOutput:
    markdown_content: str
    markdown_path: str
    html_path: str
    pdf_path: str
    recommendation: str
    risk_score: float


class StubBioHarvestAgent:
    def __init__(self, pdf_path: str):
        self._pdf_path = pdf_path

    def run(self, user_query: str, max_results_per_source: int = 20) -> Dict[str, Any]:
        return {
            "results": [
                {
                    "title": f"Stub paper for: {user_query}",
                    "source": "PubMed",
                    "snippet": "Stub evidence snippet",
                    "link": "https://pubmed.ncbi.nlm.nih.gov/12345678/",
                    "status": "PUBLISHED",
                    "date": "2026-01-01",
                    "year": 2026,
                    "authors": ["Alice", "Bob"],
                    "pmid": "12345678",
                    "local_path": self._pdf_path,
                }
            ],
            "stats": {
                "total": 1,
                "pubmed": 1,
                "trials": 0,
                "pdfs_downloaded": 1,
                "ncbi_records": 1,
                "openfda_records": 0,
            },
            "data_layers": {
                "query_context": {
                    "query": user_query,
                }
            },
            "source_payloads": {
                "pubmed": {
                    "articles": [{"pmid": "12345678", "title": "Stub paper"}]
                }
            },
            "frontend_payload": {
                "nodes": [{"id": "Paper_12345678", "label": "Paper"}],
                "edges": [],
            },
        }


class StubEvidenceAgent:
    def mine_evidence(self, pdf_path: str) -> Dict[str, Any]:
        return {
            "filename": Path(pdf_path).name,
            "paper_summary": (
                "This is a synthetic summary for smoke testing. "
                "It is intentionally long enough to pass minimum checks. "
                "PMC123456 demonstrates potential adverse events under stress conditions. "
                "Repeated mentions keep the size above threshold while retaining deterministic behavior."
            )
            * 180,
            "risk_signals": [
                {
                    "source": "PMC123456",
                    "page_estimate": "12",
                    "quote": "Serious adverse events increased in treatment arm.",
                    "risk_level": "HIGH",
                    "risk_type": "safety_signal",
                    "explanation": "Higher incidence of severe adverse events observed.",
                }
            ],
        }


class StubForensicAgent:
    def audit_paper(self, pdf_path: str) -> List[Dict[str, Any]]:
        return [
            {
                "pdf_name": Path(pdf_path).name,
                "figure_id": "Figure_1",
                "caption": "No suspicious manipulation detected in this stub run.",
                "image_url": "",
                "status": "CLEAN",
                "tampering_risk_score": 0.1,
            }
        ]


class StubReportAgent:
    def write_report_segmented(self, **_: Any) -> StubReportOutput:
        return self._make_output()

    def write_report(self, **_: Any) -> StubReportOutput:
        return self._make_output()

    @staticmethod
    def _make_output() -> StubReportOutput:
        reports_dir = PROJECT_ROOT / "final_reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        md = reports_dir / "stub_dataflow_report.md"
        html = reports_dir / "stub_dataflow_report.html"
        pdf = reports_dir / "stub_dataflow_report.pdf"
        md.write_text("# Stub Dataflow Report\n\nPipeline smoke test passed.\n", encoding="utf-8")
        return StubReportOutput(
            markdown_content="# Stub Dataflow Report\n\nPipeline smoke test passed.\n",
            markdown_path=str(md),
            html_path=str(html),
            pdf_path=str(pdf),
            recommendation="HOLD",
            risk_score=3.2,
        )


def validate_harvest_contract(payload: Dict[str, Any], label: str) -> bool:
    is_valid, errors = validate_bioharvest_output(payload)
    if is_valid:
        print(f"[PASS] {label}: Harvest output matches contract")
        return True

    print(f"[FAIL] {label}: Harvest output contract mismatch")
    for err in errors[:20]:
        print(f"  - {err}")
    return False


def run_live_harvest_check(query: str, max_results: int) -> bool:
    print("\n=== Live Harvest Contract Check ===")
    try:
        agent = BioHarvestAgent()
        payload = agent.run(user_query=query, max_results_per_source=max_results)
    except Exception as exc:
        print(f"[FAIL] Live harvest execution failed: {exc}")
        return False
    return validate_harvest_contract(payload, "Live BioHarvest")


def run_stubbed_dataflow_smoke(query: str) -> Tuple[bool, Dict[str, Any]]:
    print("\n=== Stubbed End-to-End Dataflow Smoke Test ===")

    temp_pdf = PROJECT_ROOT / "downloads" / "temp" / "stub_pipeline_test.pdf"
    temp_pdf.parent.mkdir(parents=True, exist_ok=True)
    temp_pdf.write_bytes(b"%PDF-1.4\n% stub file for pipeline smoke test\n")

    original_bioharvest = supervisor.BioHarvestAgent
    original_evidence_factory = supervisor.create_evidence_agent
    original_forensic = supervisor.ForensicAuditorAgent
    original_report_factory = supervisor.create_report_agent

    try:
        supervisor.BioHarvestAgent = lambda: StubBioHarvestAgent(str(temp_pdf))
        supervisor.create_evidence_agent = lambda: StubEvidenceAgent()
        supervisor.ForensicAuditorAgent = StubForensicAgent
        supervisor.create_report_agent = lambda: StubReportAgent()

        final_state = supervisor.run_bio_short_seller(user_query=query, pdf_paths=[])

        checks = {
            "status_complete": final_state.get("status") == "complete",
            "harvested_nonempty": len(final_state.get("harvested_data", [])) > 0,
            "evidence_nonempty": len(final_state.get("text_evidence", [])) > 0,
            "forensic_nonempty": len(final_state.get("forensic_evidence", [])) > 0,
            "report_exists": bool(final_state.get("final_report")),
        }

        failed = [name for name, ok in checks.items() if not ok]
        if failed:
            print("[FAIL] Dataflow smoke test failed checks:")
            for item in failed:
                print(f"  - {item}")
            return False, final_state

        harvest_payload = {
            "results": final_state.get("harvested_data", []),
            "stats": {"total": len(final_state.get("harvested_data", []))},
            "data_layers": final_state.get("harvest_data_layers", {}),
            "source_payloads": final_state.get("harvest_source_payloads", {}),
            "frontend_payload": final_state.get("harvest_frontend_payload", {}),
        }

        if not validate_harvest_contract(harvest_payload, "Dataflow Harvest Handoff"):
            return False, final_state

        print("[PASS] End-to-end dataflow is connected and completed")
        print(
            "[INFO] Summary: "
            f"harvested={len(final_state.get('harvested_data', []))}, "
            f"evidence={len(final_state.get('text_evidence', []))}, "
            f"forensic={len(final_state.get('forensic_evidence', []))}"
        )
        return True, final_state

    finally:
        supervisor.BioHarvestAgent = original_bioharvest
        supervisor.create_evidence_agent = original_evidence_factory
        supervisor.ForensicAuditorAgent = original_forensic
        supervisor.create_report_agent = original_report_factory


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check harvest schema and full dataflow pipeline")
    parser.add_argument(
        "--query",
        default="analyze nivolumab hepatotoxicity in melanoma",
        help="Query used in live/stub checks",
    )
    parser.add_argument(
        "--live-harvest",
        action="store_true",
        help="Also run a real BioHarvestAgent check (requires valid API credentials)",
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

    print("=" * 72)
    print("Harvest Contract + Dataflow Pipeline Check")
    print("=" * 72)

    all_ok = True

    if args.live_harvest:
        all_ok = run_live_harvest_check(args.query, args.max_results) and all_ok

    dataflow_ok, _ = run_stubbed_dataflow_smoke(args.query)
    all_ok = dataflow_ok and all_ok

    print("\n" + "=" * 72)
    print("Final Result:", "PASS" if all_ok else "FAIL")
    print("=" * 72)

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
