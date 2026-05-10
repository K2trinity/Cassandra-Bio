from __future__ import annotations

import re
from datetime import date
from typing import Any, Iterable

from .models import ClinicalTrialRecord


def normalize_trial_payload(payload: dict[str, Any]) -> ClinicalTrialRecord:
    protocol = _dict(payload.get("protocolSection"))
    identification = _dict(protocol.get("identificationModule"))
    status_module = _dict(protocol.get("statusModule"))
    conditions_module = _dict(protocol.get("conditionsModule"))
    interventions_module = _dict(protocol.get("armsInterventionsModule"))
    sponsors_module = _dict(protocol.get("sponsorCollaboratorsModule"))
    design_module = _dict(protocol.get("designModule"))
    outcomes_module = _dict(protocol.get("outcomesModule"))
    metadata = _dict(payload.get("metadata"))

    nct = _first_text(payload, metadata, identification, keys=("nct_number", "nct_id", "nctId"))
    title = _first_text(payload, metadata, identification, keys=("study_title", "title", "briefTitle", "officialTitle"))
    status = _first_text(
        payload,
        metadata,
        status_module,
        keys=("status", "study_status", "overall_status", "overallStatus"),
        default="Unknown",
    )
    conditions = _list_text(
        payload.get("conditions")
        or payload.get("condition")
        or metadata.get("conditions")
        or metadata.get("condition")
        or conditions_module.get("conditions")
    )
    interventions = _extract_interventions(payload, metadata, interventions_module)
    sponsor = _first_text(
        payload,
        metadata,
        _dict(sponsors_module.get("leadSponsor")),
        keys=("sponsor", "lead_sponsor", "trial_sponsor", "sponsor_name", "name"),
        default="Unknown",
    )
    study_type = _first_text(payload, metadata, design_module, keys=("study_type", "studyType"), default="Unknown")
    has_results = _bool_from_sources(payload, metadata, "hasResults", "has_results")
    result_label = "Results available" if has_results else "No posted results"

    return ClinicalTrialRecord(
        study_title=title or "Untitled Clinical Trial",
        nct_number=nct,
        status=status,
        phases=_split_phase_values(
            payload.get("phases")
            or payload.get("phase")
            or metadata.get("phases")
            or metadata.get("phase")
            or design_module.get("phases")
        ),
        has_results=has_results,
        study_results=_first_text(
            payload,
            metadata,
            keys=("study_results", "results_status"),
            default=result_label,
        ) or result_label,
        results_url=_first_text(
            payload,
            metadata,
            keys=("results_url",),
            default=f"https://clinicaltrials.gov/study/{nct}/results",
        ) or f"https://clinicaltrials.gov/study/{nct}/results",
        conditions=conditions,
        interventions=interventions,
        sponsor=sponsor,
        study_type=study_type,
        enrollment=_int_from_sources(
            payload,
            metadata,
            design_module.get("enrollmentInfo") if isinstance(design_module.get("enrollmentInfo"), dict) else {},
            keys=("enrollment", "enrollment_count", "count"),
        ),
        primary_outcome_measures=_outcome_measures(
            payload,
            metadata,
            outcomes_module,
            "primaryOutcomes",
            "primary_outcome_measures",
        ),
        secondary_outcome_measures=_outcome_measures(
            payload,
            metadata,
            outcomes_module,
            "secondaryOutcomes",
            "secondary_outcome_measures",
        ),
        study_first_posted=_date_from_sources(
            payload,
            metadata,
            status_module,
            "study_first_posted",
            "studyFirstPostDate",
            "studyFirstPostDateStruct",
        ),
        results_first_posted=_date_from_sources(
            payload,
            metadata,
            status_module,
            "results_first_posted",
            "resultsFirstPostDate",
            "resultsFirstPostDateStruct",
        ),
        last_update_posted=_date_from_sources(
            payload,
            metadata,
            status_module,
            "last_update_posted",
            "lastUpdatePostDate",
            "lastUpdatePostDateStruct",
        ),
        start_date=_date_from_sources(payload, metadata, status_module, "start_date", "startDate", "startDateStruct"),
        primary_completion_date=_date_from_sources(
            payload,
            metadata,
            status_module,
            "primary_completion_date",
            "primaryCompletionDate",
            "primaryCompletionDateStruct",
        ),
        completion_date=_date_from_sources(
            payload,
            metadata,
            status_module,
            "completion_date",
            "completionDate",
            "completionDateStruct",
        ),
        strata=_list_text(payload.get("strata") or metadata.get("strata")),
        primary_stratum=_first_text(
            payload,
            metadata,
            keys=("primary_stratum",),
            default="unclassified",
        ) or "unclassified",
        source_url=_first_text(
            payload,
            metadata,
            keys=("source_url", "study_url", "url"),
            default=f"https://clinicaltrials.gov/study/{nct}",
        ),
    )


