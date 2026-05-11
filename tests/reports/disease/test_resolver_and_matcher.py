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


def test_resolver_canonicalizes_general_possessive_disease_input():
    profile = DiseaseResolver().resolve("Parkinson's disease pipeline")

    assert profile.disease_name == "Parkinson Disease"
    assert profile.canonical_condition == "Parkinson Disease"
    assert "Parkinson Disease" in profile.condition_terms
    assert "Parkinson's Disease" in profile.condition_terms
    assert profile.normalized_terms == ["parkinson disease"]
    assert "FullMatch%5BParkinson%20Disease%5D" in profile.expert_full_match_url


def test_resolver_canonicalizes_apostropheless_common_eponyms():
    assert DiseaseResolver().resolve("Parkinsons disease pipeline").disease_name == "Parkinson Disease"
    assert DiseaseResolver().resolve("Crohns disease pipeline").disease_name == "Crohn Disease"
    assert DiseaseResolver().resolve("Huntingtons disease pipeline").disease_name == "Huntington Disease"


def test_resolver_preserves_non_possessive_s_eponyms():
    assert DiseaseResolver().resolve("Graves Disease").disease_name == "Graves Disease"
    assert DiseaseResolver().resolve("Legionnaires Disease").disease_name == "Legionnaires Disease"


def test_resolver_handles_polite_generate_report_prompt():
    profile = DiseaseResolver().resolve("Please generate a report for Parkinson disease")

    assert profile.disease_name == "Parkinson Disease"
    assert profile.canonical_condition == "Parkinson Disease"
    assert profile.condition_terms == ["Parkinson Disease"]


def test_resolver_handles_common_request_prompts():
    expected = "Parkinson Disease"

    assert DiseaseResolver().resolve("Can you generate a report for Parkinson disease").disease_name == expected
    assert DiseaseResolver().resolve("Can you please generate a report for Parkinson disease").disease_name == expected
    assert DiseaseResolver().resolve("I need a report on Parkinson disease").disease_name == expected
    assert DiseaseResolver().resolve("Generate a Parkinson disease report").disease_name == expected


def test_resolver_extracts_patient_context_condition_from_safety_prompt():
    profile = DiseaseResolver().resolve("Assess nivolumab hepatotoxicity in melanoma patients")

    assert profile.disease_name == "Melanoma"
    assert profile.condition_terms == ["Melanoma"]


def test_resolver_extracts_patient_context_condition_from_mechanism_prompt():
    profile = DiseaseResolver().resolve("Evaluate CRISPR gene-editing trials in sickle cell disease patients")

    assert profile.disease_name == "Sickle Cell Disease"
    assert profile.condition_terms == ["Sickle Cell Disease"]


def test_resolver_preserves_slash_containing_disease_name():
    profile = DiseaseResolver().resolve("HIV/AIDS report")

    assert profile.disease_name == "HIV/AIDS"
    assert profile.disease_name != "HIV"


def test_resolver_preserves_connector_words_inside_condition_names():
    assert DiseaseResolver().resolve("Cancer with unknown primary report").disease_name == "Cancer with Unknown Primary"
    assert (
        DiseaseResolver().resolve("Bleeding from esophageal varices report").disease_name
        == "Bleeding from Esophageal Varices"
    )


def test_normalize_condition_text_collapses_possessive_and_punctuation():
    assert normalize_condition_text("Alzheimer's Disease") == "alzheimer disease"
    assert normalize_condition_text("Alzheimers disease") == "alzheimer disease"
    assert normalize_condition_text("  Alzheimer-Disease  ") == "alzheimer disease"


def test_conditions_full_match_accepts_equivalent_ad_terms():
    profile = DiseaseResolver().resolve("Alzheimer disease")

    assert conditions_full_match(["Alzheimer's Disease"], profile)
    assert conditions_full_match(["Alzheimer Disease"], profile)
    assert conditions_full_match(["ALZHEIMERS DISEASE"], profile)


def test_conditions_full_match_accepts_general_possessive_disease_terms():
    parkinson_profile = DiseaseResolver().resolve("Parkinson disease")
    crohn_profile = DiseaseResolver().resolve("Crohn disease")

    assert conditions_full_match(["Parkinson's Disease"], parkinson_profile)
    assert conditions_full_match(["Parkinsons Disease"], parkinson_profile)
    assert conditions_full_match(["Crohn's Disease"], crohn_profile)
    assert conditions_full_match(["Crohns Disease"], crohn_profile)
    assert conditions_full_match(["Huntingtons Disease"], DiseaseResolver().resolve("Huntington disease"))


def test_conditions_full_match_preserves_non_possessive_s_eponyms():
    assert not conditions_full_match(["Grave Disease"], DiseaseResolver().resolve("Graves Disease"))
    assert not conditions_full_match(["Legionnaire Disease"], DiseaseResolver().resolve("Legionnaires Disease"))


def test_conditions_full_match_rejects_non_target_and_broad_terms():
    profile = DiseaseResolver().resolve("Alzheimer disease")

    assert not conditions_full_match(["Parkinson Disease"], profile)
    assert not conditions_full_match(["Cognitive Impairment"], profile)
    assert not conditions_full_match(["Mild Cognitive Impairment"], profile)
    assert not conditions_full_match(["Caregiver Education"], profile)


def test_conditions_full_match_accepts_broad_terms_when_targeted():
    for disease_name in ["Dementia", "Mild Cognitive Impairment", "Cognitive Impairment"]:
        profile = DiseaseResolver().resolve(disease_name)

        assert conditions_full_match([disease_name], profile)


def test_condition_variants_for_non_ad_disease_are_stable():
    assert condition_variants("Parkinson Disease") == ["Parkinson Disease"]
    assert build_expert_full_match_url("Parkinson Disease").endswith(
        "AREA%5BCondition%5DCOVERAGE%5BFullMatch%5BParkinson%20Disease%5D%5D&viewType=Card&sort=StudyFirstPostDate"
    )


def test_expert_full_match_url_encodes_slashes():
    assert "HIV%2FAIDS" in build_expert_full_match_url("HIV/AIDS")
