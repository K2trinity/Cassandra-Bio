from __future__ import annotations

import re
from collections import Counter
from datetime import date

from .models import ClinicalTrialRecord, PipelineRiskRecord


TERMINAL_STATUSES = {
    "COMPLETED",
    "TERMINATED",
    "WITHDRAWN",
}

INTERVENTION_TYPE_CATEGORIES = {
    "DRUG": "drug",
    "BIOLOGICAL": "biological",
    "BIOLOGIC": "biological",
    "DEVICE": "device",
    "PROCEDURE": "procedure",
    "BEHAVIORAL": "behavioral intervention",
    "DIETARY_SUPPLEMENT": "dietary supplement",
    "DIAGNOSTIC_TEST": "diagnostic test",
    "RADIATION": "radiation",
    "GENETIC": "genetic intervention",
    "COMBINATION_PRODUCT": "combination product",
    "OTHER": "other",
}


def categorize_interventions(
    interventions: list[str],
    intervention_types: list[str] | None = None,
) -> str:
    text = _normalize_intervention_text(interventions)
    text_category = _category_from_intervention_text(text)
    source_category = _category_from_intervention_types(intervention_types or [])

    if text_category and text_category != "other":
        if not source_category or source_category in {"drug", "biological", "other"}:
            return text_category
        return source_category
    return source_category or text_category


class RuleBasedRiskEngine:
    def __init__(self, current_date: date | None = None) -> None:
        self.current_date = current_date or date.today()

    def build(
        self,
        records: list[ClinicalTrialRecord],
        disease_name: str,
    ) -> list[PipelineRiskRecord]:
        categories = [
            categorize_interventions(record.interventions, record.intervention_types)
            for record in records
        ]
        category_counts = Counter(category for category in categories if category)

        return [
            self._build_record(
                record=record,
                category=category,
                category_count=category_counts.get(category, 0),
                disease_name=disease_name,
            )
            for record, category in zip(records, categories)
        ]

    def _build_record(
        self,
        *,
        record: ClinicalTrialRecord,
        category: str,
        category_count: int,
        disease_name: str,
    ) -> PipelineRiskRecord:
        timeline_signal, timeline_evidence = self._timeline_signal(record)
        competition_signal, competition_evidence = self._competition_signal(
            category=category,
            category_count=category_count,
            disease_name=disease_name,
        )

        return PipelineRiskRecord(
            nct_number=record.nct_number,
            study_title=record.study_title,
            sponsor=record.sponsor,
            status=record.status,
            intervention_category=category,
            timeline_signal=timeline_signal,
            timeline_evidence=timeline_evidence,
            competition_signal=competition_signal,
            competition_evidence=competition_evidence,
        )

    def _timeline_signal(self, record: ClinicalTrialRecord) -> tuple[str, str]:
        status = record.status.strip().upper()
        if record.study_first_posted is None:
            return (
                "Data insufficient",
                f"Study first posted missing; status {status}; age unavailable.",
            )

        age_years = (self.current_date - record.study_first_posted).days / 365.0
        evidence = (
            f"Study first posted {record.study_first_posted.isoformat()}; "
            f"status {status}; age {age_years:.1f} years."
        )

        if status in TERMINAL_STATUSES:
            return "Low", evidence

        high_cutoff = _subtract_years(self.current_date, 5)
        medium_cutoff = _subtract_years(self.current_date, 2)
        if record.study_first_posted < high_cutoff:
            return "High", evidence
        if record.study_first_posted <= medium_cutoff:
            return "Medium", evidence
        return "Low", evidence

    def _competition_signal(
        self,
        *,
        category: str,
        category_count: int,
        disease_name: str,
    ) -> tuple[str, str]:
        if not category:
            return (
                "Data insufficient",
                f"No intervention category available for {disease_name}.",
            )

        evidence = (
            f"{category_count} retained {disease_name} studies share "
            f"intervention category {category}."
        )
        if category_count >= 8:
            return "High", evidence
        if 3 <= category_count <= 7:
            return "Medium", evidence
        return "Low", evidence


def _normalize_intervention_text(interventions: list[str]) -> str:
    text = " ".join(intervention.strip().lower() for intervention in interventions)
    return re.sub(r"\s+", " ", text).strip()


def _category_from_intervention_text(text: str) -> str:
    if not text:
        return ""

    if _has_amyloid_term(text) and _has_antibody_term(text):
        return "amyloid antibody"
    if any(term in text for term in ("diagnostic", "imaging", "pet", "mri", "biomarker")):
        return "diagnostic or imaging"
    if "tau" in text and any(term in text for term in ("therapy", "drug", "treatment")):
        return "tau therapy"
    if "cell" in text or "stem cell" in text:
        return "cell therapy"
    if any(term in text for term in ("device", "stimulation", "wearable")):
        return "device"
    if any(term in text for term in ("behavioral", "cognitive behavioral", "psychotherapy")):
        return "behavioral intervention"
    if any(term in text for term in ("care", "caregiver", "telehealth")):
        return "care delivery"
    if any(term in text for term in ("small molecule", "inhibitor", "oral")):
        return "small molecule"
    return "other"


def _category_from_intervention_types(intervention_types: list[str]) -> str:
    categories: list[str] = []
    for intervention_type in intervention_types:
        normalized = _normalize_intervention_type(intervention_type)
        category = INTERVENTION_TYPE_CATEGORIES.get(normalized)
        if category and category not in categories:
            categories.append(category)

    if not categories:
        return ""

    non_other_categories = [category for category in categories if category != "other"]
    if not non_other_categories:
        return "other"
    if len(non_other_categories) == 1:
        return non_other_categories[0]
    return "mixed intervention"


def _normalize_intervention_type(value: str) -> str:
    text = str(value or "").strip().upper()
    return re.sub(r"[\s-]+", "_", text)


def _subtract_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year - years)
    except ValueError:
        return value.replace(year=value.year - years, day=28)


def _has_amyloid_term(text: str) -> bool:
    return "amyloid" in text or "abeta" in text or re.search(r"\ba\s*beta\b", text) is not None


def _has_antibody_term(text: str) -> bool:
    return any(term in text for term in ("antibody", "monoclonal", "mab"))
