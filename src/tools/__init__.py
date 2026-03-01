"""
Bio-Short-Seller Shared Tools Module

This module provides reusable biomedical data acquisition tools
used across multiple engines (BioHarvest, Forensic, Evidence, Report).

🔥 NEW: Multi-source data surrogates strategy for comprehensive coverage
"""

from .pubmed_client import search_pubmed, fetch_details
from .clinical_trials_client import (
    search_failed_trials, 
    search_trials_by_sponsor,
    fetch_trial_results,
    extract_adverse_events_summary
)
from .europmc_client import EuroPMCClient, search_europmc
from .pdf_processor import (
    extract_images_from_pdf,
    extract_text_from_pdf,
    extract_images_as_base64,
    get_pdf_info
)
from .pdf_downloader import download_pdf_from_url, download_pdf_with_fallback
from .preprint_client import (
    search_preprints,
    find_preprint_by_doi,
    find_preprint_by_title
)
from .supplementary_scraper import (
    find_supplementary_materials,
    download_supplementary_file
)
from .pubpeer_client import (
    search_pubpeer_by_doi,
    search_pubpeer_by_title,
    extract_flagged_images
)

__all__ = [
    # PubMed tools
    'search_pubmed',
    'fetch_details',
    # ClinicalTrials tools
    'search_failed_trials',
    'search_trials_by_sponsor',
    'fetch_trial_results',
    'extract_adverse_events_summary',
    # EuroPMC tools
    'EuroPMCClient',
    'search_europmc',
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

