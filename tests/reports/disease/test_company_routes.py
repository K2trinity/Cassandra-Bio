from src.reports.disease import company_routes


def test_normalize_analysis_target_type_accepts_supported_modes():
    assert hasattr(company_routes, "VALID_ANALYSIS_TARGET_TYPES")
    assert hasattr(company_routes, "normalize_analysis_target_type")
    assert company_routes.VALID_ANALYSIS_TARGET_TYPES == {"auto", "disease", "company"}
    assert company_routes.normalize_analysis_target_type(None) == "auto"
    assert company_routes.normalize_analysis_target_type("") == "auto"
    assert company_routes.normalize_analysis_target_type(" Company ") == "company"
    assert company_routes.normalize_analysis_target_type("DISEASE") == "disease"


def test_normalize_analysis_target_type_rejects_unknown_mode():
    try:
        company_routes.normalize_analysis_target_type("sponsor")
    except ValueError as exc:
        assert "analysis_target_type" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_explicit_company_mode_wins_over_disease_cues():
    assert hasattr(company_routes, "resolve_analysis_target")
    profile = company_routes.resolve_analysis_target(
        "conduct a comprehensive survey on Alzheimer disease",
        requested_target_type="company",
    )

    assert profile.target_type == "company"
    assert profile.company_name == "Alzheimer disease"
    assert profile.target_name == "Alzheimer disease"
    assert profile.condition_terms == []
    assert profile.normalized_terms == []
    assert "query.spons=Alzheimer%20disease" in profile.expert_topic_url
    assert "query.spons=Alzheimer%20disease" in profile.expert_full_match_url


def test_explicit_disease_mode_wins_over_company_wording():
    profile = company_routes.resolve_analysis_target(
        "company pipeline for Eli Lilly and Company",
        requested_target_type="disease",
    )

    assert profile.target_type == "disease"
    assert profile.company_name is None


def test_auto_infers_company_from_named_pharma_company():
    profile = company_routes.resolve_analysis_target("conduct a comprehensive survey on Vertex Pharmaceuticals")

    assert profile.target_type == "company"
    assert profile.company_name == "Vertex Pharmaceuticals"
    assert profile.target_name == "Vertex Pharmaceuticals"


def test_explicit_company_mode_strips_analyze_pipeline_wording():
    profile = company_routes.resolve_analysis_target(
        "Analyze Vertex Pharmaceuticals clinical pipeline",
        requested_target_type="company",
    )

    assert profile.target_type == "company"
    assert profile.company_name == "Vertex Pharmaceuticals"
    assert profile.target_name == "Vertex Pharmaceuticals"


def test_auto_infers_company_from_pipeline_wording_and_suffix():
    profile = company_routes.resolve_analysis_target("company pipeline for Eli Lilly and Company")

    assert profile.target_type == "company"
    assert profile.company_name == "Eli Lilly and Company"


def test_company_name_expands_and_co_suffix_for_sponsor_search():
    profile = company_routes.resolve_analysis_target(
        "conduct a comprehensive survey on Eli Lilly And Co",
        requested_target_type="company",
    )

    assert profile.target_type == "company"
    assert profile.company_name == "Eli Lilly and Company"
    assert "query.spons=Eli%20Lilly%20and%20Company" in profile.expert_topic_url


def test_auto_stays_disease_for_disease_prompt():
    profile = company_routes.resolve_analysis_target("conduct a comprehensive survey on Alzheimer disease")

    assert profile.target_type == "disease"
    assert profile.disease_name == "Alzheimer Disease"


def test_disease_cues_override_company_suffix_like_text_in_auto_mode():
    profile = company_routes.resolve_analysis_target("conduct a comprehensive survey on Acme Company disease")

    assert profile.target_type == "disease"
    assert profile.disease_name == "Acme Company Disease"
