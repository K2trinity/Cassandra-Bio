from __future__ import annotations

import re
from typing import NamedTuple, Protocol
from urllib.parse import quote

from .models import DiseaseProfile, DiseaseReportPackage
from .resolver import DiseaseResolver


class CompanyRouteProvider(Protocol):
    """Dormant extension point for company-route enrichment."""

    def enrich(self, package: DiseaseReportPackage) -> DiseaseReportPackage:
        """Return a disease report package with any route enrichment applied."""


class NoopCompanyRouteProvider:
    """Default provider that leaves the disease report package unchanged."""

    def enrich(self, package: DiseaseReportPackage) -> DiseaseReportPackage:
        return package


VALID_ANALYSIS_TARGET_TYPES = {"auto", "disease", "company"}

_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:"
    r"pharmaceuticals?|pharma|biopharma|biotherapeutics|biotech|therapeutics|"
    r"biosciences?|biologics|laboratories|labs|inc\.?|corp\.?|corporation|"
    r"ltd\.?|limited|plc|llc|company|co\."
    r")\b",
    flags=re.IGNORECASE,
)
_COMPANY_WORDING_RE = re.compile(r"\b(?:company|corporate|sponsor|pipeline)\b", flags=re.IGNORECASE)
_DISEASE_CUE_RE = re.compile(
    r"\b(?:disease|syndrome|disorder|cancer|carcinoma|tumou?r|infection|alzheimer|parkinson|crohn|diabetes)\b",
    flags=re.IGNORECASE,
)
_SPONSOR_SEARCH_BASE = "https://clinicaltrials.gov/search"


class _CompanySponsorIdentity(NamedTuple):
    display_name: str
    sponsor_query: str


_MODERNA_IDENTITY = _CompanySponsorIdentity(
    display_name="Moderna, Inc.",
    sponsor_query="ModernaTX, Inc.",
)
_KNOWN_SPONSOR_IDENTITIES = {
    "moderna": _MODERNA_IDENTITY,
    "moderna tx": _MODERNA_IDENTITY,
    "moderna therapeutics": _MODERNA_IDENTITY,
    "modernatx": _MODERNA_IDENTITY,
    "mrna": _MODERNA_IDENTITY,
}
_COMPANY_LEGAL_SUFFIX_RE = re.compile(
    r"\b(?:incorporated|inc|corp|corporation|ltd|limited|plc|llc|company|co)\b",
    flags=re.IGNORECASE,
)


def normalize_analysis_target_type(value: str | None) -> str:
    target_type = str(value or "auto").strip().lower() or "auto"
    if target_type not in VALID_ANALYSIS_TARGET_TYPES:
        allowed = ", ".join(sorted(VALID_ANALYSIS_TARGET_TYPES))
        raise ValueError(f"analysis_target_type must be one of: {allowed}")
    return target_type


def resolve_analysis_target(
    user_query: str,
    requested_target_type: str | None = None,
    disease_resolver: DiseaseResolver | None = None,
) -> DiseaseProfile:
    target_type = normalize_analysis_target_type(requested_target_type)
    resolver = disease_resolver or DiseaseResolver()

    if target_type == "disease":
        return resolver.resolve(user_query)

    if target_type == "company" or _should_infer_company(user_query):
        return _build_company_profile(user_query, _extract_company_name(user_query))

    return resolver.resolve(user_query)


def _should_infer_company(user_query: str) -> bool:
    text = str(user_query or "")
    company_name = _extract_company_name(text)
    if _DISEASE_CUE_RE.search(company_name):
        return False
    return bool(_COMPANY_WORDING_RE.search(text) or _COMPANY_SUFFIX_RE.search(company_name))


def _extract_company_name(user_query: str) -> str:
    text = re.sub(r"\s+", " ", str(user_query or "")).strip()
    patterns = [
        r"^company\s+pipeline\s+(?:for|on|of|about)\s+(.+)$",
        r"^(?:conduct|perform|run|create|generate|write|prepare|analyze|analyse)\s+(?:a\s+|an\s+)?(?:comprehensive\s+|full\s+|complete\s+)?(?:company\s+|corporate\s+)?(?:survey|landscape|overview|review|report|analysis)\s+(?:on|of|about|for)\s+(.+)$",
        r"^(?:company\s+|corporate\s+)?(?:pipeline|landscape|overview|review|report|analysis)\s+(?:on|of|about|for)\s+(.+)$",
        r"^(?:analyze|analyse|assess|evaluate|review)\s+(.+?)\s+(?:clinical\s+)?pipeline\s*$",
        r"^(.+?)\s+(?:clinical\s+)?pipeline\s*$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_company_name(match.group(1))
    return _clean_company_name(text)


def _clean_company_name(value: str) -> str:
    text = str(value or "").strip()
    text = re.split(r"[,;:|]", text, maxsplit=1)[0]
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:&|and)\s+co\.?$", " and Company", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+co\.?$", " Company", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "Unknown Company"


def _build_company_profile(user_query: str, company_name: str) -> DiseaseProfile:
    identity = _resolve_company_sponsor_identity(company_name)
    sponsor_url = _build_sponsor_trace_url(identity.sponsor_query)
    sponsor_query = (
        identity.sponsor_query
        if identity.sponsor_query != identity.display_name
        else None
    )
    return DiseaseProfile(
        query=str(user_query or "").strip() or identity.display_name,
        target_type="company",
        company_name=identity.display_name,
        sponsor_query=sponsor_query,
        target_name=identity.display_name,
        disease_name=identity.display_name,
        canonical_condition=identity.display_name,
        condition_terms=[],
        normalized_terms=[],
        expert_topic_url=sponsor_url,
        expert_full_match_url=sponsor_url,
    )


def _resolve_company_sponsor_identity(company_name: str) -> _CompanySponsorIdentity:
    normalized = _clean_company_name(company_name)
    known_identity = _KNOWN_SPONSOR_IDENTITIES.get(_company_lookup_key(normalized))
    if known_identity is not None:
        return known_identity
    return _CompanySponsorIdentity(display_name=normalized, sponsor_query=normalized)


def _company_lookup_key(value: str) -> str:
    text = str(value or "").replace("&", " and ").lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = _COMPANY_LEGAL_SUFFIX_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _build_sponsor_trace_url(sponsor_query: str) -> str:
    return f"{_SPONSOR_SEARCH_BASE}?query.spons={quote(sponsor_query, safe='')}"


__all__ = [
    "CompanyRouteProvider",
    "NoopCompanyRouteProvider",
    "VALID_ANALYSIS_TARGET_TYPES",
    "normalize_analysis_target_type",
    "resolve_analysis_target",
]
