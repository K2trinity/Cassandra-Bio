"""
PDF Processor - Cassandra Scientific Document Analyzer

This module provides tools to extract text from PDF documents,
specifically optimized for scientific papers and clinical trial reports.

Key Functions:
- extract_text_from_pdf: Extract full text for evidence mining

Requires: PyMuPDF (fitz) - install via: pip install pymupdf
"""

import os
import logging
from pathlib import Path
from typing import Dict, Optional

try:
    from loguru import logger
except Exception:  # pragma: no cover - optional dependency fallback
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)

try:
    import fitz  # PyMuPDF
except ImportError:
    logger.error("PyMuPDF not installed. Run: pip install pymupdf")
    raise


def extract_text_from_pdf(
    pdf_path: str,
    include_metadata: bool = False
) -> str:
    """
    Extract full text content from a PDF file.
    
    Useful for evidence mining and supplementary material analysis.
    
    Args:
        pdf_path: Path to the PDF file
        include_metadata: If True, prepend document metadata (title, author, etc.)
    
    Returns:
        Extracted text as a single string (pages separated by double newlines)
    
    Example:
        >>> text = extract_text_from_pdf("clinical_trial_report.pdf")
        >>> if "adverse event" in text.lower():
        ...     print("Document mentions adverse events")
    
    Raises:
        FileNotFoundError: If PDF file doesn't exist
        Exception: If PDF cannot be opened or processed
    """
    # Validate input file
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    logger.info(f"Extracting text from: {pdf_path}")
    
    try:
        # Open PDF
        pdf_document = fitz.open(pdf_path)
        total_pages = len(pdf_document)
        
        # 🔍 DIAGNOSTIC: Check if PDF is encrypted
        if pdf_document.is_encrypted:
            logger.error(f"🔒 PDF is encrypted and requires password: {pdf_path}")
            pdf_document.close()
            raise ValueError("ENCRYPTED_PDF: This PDF is password-protected and cannot be processed.")
        
        # Extract metadata if requested
        text_parts = []
        if include_metadata:
            metadata = pdf_document.metadata
            if metadata:
                text_parts.append("=== DOCUMENT METADATA ===")
                for key, value in metadata.items():
                    if value:
                        text_parts.append(f"{key}: {value}")
                text_parts.append("\n=== DOCUMENT CONTENT ===\n")
        
        # Extract text from each page
        logger.info(f"Extracting text from {total_pages} pages...")
        
        # 🔍 DIAGNOSTIC: Track pages with/without text
        pages_with_text = 0
        pages_without_text = 0
        total_chars_extracted = 0
        
        for page_num in range(total_pages):
            page = pdf_document[page_num]
            page_text = page.get_text()
            
            if page_text.strip():
                pages_with_text += 1
                total_chars_extracted += len(page_text)
                text_parts.append(f"--- Page {page_num + 1} ---")
                text_parts.append(page_text)
                text_parts.append("")  # Empty line between pages
            else:
                pages_without_text += 1
                logger.debug(f"⚠️ Page {page_num + 1} has no extractable text (possible scanned image)")
        
        pdf_document.close()
        
        # 🔍 DIAGNOSTIC: Report extraction statistics
        logger.info(f"📊 Extraction Stats:")
        logger.info(f"   - Pages with text: {pages_with_text}/{total_pages}")
        logger.info(f"   - Pages without text: {pages_without_text}/{total_pages}")
        logger.info(f"   - Total characters: {total_chars_extracted}")
        
        # 🚨 CRITICAL CHECK: Detect scanned PDFs
        if pages_without_text == total_pages:
            logger.error(f"❌ SCANNED PDF DETECTED: All {total_pages} pages have no extractable text")
            logger.error(f"💡 This PDF likely contains only scanned images (requires OCR processing)")
            raise ValueError(f"SCANNED_PDF: All pages are images. Extracted 0 characters from {total_pages} pages.")
        elif pages_without_text > 0:
            logger.warning(f"⚠️ PARTIAL SCANNED PDF: {pages_without_text}/{total_pages} pages are image-only")
        
        # Combine all text
        full_text = "\n".join(text_parts)
        
        word_count = len(full_text.split())
        char_count = len(full_text)
        
        logger.success(
            f"✅ Extracted {char_count} characters ({word_count} words) "
            f"from {total_pages} pages"
        )
        
        return full_text
        
    except ValueError as e:
        # Re-raise ValueError with specific error codes (ENCRYPTED_PDF, SCANNED_PDF)
        raise
    except fitz.FileDataError as e:
        logger.error(f"❌ PDF CORRUPTED: File appears to be damaged or invalid format")
        logger.error(f"   Error details: {e}")
        raise ValueError(f"CORRUPTED_PDF: {e}")
    except Exception as e:
        logger.error(f"❌ UNKNOWN PDF ERROR: {type(e).__name__}: {e}")
        raise


def get_pdf_info(pdf_path: str) -> Dict[str, any]:
    """
    Get metadata and statistics about a PDF file.
    
    Args:
        pdf_path: Path to the PDF file
    
    Returns:
        Dictionary containing:
        - page_count: Number of pages
        - metadata: Document metadata (title, author, subject, etc.)
        - file_size_mb: File size in megabytes
        - has_images: Whether the PDF contains images
    
    Example:
        >>> info = get_pdf_info("paper.pdf")
        >>> print(f"Pages: {info['page_count']}, Author: {info['metadata'].get('author')}")
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    try:
        pdf_document = fitz.open(pdf_path)
        
        # Count images
        has_images = False
        for page_num in range(len(pdf_document)):
            if pdf_document[page_num].get_images():
                has_images = True
                break
        
        info = {
            "page_count": len(pdf_document),
            "metadata": pdf_document.metadata or {},
            "file_size_mb": round(os.path.getsize(pdf_path) / (1024 * 1024), 2),
            "has_images": has_images,
        }
        
        pdf_document.close()
        return info
        
    except Exception as e:
        logger.error(f"Failed to get PDF info: {e}")
        raise


# ========== Example Usage ==========
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python pdf_processor.py <path_to_pdf>")
        sys.exit(1)
    
    pdf_file = sys.argv[1]
    
    # Example 1: Get PDF info
    print("\n=== PDF Information ===")
    info = get_pdf_info(pdf_file)
    print(f"Pages: {info['page_count']}")
    print(f"File size: {info['file_size_mb']} MB")
    print(f"Has images: {info['has_images']}")
    print(f"Title: {info['metadata'].get('title', 'N/A')}")
    print(f"Author: {info['metadata'].get('author', 'N/A')}")
    
    # Example 2: Extract text
    print("\n=== Extracting Text ===")
    text = extract_text_from_pdf(pdf_file)
    print(f"Extracted {len(text)} characters")
    print(f"First 500 characters:\n{text[:500]}...")
