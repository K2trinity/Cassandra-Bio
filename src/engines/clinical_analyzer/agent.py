"""Clinical Analyzer Agent — pipeline matrix, phase transitions, safety signals."""

from __future__ import annotations

import importlib
import re
from collections import defaultdict
from typing import Any, Dict, List, Set


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

PHASE_ORDER = ["Phase I", "Phase I/II", "Phase II", "Phase II/III", "Phase III", "Phase IV", "Approved"]

SAFETY_PATTERNS = [
    (r"serious adverse|severe adverse|\bSAE\b", "serious_adverse_event"),
    (r"black.?box warning", "black_box_warning"),
    (r"terminated|withdrawn", "trial_terminated"),
    (r"discontinu(?:ed|ation)\s+(?:due to|because of)\s+(?:adverse|safety|toxicity)", "discontinuation_safety"),
    (r"death|fatal(?:ity)?|mortality", "mortality_signal"),
    (r"dose.?limiting toxicit", "dose_limiting_toxicity"),
]


class ClinicalAnalyzerAgent:
    """Analyze clinical trial data for pipeline and safety insights."""

    def analyze(
        self,
        harvested_data: List[Dict[str, Any]],
        source_payloads: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not harvested_data:
            return {
                "pipeline_matrix": [],
                "phase_transitions": {"phase_counts": {}, "total_trials": 0},
                "safety_signals": [],
                "competition_landscape": {},
            }

        trial_records = [
            r for r in harvested_data
            if isinstance(r, dict) and (
                r.get("nct_id")
                or (isinstance(r.get("metadata"), dict) and r["metadata"].get("nct_id"))
                or r.get("source") == "ClinicalTrials.gov"
            )
        ]

        pipeline_matrix = self._build_pipeline_matrix(trial_records)
        phase_transitions = self._compute_phase_transitions(trial_records)
        safety_signals = self._extract_safety_signals(harvested_data)
        competition = self._map_competition(trial_records)

        return {
            "pipeline_matrix": pipeline_matrix,
            "phase_transitions": phase_transitions,
            "safety_signals": safety_signals,
            "competition_landscape": competition,
        }

    def _build_pipeline_matrix(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        combos: Dict[str, Dict[str, Any]] = {}

        for rec in records:
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            phase = str(meta.get("phase") or "Unknown")
            status = str(meta.get("status") or "Unknown")
            nct_id = str(rec.get("nct_id") or meta.get("nct_id") or "")

            indications = meta.get("conditions") or []
            if isinstance(indications, str):
                indications = [indications]
            if not indications:
                indications = ["Unknown"]

            interventions = meta.get("interventions") or []
            if isinstance(interventions, str):
                interventions = [interventions]
            if not interventions:
                interventions = ["Unknown"]

            for indication in indications:
                for intervention in interventions:
                    key = f"{indication}||{intervention}"
                    if key not in combos:
                        combos[key] = {
                            "indication": str(indication),
                            "intervention": str(intervention),
                            "phases": {},
                            "trial_count": 0,
                        }
                    entry = combos[key]
                    entry["trial_count"] += 1
                    phase_entry = entry["phases"].setdefault(phase, [])
                    phase_entry.append({"nct_id": nct_id, "status": status})

        return sorted(combos.values(), key=lambda x: x["trial_count"], reverse=True)

    def _compute_phase_transitions(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        phase_counts: Dict[str, int] = defaultdict(int)
        status_by_phase: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        for rec in records:
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            phase = str(meta.get("phase") or "Unknown")
            status = str(meta.get("status") or "Unknown")
            phase_counts[phase] += 1
            status_by_phase[phase][status] += 1

        return {
            "phase_counts": dict(phase_counts),
            "status_by_phase": {k: dict(v) for k, v in status_by_phase.items()},
            "total_trials": sum(phase_counts.values()),
        }

    def _extract_safety_signals(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        signals: List[Dict[str, Any]] = []

        for rec in records:
            if not isinstance(rec, dict):
                continue
            text = " ".join([
                str(rec.get("title") or ""),
                str(rec.get("summary") or rec.get("abstract") or ""),
            ])
            matched_types: List[str] = []
            for pattern, signal_type in SAFETY_PATTERNS:
                if re.search(pattern, text, re.IGNORECASE):
                    matched_types.append(signal_type)

            if matched_types:
                signals.append({
                    "title": str(rec.get("title") or ""),
                    "nct_id": str(rec.get("nct_id") or ""),
                    "pmid": str(rec.get("pmid") or ""),
                    "signal_types": matched_types,
                })

        return signals

    def _map_competition(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        by_target: Dict[str, Set[str]] = defaultdict(set)
        by_indication: Dict[str, Set[str]] = defaultdict(set)

        for rec in records:
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            interventions = meta.get("interventions") or []
            if isinstance(interventions, str):
                interventions = [interventions]
            conditions = meta.get("conditions") or []
            if isinstance(conditions, str):
                conditions = [conditions]
            targets = meta.get("targets") or []
            if isinstance(targets, str):
                targets = [targets]

            for target in targets:
                for intervention in interventions:
                    by_target[str(target)].add(str(intervention))
            for condition in conditions:
                for intervention in interventions:
                    by_indication[str(condition)].add(str(intervention))

        return {
            "by_target": {k: sorted(v) for k, v in by_target.items()},
            "by_indication": {k: sorted(v) for k, v in by_indication.items()},
        }


def create_clinical_analyzer() -> ClinicalAnalyzerAgent:
    return ClinicalAnalyzerAgent()
