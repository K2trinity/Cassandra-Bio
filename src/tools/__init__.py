"""
Cassandra Shared Tools Module

This module provides reusable biomedical data acquisition tools
used across multiple engines (Harvest and Report).

🔥 NEW: Multi-source data surrogates strategy for comprehensive coverage
"""

from importlib import import_module
from typing import Any, Dict, Tuple


_EXPORTS: Dict[str, Tuple[str, str]] = {
    # PubMed tools
    "search_pubmed": ("src.tools.pubmed_client", "search_pubmed"),
    "fetch_details": ("src.tools.pubmed_client", "fetch_details"),
    # ClinicalTrials tools
    "search_trials": ("src.tools.clinical_trials_client", "search_trials"),
    "search_failed_trials": ("src.tools.clinical_trials_client", "search_failed_trials"),
    "search_trials_by_sponsor": ("src.tools.clinical_trials_client", "search_trials_by_sponsor"),
    "fetch_trial_results": ("src.tools.clinical_trials_client", "fetch_trial_results"),
    "extract_adverse_events_summary": ("src.tools.clinical_trials_client", "extract_adverse_events_summary"),
    # EuroPMC tools
    "EuroPMCClient": ("src.tools.europmc_client", "EuroPMCClient"),
    "search_europmc": ("src.tools.europmc_client", "search_europmc"),
    # NCBI / openFDA / unified harvester
    "NCBIEutilsClient": ("src.tools.ncbi_eutils_client", "NCBIEutilsClient"),
    "OpenFDAClient": ("src.tools.openfda_client", "OpenFDAClient"),
    "MultiSourceHarvester": ("src.tools.multi_source_harvester", "MultiSourceHarvester"),
    "collect_multi_source_data": ("src.tools.multi_source_harvester", "collect_multi_source_data"),
    # Biomedical normalization helpers
    "normalize_drug_class": ("src.tools.biomedical_normalization", "normalize_drug_class"),
    "normalize_target_term": ("src.tools.biomedical_normalization", "normalize_target_term"),
    "extract_normalized_targets": ("src.tools.biomedical_normalization", "extract_normalized_targets"),
    # Source whitelist & mapping helpers
    "CLINICALTRIALS_STUDY_FIELD_WHITELIST": ("src.engines.harvest.core.field_mappings", "CLINICALTRIALS_STUDY_FIELD_WHITELIST"),
    "NCBI_DB_SUMMARY_WHITELIST": ("src.engines.harvest.core.field_mappings", "NCBI_DB_SUMMARY_WHITELIST"),
    "PUBMED_ARTICLE_WHITELIST": ("src.engines.harvest.core.field_mappings", "PUBMED_ARTICLE_WHITELIST"),
    "OPENFDA_ENDPOINT_FIELD_WHITELIST": ("src.engines.harvest.core.field_mappings", "OPENFDA_ENDPOINT_FIELD_WHITELIST"),
    "SOURCE_FIELD_MAPPING_TABLE": ("src.engines.harvest.core.field_mappings", "SOURCE_FIELD_MAPPING_TABLE"),
    "project_source_payloads_for_frontend": ("src.engines.harvest.core.field_mappings", "project_source_payloads_for_frontend"),
    "get_mapping_table": ("src.engines.harvest.core.field_mappings", "get_mapping_table"),
    # PDF processing tools
    "extract_images_from_pdf": ("src.tools.pdf_processor", "extract_images_from_pdf"),
    "extract_text_from_pdf": ("src.tools.pdf_processor", "extract_text_from_pdf"),
    "extract_images_as_base64": ("src.tools.pdf_processor", "extract_images_as_base64"),
    "get_pdf_info": ("src.tools.pdf_processor", "get_pdf_info"),
    # PDF download tools (with preprint fallback)
    "download_pdf_from_url": ("src.tools.pdf_downloader", "download_pdf_from_url"),
    "download_pdf_with_fallback": ("src.tools.pdf_downloader", "download_pdf_with_fallback"),
    # Preprint tools
    "search_preprints": ("src.tools.preprint_client", "search_preprints"),
    "find_preprint_by_doi": ("src.tools.preprint_client", "find_preprint_by_doi"),
    "find_preprint_by_title": ("src.tools.preprint_client", "find_preprint_by_title"),
    # Supplementary materials tools
    "find_supplementary_materials": ("src.tools.supplementary_scraper", "find_supplementary_materials"),
    "download_supplementary_file": ("src.tools.supplementary_scraper", "download_supplementary_file"),
    # PubPeer fraud detection tools
    "search_pubpeer_by_doi": ("src.tools.pubpeer_client", "search_pubpeer_by_doi"),
    "search_pubpeer_by_title": ("src.tools.pubpeer_client", "search_pubpeer_by_title"),
    "extract_flagged_images": ("src.tools.pubpeer_client", "extract_flagged_images"),
}

__all__ = [
    # PubMed tools
    'search_pubmed',
    'fetch_details',
    # ClinicalTrials tools
    'search_trials',
    'search_failed_trials',
    'search_trials_by_sponsor',
    'fetch_trial_results',
    'extract_adverse_events_summary',
    # EuroPMC tools
    'EuroPMCClient',
    'search_europmc',
    # NCBI / openFDA / unified harvester
    'NCBIEutilsClient',
    'OpenFDAClient',
    'MultiSourceHarvester',
    'collect_multi_source_data',
    # Biomedical normalization helpers
    'normalize_drug_class',
    'normalize_target_term',
    'extract_normalized_targets',
    # Source whitelist & mapping helpers
    'CLINICALTRIALS_STUDY_FIELD_WHITELIST',
    'NCBI_DB_SUMMARY_WHITELIST',
    'PUBMED_ARTICLE_WHITELIST',
    'OPENFDA_ENDPOINT_FIELD_WHITELIST',
    'SOURCE_FIELD_MAPPING_TABLE',
    'project_source_payloads_for_frontend',
    'get_mapping_table',
    # PDF processing tools
    'extract_images_from_pdf',
    'extract_text_from_pdf',
    'extract_images_as_base64',
    'get_pdf_info',
    # PDF download tools (with preprint fallback)
    'download_pdf_from_url',
    'download_pdf_with_fallback',
    # Preprint tools
    'search_preprints',
    'find_preprint_by_doi',
    'find_preprint_by_title',
    # Supplementary materials tools
    'find_supplementary_materials',
    'download_supplementary_file',
    # PubPeer fraud detection tools
    'search_pubpeer_by_doi',
    'search_pubpeer_by_title',
    'extract_flagged_images',
]


def __getattr__(name: str) -> Any:
    """Lazy-load tool symbols so optional dependencies don't fail package import."""
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'src.tools' has no attribute '{name}'")

    module_name, attr_name = target
    module = import_module(module_name)
    return getattr(module, attr_name)


def __dir__():
    return sorted(set(globals().keys()) | set(__all__))

