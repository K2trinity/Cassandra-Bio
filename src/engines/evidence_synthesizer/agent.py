"""Evidence Synthesizer Agent — GRADE-lite evidence layering and endpoint extraction."""

from __future__ import annotations

import importlib
import re
from typing import Any, Dict, List


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

EVIDENCE_HIERARCHY = ["meta_analysis", "rct", "clinical_trial", "cohort", "case_report", "other"]

GRADE_WEIGHTS = {
    "meta_analysis": 5,
    "rct": 4,
    "clinical_trial": 3,
    "cohort": 2,
    "case_report": 1,
    "other": 0,
}


class EvidenceSynthesizerAgent:
    """Synthesize harvested biomedical records into layered evidence."""

    def synthesize(
        self,
        harvested_data: List[Dict[str, Any]],
        data_layers: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not harvested_data:
            return {
                "evidence_layers": {},
                "efficacy_endpoints": [],
                "conflicts": [],
                "grade_scores": {},
            }

        evidence_layers: Dict[str, List[Dict[str, Any]]] = {}
        all_endpoints: List[Dict[str, Any]] = []

        for record in harvested_data:
            if not isinstance(record, dict):
                continue
            level = self._classify_evidence_level(record)
            evidence_layers.setdefault(level, []).append({
                "title": str(record.get("title") or ""),
                "pmid": str(record.get("pmid") or ""),
                "nct_id": str(record.get("nct_id") or ""),
                "source": str(record.get("source") or ""),
            })

            text = " ".join([
                str(record.get("summary") or ""),
                str(record.get("abstract") or ""),
                str(record.get("title") or ""),
            ])
            endpoints = self._extract_efficacy_endpoints(text)
            for ep in endpoints:
                ep["source_title"] = str(record.get("title") or "")
                ep["evidence_level"] = level
            all_endpoints.extend(endpoints)

        conflicts = self._detect_conflicts(all_endpoints)
        grade_scores = self._compute_grade_scores(evidence_layers)

        return {
            "evidence_layers": {k: v for k, v in evidence_layers.items()},
            "efficacy_endpoints": all_endpoints,
            "conflicts": conflicts,
            "grade_scores": grade_scores,
        }

    def _classify_evidence_level(self, record: Dict[str, Any]) -> str:
        title = str(record.get("title") or "").lower()
        summary = str(record.get("summary") or record.get("abstract") or "").lower()
        source = str(record.get("source") or "").lower()
        metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
        phase = str(metadata.get("phase") or "").lower()
        nct_id = record.get("nct_id") or ""
        combined = f"{title} {summary}"

        if re.search(r"meta[\s-]?analysis|systematic review", combined):
            return "meta_analysis"
        if re.search(r"randomized controlled|randomised controlled|\brct\b", combined) or "phase iii" in phase:
            return "rct"
        if nct_id or "clinicaltrials" in source or re.search(r"phase [i|ii|iv]", combined):
            return "clinical_trial"
        if re.search(r"cohort|observational|retrospective|prospective study", combined):
            return "cohort"
        if re.search(r"case report|case series|single.?patient", combined):
            return "case_report"
        return "other"

    def _extract_efficacy_endpoints(self, text: str) -> List[Dict[str, Any]]:
        endpoints: List[Dict[str, Any]] = []
        patterns = [
            (r"overall\s+survival\s*\(?OS\)?\s*(?:was|of|:)?\s*([\d.]+)\s*(months?|years?)?", "overall_survival"),
            (r"(?:progression[- ]free\s+survival|PFS)\s*(?:was|of|:)?\s*([\d.]+)\s*(months?|years?)?", "pfs"),
            (r"(?:overall\s+response\s+rate|ORR)\s*(?:was|of|:)?\s*([\d.]+)\s*%?", "orr"),
            (r"(?:complete\s+response|CR)\s*(?:was|of|:)?\s*(?:in\s+)?([\d.]+)\s*%?", "cr"),
            (r"(?:partial\s+response|PR)\s*(?:was|of|:)?\s*(?:in\s+)?([\d.]+)\s*%?", "pr"),
        ]
        for pattern, ep_type in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                value = match.group(1)
                unit = match.group(2) if match.lastindex >= 2 else None
                endpoints.append({
                    "type": ep_type,
                    "value": float(value),
                    "unit": str(unit or "").strip() or None,
                    "raw_match": match.group(0).strip(),
                })
        return endpoints

    def _detect_conflicts(self, endpoints: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for ep in endpoints:
            by_type.setdefault(ep["type"], []).append(ep)

        conflicts: List[Dict[str, Any]] = []
        for ep_type, items in by_type.items():
            if len(items) < 2:
                continue
            values = [it["value"] for it in items]
            min_val, max_val = min(values), max(values)
            if max_val > 0 and (max_val - min_val) / max_val > 0.5:
                conflicts.append({
                    "endpoint_type": ep_type,
                    "min_value": min_val,
                    "max_value": max_val,
                    "spread_ratio": round((max_val - min_val) / max_val, 2),
                    "sources": [it.get("source_title", "") for it in items],
                })
        return conflicts

    def _compute_grade_scores(self, evidence_layers: Dict[str, List]) -> Dict[str, Any]:
        total_weight = 0
        total_records = 0
        per_level: Dict[str, int] = {}
        for level, records in evidence_layers.items():
            count = len(records)
            per_level[level] = count
            total_records += count
            total_weight += count * GRADE_WEIGHTS.get(level, 0)

        if total_records == 0:
            return {"overall": "D", "score": 0, "breakdown": {}}

        avg_weight = total_weight / total_records
        if avg_weight >= 4.0:
            grade = "A"
        elif avg_weight >= 3.0:
            grade = "B"
        elif avg_weight >= 2.0:
            grade = "C"
        else:
            grade = "D"

        return {
            "overall": grade,
            "score": round(avg_weight, 2),
            "breakdown": per_level,
        }


def create_evidence_synthesizer() -> EvidenceSynthesizerAgent:
    return EvidenceSynthesizerAgent()
