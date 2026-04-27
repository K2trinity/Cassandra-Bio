from src.reports.disease.condition_matcher import (
    condition_variants,
    conditions_full_match,
    normalize_condition_text,
)
from src.reports.disease.resolver import DiseaseResolver, build_expert_full_match_url


def test_resolver_extracts_disease_from_report_prompt():
    profile = DiseaseResolver().resolve("conduct a comprehensive survey on Alzheimer disease")

    assert profile.disease_name == "Alzheimer Disease"
    assert profile.canonical_condition == "Alzheimer Disease"
    assert "Alzheimer's Disease" in profile.condition_terms
    assert profile.normalized_terms == ["alzheimer disease"]
    assert profile.expert_topic_url.endswith("term=Alzheimer%20Disease&viewType=Topic")
    assert "AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BAlzheimer%20Disease%5D%5D" in profile.expert_full_match_url


def test_resolver_handles_possessive_user_input():
    profile = DiseaseResolver().resolve("Alzheimer's disease pipeline")

    assert profile.disease_name == "Alzheimer Disease"
    assert set(profile.condition_terms) == {
        "Alzheimer Disease",
        "Alzheimer's Disease",
        "Alzheimers Disease",
    }


def test_normalize_condition_text_collapses_possessive_and_punctuation():
    assert normalize_condition_text("Alzheimer's Disease") == "alzheimer disease"
    assert normalize_condition_text("Alzheimers disease") == "alzheimer disease"
    assert normalize_condition_text("  Alzheimer-Disease  ") == "alzheimer disease"


def test_conditions_full_match_accepts_equivalent_ad_terms():
    profile = DiseaseResolver().resolve("Alzheimer disease")

    assert conditions_full_match(["Alzheimer's Disease"], profile)
    assert conditions_full_match(["Alzheimer Disease"], profile)
    assert conditions_full_match(["ALZHEIMERS DISEASE"], profile)


def test_conditions_full_match_rejects_non_target_and_broad_terms():
    profile = DiseaseResolver().resolve("Alzheimer disease")

    assert not conditions_full_match(["Parkinson Disease"], profile)
    assert not conditions_full_match(["Cognitive Impairment"], profile)
    assert not conditions_full_match(["Mild Cognitive Impairment"], profile)
    assert not conditions_full_match(["Caregiver Education"], profile)


def test_condition_variants_for_non_ad_disease_are_stable():
    assert condition_variants("Parkinson Disease") == ["Parkinson Disease"]
    assert build_expert_full_match_url("Parkinson Disease").endswith(
        "AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BParkinson%20Disease%5D%5D&viewType=Card&sort=StudyFirstPostDate"
    )
