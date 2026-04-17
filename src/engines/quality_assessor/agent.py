"""Quality Assessor Agent — data completeness, source diversity, timeliness, confidence."""

from __future__ import annotations

import importlib
import re
from collections import Counter
from datetime import datetime
from typing import Any, Dict, List


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:
        import logging
        return logging.getLogger(__name__)


logger = _resolve_logger()

REQUIRED_FIELDS = ["title", "source", "summary", "pmid"]
CURRENT_YEAR = datetime.now().year


class QualityAssessorAgent:
    """Assess data quality and produce a confidence grade."""

    def assess(
        self,
        harvested_data: List[Dict[str, Any]],
        slot_a_data: Dict[str, Any],
        slot_b_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        if not harvested_data:
            return {
                "completeness": {"field_coverage": {}, "overall_completeness": 0.0},
                "source_diversity_score": 0.0,
                "timeliness": {"year_distribution": {}, "recency_score": 0.0},
                "bias_indicators": [],
                "confidence_grade": "D",
                "confidence_score": 0.0,
                "rationale": "No data available for assessment.",
            }

        completeness = self._check_completeness(harvested_data)
        diversity = self._score_source_diversity(harvested_data)
        timeliness = self._assess_timeliness(harvested_data)
        bias = self._detect_bias_indicators(harvested_data)

        evidence_grade_score = 0.0
        evidence_synthesis = slot_a_data.get("evidence_synthesis", {})
        if isinstance(evidence_synthesis, dict):
            grade_scores = evidence_synthesis.get("grade_scores", {})
            if isinstance(grade_scores, dict):
                evidence_grade_score = float(grade_scores.get("score", 0))

        composite = (
            completeness["overall_completeness"] * 0.25
            + diversity * 0.25
            + timeliness["recency_score"] * 0.25
            + min(evidence_grade_score / 5.0, 1.0) * 0.25
        )
        confidence_score = round(composite, 3)
        grade = self._compute_confidence_grade(confidence_score)

        rationale_parts = []
        if completeness["overall_completeness"] < 0.5:
            rationale_parts.append("Low field completeness in harvested records.")
        if diversity < 0.4:
            rationale_parts.append("Limited source diversity — mostly single-source data.")
        if timeliness["recency_score"] < 0.4:
            rationale_parts.append("Data skews toward older publications.")
        if bias:
            rationale_parts.append(f"{len(bias)} potential bias indicator(s) detected.")
        if not rationale_parts:
            rationale_parts.append("Data quality metrics are within acceptable ranges.")

        return {
            "completeness": completeness,
            "source_diversity_score": round(diversity, 3),
            "timeliness": timeliness,
            "bias_indicators": bias,
            "confidence_grade": grade,
            "confidence_score": confidence_score,
            "rationale": " ".join(rationale_parts),
        }

    def _check_completeness(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not records:
            return {"field_coverage": {}, "overall_completeness": 0.0}

        total = len(records)
        field_counts: Dict[str, int] = {f: 0 for f in REQUIRED_FIELDS}

        for rec in records:
            if not isinstance(rec, dict):
                continue
            for field in REQUIRED_FIELDS:
                val = rec.get(field)
                if val and str(val).strip():
                    field_counts[field] += 1

        coverage = {f: round(c / total, 3) for f, c in field_counts.items()}
        overall = round(sum(coverage.values()) / len(coverage), 3) if coverage else 0.0

        return {"field_coverage": coverage, "overall_completeness": overall}

    def _score_source_diversity(self, records: List[Dict[str, Any]]) -> float:
        sources = [str(r.get("source") or "unknown") for r in records if isinstance(r, dict)]
        if not sources:
            return 0.0

        unique = len(set(sources))
        total = len(sources)
        counter = Counter(sources)
        max_share = max(counter.values()) / total if total else 1.0

        diversity = min(1.0, (unique / 5.0) * 0.5 + (1.0 - max_share) * 0.5)
        return round(diversity, 3)

    def _assess_timeliness(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        years: List[int] = []
        for rec in records:
            if not isinstance(rec, dict):
                continue
            meta = rec.get("metadata") if isinstance(rec.get("metadata"), dict) else {}
            year_str = str(meta.get("year") or rec.get("year") or rec.get("publication_year") or "")
            match = re.search(r"(19|20)\d{2}", year_str)
            if match:
                years.append(int(match.group(0)))

        if not years:
            return {"year_distribution": {}, "recency_score": 0.0}

        dist = dict(Counter(years))
        recent_count = sum(1 for y in years if y >= CURRENT_YEAR - 3)
        recency_score = round(recent_count / len(years), 3)

        return {"year_distribution": dist, "recency_score": recency_score}

    def _detect_bias_indicators(self, records: List[Dict[str, Any]]) -> List[Dict[str, str]]:
        indicators: List[Dict[str, str]] = []
        sources = [str(r.get("source") or "") for r in records if isinstance(r, dict)]
        counter = Counter(sources)
        total = len(sources)

        if total > 0:
            for src, count in counter.items():
                if count / total > 0.8 and total >= 5:
                    indicators.append({
                        "type": "source_concentration",
                        "detail": f"{src} accounts for {count}/{total} records ({round(count/total*100)}%)",
                    })

        sponsor_pattern = re.compile(r"funded by|sponsored by|grant from", re.IGNORECASE)
        sponsored_count = 0
        for rec in records:
            if not isinstance(rec, dict):
                continue
            text = str(rec.get("summary") or rec.get("abstract") or "")
            if sponsor_pattern.search(text):
                sponsored_count += 1
        if sponsored_count > 0 and total > 0 and sponsored_count / total > 0.5:
            indicators.append({
                "type": "funding_bias",
                "detail": f"{sponsored_count}/{total} records mention explicit funding/sponsorship",
            })

        return indicators

    def _compute_confidence_grade(self, score: float) -> str:
        if score >= 0.8:
            return "A"
        if score >= 0.6:
            return "B"
        if score >= 0.4:
            return "C"
        return "D"


def create_quality_assessor() -> QualityAssessorAgent:
    return QualityAssessorAgent()
