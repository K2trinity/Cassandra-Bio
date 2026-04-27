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


def normalize_condition_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = re.sub(r"\balzheimer[' ]?s\b", "alzheimer", text)
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
        if normalized in BROAD_NON_ANCHOR_TERMS:
            continue
        if normalized in allowed:
            return True
    return False


def _title_case_entity(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9' -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" .")
    words = []
    lower_words = {"and", "or", "of", "in", "with", "for"}
    for index, word in enumerate(text.split()):
        lowered = word.lower()
        if index > 0 and lowered in lower_words:
            words.append(lowered)
        elif word.isupper() and len(word) <= 6:
            words.append(word)
        else:
            words.append(word[:1].upper() + word[1:].lower())
    return " ".join(words)
