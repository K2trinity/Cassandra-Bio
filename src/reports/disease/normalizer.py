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

    return ClinicalTrialRecord(
        study_title=title or "Untitled Clinical Trial",
        nct_number=nct,
        status=status,
        conditions=conditions,
        interventions=interventions,
        sponsor=sponsor,
        study_type=study_type,
        study_first_posted=_date_from_sources(
            payload,
            metadata,
            status_module,
            "study_first_posted",
            "studyFirstPostDate",
            "studyFirstPostDateStruct",
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
