from __future__ import annotations

import re
from typing import Iterable

from .models import DiseaseProfile


BROAD_NON_ANCHOR_TERMS = {
    "care delivery",
    "caregiver",
    "caregiver education",
    "cognitive behavioral therapy",
    "cognitive dysfunction",
    "cognitive impairment",
    "dementia",
    "education",
    "mild cognitive impairment",
    "nursing career",
}

APOSTROPHELESS_POSSESSIVE_EPONYMS = {
    "alzheimers": "alzheimer",
    "crohns": "crohn",
    "huntingtons": "huntington",
    "parkinsons": "parkinson",
}


def normalize_condition_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\b([a-z0-9]+)(?:'s|\s+s)(?=\s+disease\b)", r"\1", text)
    for alias, stem in APOSTROPHELESS_POSSESSIVE_EPONYMS.items():
        text = re.sub(rf"\b{alias}(?=\s+disease\b)", stem, text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def condition_variants(disease_name: str) -> list[str]:
    cleaned = _title_case_entity(disease_name)
    normalized = normalize_condition_text(cleaned)
    if normalized == "alzheimer disease":
        return ["Alzheimer Disease", "Alzheimer's Disease", "Alzheimers Disease"]
    return [cleaned]


def conditions_full_match(conditions: Iterable[str], profile: DiseaseProfile) -> bool:
    allowed = set(profile.normalized_terms)
    if not allowed:
        allowed = {normalize_condition_text(term) for term in profile.condition_terms}
    for condition in conditions or []:
        normalized = normalize_condition_text(str(condition))
        if normalized in allowed:
            return True
        if normalized in BROAD_NON_ANCHOR_TERMS:
            continue
    return False


def _title_case_entity(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9' /-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    words = []
    lower_words = {"and", "or", "of", "in", "with", "for"}
    for index, word in enumerate(text.split()):
        lowered = word.lower()
        if index > 0 and lowered in lower_words:
            words.append(lowered)
        else:
            words.append(_title_case_token(word))
    return " ".join(words)


def _title_case_token(value: str) -> str:
    if "/" in value:
        return "/".join(_title_case_token(part) for part in value.split("/"))
    if value.isupper() and len(value) <= 6:
        return value
    return value[:1].upper() + value[1:].lower()
