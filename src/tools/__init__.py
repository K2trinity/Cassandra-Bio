"""
Bio-Short-Seller Shared Tools Module

This module provides reusable biomedical data acquisition tools
used across multiple engines (BioHarvest, Forensic, Evidence, Report).
"""

from .pubmed_client import search_pubmed, fetch_details
from .clinical_trials_client import search_failed_trials, search_trials_by_sponsor
from .europmc_client import EuroPMCClient, search_europmc
from .pdf_processor import (
    extract_images_from_pdf,
    extract_text_from_pdf,
    extract_images_as_base64,
    get_pdf_info
)

__all__ = [
    # PubMed tools
    'search_pubmed',
    'fetch_details',
    # ClinicalTrials tools
    'search_failed_trials',
    'search_trials_by_sponsor',
    # EuroPMC tools
    'EuroPMCClient',
    'search_europmc',
    # PDF processing tools
    'extract_images_from_pdf',
    'extract_text_from_pdf',
    'extract_images_as_base64',
    'get_pdf_info',
]
