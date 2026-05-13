from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date
from typing import Any, Callable, Iterator

from .clinicaltrials_harvester import (
    ClinicalTrialsCompanyHarvester,
    ClinicalTrialsConditionDiscovery,
    ClinicalTrialsDiseaseHarvester,
)
from .company_routes import NoopCompanyRouteProvider, resolve_analysis_target
from .ir_builder import DiseaseReportIRBuilder
from .landscape import assign_landscape_strata
from .models import ClinicalTrialRecord
from .narrative import DiseaseReportNarrativeService
from .normalizer import normalize_trial_payload
from .package_builder import DiseaseReportPackageBuilder
from .pipeline import DAGPipeline, PipelineStage
from .relevance import DiseaseRelevanceGate
from .report_kline_bridge import ReportKlineBridge
from .renderer_adapter import DiseaseReportRendererAdapter
from .resolver import DiseaseResolver
from .risk_engine import RuleBasedRiskEngine


ANALYSIS_FOCUS = "DISEASE_REPORT_PIPELINE"
COMPANY_ANALYSIS_FOCUS = "COMPANY_CLINICALTRIALS_PIPELINE"
DEFAULT_COMPANY_MAX_TRIALS = 100


class DiseaseReportOrchestrator:
    def __init__(
        self,
        *,
        clinicaltrials_get_json: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        clinicaltrials_get_text: Callable[[str], str] | None = None,
        renderer_adapter: Any | None = None,
        max_workers: int = 4,
        current_date_for_tests: str | None = None,
        company_route_provider: Any | None = None,
        narrative_service: Any | None = None,
        report_kline_bridge: Any | None = None,
    ) -> None:
        self.max_workers = max(1, int(max_workers))
        self.resolver = DiseaseResolver()
        self.condition_discovery = ClinicalTrialsConditionDiscovery(
            get_text=clinicaltrials_get_text,
        )
        self.harvester = ClinicalTrialsDiseaseHarvester(
            get_json=clinicaltrials_get_json,
        )
        self.company_harvester = ClinicalTrialsCompanyHarvester(
            get_json=clinicaltrials_get_json,
        )
        current_date = date.fromisoformat(current_date_for_tests) if current_date_for_tests else None
        self.risk_engine = RuleBasedRiskEngine(current_date=current_date)
        self.package_builder = DiseaseReportPackageBuilder()
        self.relevance_gate = DiseaseRelevanceGate()
        self.company_route_provider = company_route_provider or NoopCompanyRouteProvider()
        self.narrative_service = narrative_service or DiseaseReportNarrativeService()
        self.ir_builder = DiseaseReportIRBuilder()
        self.renderer_adapter = renderer_adapter or DiseaseReportRendererAdapter()
        self.report_kline_bridge = report_kline_bridge or ReportKlineBridge()

    def run(
        self,
        user_query: str,
        output_dir: str = "final_reports",
        max_trials: int = 50,
        narrative_language: str = "zh",
        analysis_target_type: str = "auto",
    ) -> dict[str, Any]:
        final_state: dict[str, Any] | None = None
        for _node_name, state in self.stream(
            user_query=user_query,
            output_dir=output_dir,
            max_trials=max_trials,
            narrative_language=narrative_language,
            analysis_target_type=analysis_target_type,
        ):
            final_state = state
        if final_state is None:
            return {
                "user_query": user_query,
                "status": "failed",
                "analysis_focus": ANALYSIS_FOCUS,
                "errors": ["Disease report stream yielded no states."],
            }
        return final_state

    def stream(
        self,
        user_query: str,
        output_dir: str = "final_reports",
        max_trials: int = 50,
        narrative_language: str = "zh",
        analysis_target_type: str = "auto",
    ) -> Iterator[tuple[str, dict[str, Any]]]:
        context: dict[str, Any] = {
            "analysis_target_type": analysis_target_type,
            "max_trials": max_trials,
            "narrative_language": narrative_language,
            "output_dir": output_dir,
            "user_query": user_query,
        }
        yield from self._build_pipeline().run(context)

    def _build_pipeline(self) -> DAGPipeline:
        return DAGPipeline(
            [
                PipelineStage("harvest", self._run_harvest_stage),
                PipelineStage(
                    "package",
                    self._run_package_stage,
                    depends_on=("harvest",),
                ),
                PipelineStage(
                    "writer",
                    self._run_writer_stage,
                    depends_on=("package",),
                ),
                PipelineStage(
                    "report_to_kline_bridge",
                    self._run_report_to_kline_bridge_stage,
                    depends_on=("writer",),
                ),
            ]
        )

    def _run_harvest_stage(self, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        user_query = context["user_query"]
        max_trials = context["max_trials"]
        analysis_target_type = context["analysis_target_type"]
        profile = resolve_analysis_target(
            user_query,
            requested_target_type=analysis_target_type,
            disease_resolver=self.resolver,
        )

        record_limit = max_trials
        if profile.target_type == "company":
            record_limit = _company_record_limit(max_trials)
            raw_result = self.company_harvester.fetch_raw_studies(profile, max_records=record_limit)
            normalized_records = self._normalize_records(raw_result.studies)
            retained_records = normalized_records
            rejected_nct_numbers = list(raw_result.rejected_nct_numbers)
        else:
            profile = self.condition_discovery.discover(profile)
            raw_result = self.harvester.fetch_raw_studies(profile, max_records=None)
            normalized_records = self._normalize_records(raw_result.studies)
            relevance_result = self.relevance_gate.filter_records(normalized_records, profile)
            retained_records = [
                assign_landscape_strata(record)
                for record in relevance_result.retained
            ]
            rejected_nct_numbers = _unique_values(
                list(raw_result.rejected_nct_numbers) + list(relevance_result.rejected_nct_numbers)
            )
        risk_records = self.risk_engine.build(
            retained_records,
            disease_name=profile.disease_name,
        )
        harvest_state = self._build_harvest_state(
            user_query=user_query,
            profile=profile,
            retained_records=retained_records,
            raw_records=raw_result.studies,
            rejected_nct_numbers=rejected_nct_numbers,
        )
        context.update(
            {
                "harvest_state": harvest_state,
                "profile": profile,
                "raw_records": raw_result.studies,
                "raw_result": raw_result,
                "record_limit": record_limit,
                "rejected_nct_numbers": rejected_nct_numbers,
                "retained_records": retained_records,
                "risk_records": risk_records,
            }
        )
        return "harvester", harvest_state

    def _run_package_stage(self, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        package = self.package_builder.build(
            disease_profile=context["profile"],
            retained_records=context["retained_records"],
            raw_count=context["raw_result"].raw_count,
            rejected_nct_numbers=context["rejected_nct_numbers"],
            risk_records=context["risk_records"],
            max_records=context["record_limit"],
        )
        package = self.company_route_provider.enrich(package)
        package_state = self._build_package_state(
            candidate_state=context["harvest_state"],
            retained_records=list(package.clinical_trials),
            raw_records=context["raw_records"],
            rejected_nct_numbers=context["rejected_nct_numbers"],
        )
        narratives = self.narrative_service.generate(
            package,
            language="en" if context["narrative_language"] == "en" else "zh",
        )
        handoff_state = {
            **package_state,
            "status": "handoff_complete",
            "handoff_complete": True,
            "disease_report_package": package.model_dump(mode="json"),
            "disease_report_narratives": narratives.model_dump(mode="json"),
        }
        context.update(
            {
                "handoff_state": handoff_state,
                "narratives": narratives,
                "package": package,
            }
        )
        return "extension_handoff", handoff_state

    def _run_writer_stage(self, context: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        package = context["package"]
        narratives = context["narratives"]
        report_ir = self.ir_builder.build(package, narratives=narratives)
        artifacts = self.renderer_adapter.render_all(
            document_ir=report_ir,
            output_dir=context["output_dir"],
            project_name=package.disease_profile.disease_name,
        )
        writer_state = {
            **context["handoff_state"],
            "status": "writer_complete",
            "writer_complete": True,
            "final_report": artifacts.markdown_content,
            "final_report_markdown": artifacts.markdown_content,
            "final_report_path": artifacts.markdown_path,
            "final_report_html_path": artifacts.html_path,
            "final_report_pdf_path": artifacts.pdf_path,
            "final_report_ir_path": artifacts.ir_path,
            "report_ir": report_ir,
        }
        context.update({"report_ir": report_ir, "writer_state": writer_state})
        return "writer", writer_state

    def _run_report_to_kline_bridge_stage(
        self,
        context: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        writer_state = context["writer_state"]
        bridge_result = self.report_kline_bridge.run(
            context["package"],
            report_path=writer_state.get("final_report_path"),
        )
        bridge_state = {
            **writer_state,
            "status": writer_state.get("status", "writer_complete"),
            "kline_bridge_complete": True,
            "kline_bridge": bridge_result,
            "kline_bridge_status": bridge_result.get("status"),
            "kline_bridge_skip_reason": bridge_result.get("skip_reason"),
            "kline_ticker": bridge_result.get("ticker"),
            "kline_url": bridge_result.get("kline_url"),
            "kline_event_count": bridge_result.get("event_count", 0),
        }
        context["bridge_state"] = bridge_state
        return "report_to_kline_bridge", bridge_state

    def _normalize_records(self, raw_records: list[dict[str, Any]]) -> list[ClinicalTrialRecord]:
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            return list(executor.map(normalize_trial_payload, raw_records))

    def _build_harvest_state(
        self,
        *,
        user_query: str,
        profile: Any,
        retained_records: list[ClinicalTrialRecord],
        raw_records: list[dict[str, Any]],
        rejected_nct_numbers: list[str],
    ) -> dict[str, Any]:
        trial_records = [record.model_dump(mode="json") for record in retained_records]
        analysis_focus = COMPANY_ANALYSIS_FOCUS if profile.target_type == "company" else ANALYSIS_FOCUS
        target_name = profile.target_name or profile.company_name or profile.disease_name
        biomedical_profile = {
            "analysis_focus": analysis_focus,
            "target_type": profile.target_type,
            "target_name": target_name,
            "disease_areas": [profile.disease_name] if profile.target_type == "disease" else [],
            "company_entities": (
                [{"name": profile.company_name, "role": "sponsor"}]
                if profile.company_name
                else []
            ),
            "clinical_data": {
                "trial_records": len(trial_records),
                "raw_records": len(raw_records),
                "rejected_records": len(rejected_nct_numbers),
            },
            "evidence_stats": {
                "clinical_trial_records": len(retained_records),
            },
        }
        if profile.company_name:
            biomedical_profile["company_name"] = profile.company_name

        return {
            "user_query": user_query,
            "project_name": target_name,
            "status": "harvest_complete",
            "analysis_focus": analysis_focus,
            "harvested_data": [_harvested_data_item(record) for record in retained_records],
            "biomedical_profile": biomedical_profile,
            "disease_areas": biomedical_profile["disease_areas"],
            "company_entities": biomedical_profile["company_entities"],
            "clinical_data": {
                "trial_records": len(trial_records),
                "raw_records": len(raw_records),
                "rejected_records": len(rejected_nct_numbers),
                "trial_record_details": trial_records,
                "raw_record_details": deepcopy(raw_records),
                "rejected_nct_numbers": list(rejected_nct_numbers),
            },
            "evidence_stats": {
                "clinical_trial_records": len(retained_records),
            },
            "extension_payloads": {},
            "errors": [],
        }

    def _build_package_state(
        self,
        *,
        candidate_state: dict[str, Any],
        retained_records: list[ClinicalTrialRecord],
        raw_records: list[dict[str, Any]],
        rejected_nct_numbers: list[str],
    ) -> dict[str, Any]:
        selected_nct_numbers = {record.nct_number for record in retained_records}
        selected_raw_records = [
            record
            for record in raw_records
            if _raw_record_nct_number(record) in selected_nct_numbers
        ]
        trial_records = [record.model_dump(mode="json") for record in retained_records]
        return {
            **candidate_state,
            "harvested_data": [_harvested_data_item(record) for record in retained_records],
            "clinical_data": {
                **candidate_state["clinical_data"],
                "trial_records": len(trial_records),
                "raw_records": len(selected_raw_records),
                "trial_record_details": trial_records,
                "raw_record_details": deepcopy(selected_raw_records),
                "rejected_records": len(rejected_nct_numbers),
                "rejected_nct_numbers": list(rejected_nct_numbers),
            },
            "evidence_stats": {
                "clinical_trial_records": len(retained_records),
            },
            "candidate_harvested_data": deepcopy(candidate_state["harvested_data"]),
            "candidate_clinical_data": deepcopy(candidate_state["clinical_data"]),
            "candidate_evidence_stats": deepcopy(candidate_state["evidence_stats"]),
        }


def _harvested_data_item(record: ClinicalTrialRecord) -> dict[str, Any]:
    payload = record.model_dump(mode="json")
    return {
        "source": "clinicaltrials.gov",
        "title": record.study_title,
        "nct_id": record.nct_number,
        "nct_number": record.nct_number,
        "status": record.status,
        "conditions": list(record.conditions),
        "interventions": list(record.interventions),
        "sponsor": record.sponsor,
        "study_type": record.study_type,
        "url": record.source_url,
        "metadata": payload,
    }


def _raw_record_nct_number(record: dict[str, Any]) -> str:
    protocol = record.get("protocolSection") if isinstance(record, dict) else None
    identification = (
        protocol.get("identificationModule")
        if isinstance(protocol, dict)
        else None
    )
    if not isinstance(identification, dict):
        return ""
    return str(identification.get("nctId") or "").strip()


def _unique_values(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        unique.append(text)
        seen.add(text)
    return unique


def _company_record_limit(max_trials: int) -> int:
    return max(DEFAULT_COMPANY_MAX_TRIALS, int(max_trials))


__all__ = ["ANALYSIS_FOCUS", "DiseaseReportOrchestrator"]