def _dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _first_text(*sources: dict[str, Any], keys: Iterable[str], default: str | None = None) -> str | None:
    for source in sources:
        source_dict = _dict(source)
        for key in keys:
            value = source_dict.get(key)
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
    return default


def _list_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        nested = (
            value.get("conditions")
            or value.get("condition")
            or value.get("interventions")
            or value.get("intervention")
        )
        if nested is not None:
            return _list_text(nested)
        text = _first_text(value, keys=("name", "label", "condition", "interventionName"))
        return [text] if text else []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []

    try:
        iterator = iter(value)
    except TypeError:
        text = str(value).strip()
        return [text] if text else []

    values: list[str] = []
    for item in iterator:
        values.extend(_list_text(item))
    return values


def _extract_interventions(
    payload: dict[str, Any],
    metadata: dict[str, Any],
    interventions_module: dict[str, Any],
) -> list[str]:
    return _list_text(
        payload.get("interventions")
        or payload.get("intervention")
        or metadata.get("interventions")
        or metadata.get("intervention")
        or interventions_module.get("interventions")
        or interventions_module.get("intervention")
    )


def _split_phase_values(value: Any) -> list[str]:
    phases: list[str] = []
    for item in _list_text(value):
        for part in re.split(r"[,;/]", item):
            text = _canonical_phase_token(part)
            if text and text not in phases:
                phases.append(text)
    return phases


def _canonical_phase_token(value: Any) -> str:
    text = str(value or "").strip().upper()
    if not text:
        return ""
    normalized = re.sub(r"[\s_-]+", "_", text)
    compact = normalized.replace("_", "")
    if compact == "EARLYPHASE1":
        return "EARLY_PHASE1"
    phase_match = re.fullmatch(r"PHASE([1-4])", compact)
    if phase_match:
        return f"PHASE{phase_match.group(1)}"
    return normalized


def _bool_from_sources(
    payload: dict[str, Any],
    metadata: dict[str, Any],
    *keys: str,
) -> bool:
    for source in (payload, metadata):
        source_dict = _dict(source)
        for key in keys:
            value = source_dict.get(key)
            if isinstance(value, bool):
                return value
            if value is not None:
                return str(value).strip().lower() in {"true", "1", "yes", "y"}
    return False


def _int_from_sources(*sources: dict[str, Any], keys: Iterable[str]) -> int | None:
    for source in sources:
        source_dict = _dict(source)
        for key in keys:
            value = source_dict.get(key)
            if isinstance(value, dict):
                value = value.get("count")
            if value is None:
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
    return None


def _outcome_measures(
    payload: dict[str, Any],
    metadata: dict[str, Any],
    outcomes_module: dict[str, Any],
    nested_key: str,
    *flat_keys: str,
) -> list[str]:
    measures: list[str] = []
    for source in (payload, metadata):
        source_dict = _dict(source)
        for key in flat_keys:
            _extend_outcome_measures(measures, source_dict.get(key), split_text=True)
    _extend_outcome_measures(measures, outcomes_module.get(nested_key), split_text=False)
    return measures


def _extend_outcome_measures(measures: list[str], value: Any, *, split_text: bool) -> None:
    if value is None:
        return
    if isinstance(value, dict):
        text = _first_text(value, keys=("measure", "name", "label"))
        if text:
            _append_unique(measures, text)
        return
    if isinstance(value, str):
        parts = re.split(r"[;,]", value) if split_text else [value]
        for part in parts:
            _append_unique(measures, part)
        return

    try:
        iterator = iter(value)
    except TypeError:
        _append_unique(measures, str(value))
        return

    for item in iterator:
        _extend_outcome_measures(measures, item, split_text=split_text)


def _append_unique(values: list[str], value: str) -> None:
    text = value.strip()
    if text and text not in values:
        values.append(text)


def _date_from_sources(
    payload: dict[str, Any],
    metadata: dict[str, Any],
    status_module: dict[str, Any],
    *keys: str,
) -> date | None:
    for source in (payload, metadata, status_module):
        source_dict = _dict(source)
        for key in keys:
            parsed = _parse_date(source_dict.get(key))
            if parsed is not None:
                return parsed
    return None


def _parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, dict):
        return _parse_date(value.get("date"))

    text = str(value).strip()
    match = re.match(r"^(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", text)
    if not match:
        return None

    year = int(match.group(1))
    month = int(match.group(2) or 1)
    day = int(match.group(3) or 1)
    try:
        return date(year, month, day)
    except ValueError:
        return None
