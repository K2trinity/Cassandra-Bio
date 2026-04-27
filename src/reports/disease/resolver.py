from __future__ import annotations

import re
from urllib.parse import quote

from .condition_matcher import condition_variants, normalize_condition_text
from .models import DiseaseProfile


EXPERT_SEARCH_BASE = "https://clinicaltrials.gov/expert-search"


class DiseaseResolver:
    def resolve(self, user_query: str) -> DiseaseProfile:
        disease_name = _extract_disease_name(user_query)
        canonical = _canonical_condition(disease_name)
        variants = condition_variants(canonical)
        normalized_terms = sorted({normalize_condition_text(term) for term in variants})
        return DiseaseProfile(
            query=str(user_query or "").strip(),
            disease_name=canonical,
            canonical_condition=canonical,
            condition_terms=variants,
            normalized_terms=normalized_terms,
            expert_topic_url=build_expert_topic_url(canonical),
            expert_full_match_url=build_expert_full_match_url(canonical),
        )


def build_expert_topic_url(disease_name: str) -> str:
    return f"{EXPERT_SEARCH_BASE}?term={quote(disease_name, safe='')}&viewType=Topic"


def build_expert_full_match_url(disease_name: str) -> str:
    expression = f"AREA[Condition]COVERAGE[FullMatch[{disease_name}]]"
    return f"{EXPERT_SEARCH_BASE}?term={quote(expression, safe='')}&viewType=Card&sort=StudyFirstPostDate"


def _extract_disease_name(user_query: str) -> str:
    text = re.sub(r"\s+", " ", str(user_query or "")).strip()
    patterns = [
        r"^(?:please\s+)?(?:can you\s+)?(?:conduct|perform|run|create|generate|write|prepare)\s+(?:a\s+|an\s+)?(?:comprehensive\s+|full\s+|complete\s+)?(?:disease\s+)?(?:survey|landscape|overview|review|report|analysis)\s+(?:on|of|about|for)\s+(.+)$",
        r"^(?:i\s+)?need\s+(?:a\s+|an\s+)?(?:comprehensive\s+|full\s+|complete\s+)?(?:disease\s+)?(?:survey|landscape|overview|review|report|analysis)\s+(?:on|of|about|for)\s+(.+)$",
        r"^(?:comprehensive\s+|full\s+|complete\s+)?(?:disease\s+)?(?:survey|landscape|overview|review|report|analysis)\s+(?:on|of|about|for)\s+(.+)$",
        r"^(.+?)\s+(?:survey|landscape|overview|review|report|analysis|pipeline)\s*$",
    ]
    for pattern in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            return _clean_candidate(match.group(1))
    return _clean_candidate(text)


def _clean_candidate(value: str) -> str:
    text = str(value or "").strip()
    text = re.split(r"\s+(?:with|using|based on|from)\s+", text, maxsplit=1, flags=re.IGNORECASE)[0]
    text = re.split(r"[,;:|]", text, maxsplit=1)[0]
    text = re.sub(r"^(?:the|a|an)\s+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "Disease"


def _canonical_condition(value: str) -> str:
    normalized = normalize_condition_text(value)
    if normalized == "alzheimer disease":
        return "Alzheimer Disease"
    words = []
    for word in _clean_candidate(value).split():
        words.append(_title_case_condition_token(word))
    return " ".join(words)


def _title_case_condition_token(value: str) -> str:
    if "/" in value:
        return "/".join(_title_case_condition_token(part) for part in value.split("/"))
    if value.isupper() and len(value) <= 6:
        return value
    return value[:1].upper() + value[1:].lower()
