from __future__ import annotations

from datetime import date, datetime
import html
import re
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

import requests
from pydantic import BaseModel, ConfigDict, Field

from .condition_matcher import conditions_full_match, normalize_condition_text
from .models import DiseaseProfile


CTGOV_STUDIES_URL = "https://clinicaltrials.gov/api/v2/studies"
LANDSCAPE_CANDIDATE_QUERIES: tuple[dict[str, Any], ...] = (
    {},
    {
        "aggFilters": "phase:3 4,status:act com",
        "sort": "LastUpdatePostDate:desc",
    },
    {
        "aggFilters": "phase:1 2,status:rec not",
        "sort": "StudyFirstPostDate:desc",
    },
    {
        "aggFilters": "results:with",
        "sort": "LastUpdatePostDate:desc",
    },
)

_FULL_MATCH_RE = re.compile(
    r"AREA\s*\[\s*Condition\s*\]\s*COVERAGE\s*\[\s*FullMatch\s*\[\s*(?P<condition>[^\]]+?)\s*\]\s*\]",
    flags=re.IGNORECASE,
)


class RawClinicalTrialsResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    studies: list[dict[str, Any]] = Field(default_factory=list)
    raw_count: int = 0
    rejected_nct_numbers: list[str] = Field(default_factory=list)


class ClinicalTrialsConditionDiscovery:
    def __init__(self, get_text: Callable[[str], str] | None = None):
        self._get_text = get_text or self._requests_get_text

    def discover(self, profile: DiseaseProfile) -> DiseaseProfile:
        topic_html = self._get_text(profile.expert_topic_url)
        candidates = _extract_condition_candidates(topic_html)
        if not candidates:
            return profile

        terms = list(profile.condition_terms)
        profile_terms = terms or [profile.canonical_condition]
        allowed = set(profile.normalized_terms) | {
            normalize_condition_text(term) for term in profile_terms
        }
        seen_terms = set(terms)

        for candidate in candidates:
            if normalize_condition_text(candidate) not in allowed:
                continue
            if candidate not in seen_terms:
                terms.append(candidate)
                seen_terms.add(candidate)

        if terms == profile.condition_terms:
            return profile

        normalized_terms = sorted({normalize_condition_text(term) for term in terms})
        return profile.model_copy(
            update={
                "condition_terms": terms,
                "normalized_terms": normalized_terms,
            }
        )

    @staticmethod
    def _requests_get_text(url: str) -> str:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text


class ClinicalTrialsDiseaseHarvester:
    def __init__(
        self,
        get_json: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
        page_size: int = 100,
        max_pages: int = 10,
    ):
        self._get_json = get_json or self._requests_get_json
        self.page_size = page_size
        self.max_pages = max(1, int(max_pages))

    def fetch_raw_studies(self, profile: DiseaseProfile, max_records: int | None = 50) -> RawClinicalTrialsResult:
        raw_count = 0
        retained_by_nct: dict[str, dict[str, Any]] = {}
        retained_without_nct: list[dict[str, Any]] = []
        rejected_nct_numbers: list[str] = []
        rejected_seen: set[str] = set()

        for condition_term in _query_condition_terms(profile):
            for candidate_params in LANDSCAPE_CANDIDATE_QUERIES:
                page_token: str | None = None
                seen_page_tokens: set[str | None] = set()
                pages_fetched = 0
                while pages_fetched < self.max_pages:
                    if page_token in seen_page_tokens:
                        break
                    seen_page_tokens.add(page_token)

                    params: dict[str, Any] = {
                        "query.cond": condition_term,
                        "pageSize": self.page_size,
                        "format": "json",
                    }
                    params.update(candidate_params)
                    if page_token:
                        params["pageToken"] = page_token

                    payload = self._get_json(CTGOV_STUDIES_URL, params)
                    studies = _extract_study_rows(payload)
                    raw_count += len(studies)
                    pages_fetched += 1

                    for study in studies:
                        nct_number = _extract_nct_number(study)
                        if conditions_full_match(_extract_conditions(study), profile):
                            if nct_number:
                                retained_by_nct.setdefault(nct_number, study)
                            else:
                                retained_without_nct.append(study)
                        elif nct_number:
                            if nct_number not in retained_by_nct and nct_number not in rejected_seen:
                                rejected_nct_numbers.append(nct_number)
                                rejected_seen.add(nct_number)

                    page_token = _extract_next_page_token(payload)
                    if not page_token:
                        break

        retained = list(retained_by_nct.values()) + retained_without_nct
        retained.sort(key=_sort_date_key, reverse=True)
        capped_retained = retained if max_records is None else retained[: max(0, int(max_records))]
        return RawClinicalTrialsResult(
            studies=capped_retained,
            raw_count=raw_count,
            rejected_nct_numbers=[
                nct_number for nct_number in rejected_nct_numbers if nct_number not in retained_by_nct
            ],
        )

    @staticmethod
    def _requests_get_json(url: str, params: dict[str, Any]) -> dict[str, Any]:
        response = requests.get(url, params=params, timeout=30)
        response.raise_for_status()
        return response.json()


def _extract_condition_candidates(topic_html: str) -> list[str]:
    raw_html = html.unescape(str(topic_html or ""))
    full_match_candidates = _extract_full_match_condition_candidates(raw_html)
    if full_match_candidates:
        return full_match_candidates
    return _extract_visible_anchor_condition_candidates(raw_html)


def _extract_full_match_condition_candidates(raw_html: str) -> list[str]:
    candidates: list[str] = []

    for href in _extract_href_values(raw_html):
        for term in parse_qs(urlsplit(href).query).get("term", []):
            _append_full_match_candidates(candidates, term)
        _append_full_match_candidates(candidates, href)

    _append_full_match_candidates(candidates, raw_html)
    return candidates


def _extract_visible_anchor_condition_candidates(raw_html: str) -> list[str]:
    candidates: list[str] = []
    for match in re.finditer(r"<a\b[^>]*>(?P<body>.*?)</a>", raw_html, flags=re.IGNORECASE | re.DOTALL):
        text = re.sub(r"<[^>]+>", " ", match.group("body"))
        candidate = _clean_condition_candidate(text)
        if candidate and candidate not in candidates:
            candidates.append(candidate)
    return candidates


def _extract_href_values(raw_html: str) -> list[str]:
    return [match.group("href") for match in re.finditer(r"""href\s*=\s*["'](?P<href>[^"']+)["']""", raw_html)]


def _append_full_match_candidates(candidates: list[str], value: str) -> None:
    for decoded in _decoded_text_layers(value):
        for match in _FULL_MATCH_RE.finditer(decoded):
            candidate = _clean_condition_candidate(match.group("condition"))
            if candidate and candidate not in candidates:
                candidates.append(candidate)


def _decoded_text_layers(value: str) -> list[str]:
    layers = []
    current = html.unescape(str(value or ""))
    for _ in range(4):
        if current not in layers:
            layers.append(current)
        decoded = unquote(current)
        if decoded == current:
            break
        current = decoded
    return layers


def _clean_condition_candidate(value: str) -> str:
    text = html.unescape(unquote(str(value or ""))).strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .")


def _query_condition_terms(profile: DiseaseProfile) -> list[str]:
    terms = list(profile.condition_terms) or [profile.canonical_condition]
    selected: list[str] = []
    seen_terms: set[str] = set()
    for term in terms:
        text = str(term or "").strip()
        if not text or text in seen_terms:
            continue
        selected.append(text)
        seen_terms.add(text)
    return selected or [profile.canonical_condition]


def _extract_study_rows(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    studies = payload.get("studies")
    if not isinstance(studies, list):
        return []
    return [study for study in studies if isinstance(study, dict)]


def _extract_next_page_token(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    token = payload.get("nextPageToken") or payload.get("next_page_token")
    if token is None and isinstance(payload.get("pagination"), dict):
        token = payload["pagination"].get("nextPageToken") or payload["pagination"].get("next_page_token")
    text = str(token or "").strip()
    return text or None


def _extract_nct_number(study: dict[str, Any]) -> str | None:
    value = _lookup_path(study, "protocolSection", "identificationModule", "nctId")
    if value is None:
        value = _lookup_any(
            study,
            "nctId",
            "nct_id",
            "nctNumber",
            "nct_number",
            "NCT Number",
            "NCTId",
            "NCT",
            "nct",
        )
    text = str(value or "").strip()
    return text or None


def _extract_conditions(study: dict[str, Any]) -> list[str]:
    value = _lookup_path(study, "protocolSection", "conditionsModule", "conditions")
    if value is None:
        value = _lookup_any(study, "conditions", "condition", "Conditions", "Condition")
    return _coerce_text_list(value)


def _extract_study_first_posted(study: dict[str, Any]) -> date | None:
    value = _lookup_path(study, "protocolSection", "statusModule", "studyFirstPostDateStruct", "date")
    if value is None:
        value = _lookup_any(
            study,
            "studyFirstPostDate",
            "studyFirstPostDateStruct",
            "study_first_posted",
            "firstPostedDate",
            "first_posted",
            "Study First Posted",
            "Study First Posted Date",
            "First Posted",
        )
    if isinstance(value, dict):
        value = value.get("date")
    return _parse_study_date(value)


def _lookup_path(value: dict[str, Any], *path: str) -> Any:
    current: Any = value
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _lookup_any(value: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in value:
            return value[key]
    return None


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, dict):
        return _coerce_text_list(_lookup_any(value, "name", "condition", "term", "text", "value"))
    if isinstance(value, list):
        items: list[str] = []
        for item in value:
            items.extend(_coerce_text_list(item))
        return items
    text = str(value).strip()
    return [text] if text else []


def _parse_study_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value

    text = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        try:
            return date.fromisoformat(text)
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}-\d{2}", text):
        year_text, month_text = text.split("-")
        try:
            return date(int(year_text), int(month_text), 1)
        except ValueError:
            return None
    if re.fullmatch(r"\d{4}", text):
        try:
            return date(int(text), 1, 1)
        except ValueError:
            return None
    return None


def _sort_date_key(study: dict[str, Any]) -> date:
    return _extract_study_first_posted(study) or date.min


__all__ = [
    "CTGOV_STUDIES_URL",
    "LANDSCAPE_CANDIDATE_QUERIES",
    "ClinicalTrialsConditionDiscovery",
    "ClinicalTrialsDiseaseHarvester",
    "RawClinicalTrialsResult",
]
