"""
PDF Processor - Bio-Short-Seller Scientific Document Analyzer

This module provides tools to extract images and text from PDF documents,
specifically optimized for scientific papers and clinical trial reports.

Key Functions:
- extract_images_from_pdf: Extract figures/charts from PDFs for forensic analysis
- extract_text_from_pdf: Extract full text for evidence mining

Requires: PyMuPDF (fitz) - install via: pip install pymupdf
"""

import os
import tempfile
from pathlib import Path
from typing import List, Dict, Optional
from loguru import logger

try:
    import fitz  # PyMuPDF
except ImportError:
    logger.error("PyMuPDF not installed. Run: pip install pymupdf")
    raise


# ========== Configuration ==========
# Minimum image dimensions to filter out logos, icons, and small graphics
MIN_IMAGE_WIDTH = 200  # pixels
MIN_IMAGE_HEIGHT = 200  # pixels

# Image quality settings
IMAGE_DPI = 300  # DPI for image extraction
IMAGE_FORMAT = "png"  # Format for saved images


def extract_images_from_pdf(
    pdf_path: str,
    output_dir: Optional[str] = None,
    min_width: int = MIN_IMAGE_WIDTH,
    min_height: int = MIN_IMAGE_HEIGHT,
    dpi: int = IMAGE_DPI
) -> List[str]:
    """
    Extract images from a PDF file and save them to disk.
    
    This function is optimized for extracting scientific figures, charts, and diagrams
    from biomedical papers. It filters out small logos, icons, and page decorations.
    
    Args:
        pdf_path: Path to the PDF file
        output_dir: Directory to save extracted images (default: temporary directory)
        min_width: Minimum image width in pixels to keep (default: 200)
        min_height: Minimum image height in pixels to keep (default: 200)
        dpi: DPI resolution for image extraction (default: 300)
    
    Returns:
        List of file paths to extracted images
    
    Example:
        >>> image_paths = extract_images_from_pdf("research_paper.pdf")
        >>> print(f"Extracted {len(image_paths)} figures")
        >>> for img_path in image_paths:
        ...     print(f"Figure: {img_path}")
    
    Raises:
        FileNotFoundError: If PDF file doesn't exist
        Exception: If PDF cannot be opened or processed
    """
    # Validate input file
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    # Create output directory
    if output_dir is None:
        output_dir = tempfile.mkdtemp(prefix="bio_short_seller_imgs_")
    else:
        os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"Extracting images from: {pdf_path}")
    logger.info(f"Output directory: {output_dir}")
    
    extracted_images = []
    
    try:
        # Open PDF
        pdf_document = fitz.open(pdf_path)
        total_pages = len(pdf_document)
        logger.info(f"PDF has {total_pages} pages")
        
        image_counter = 0
        
        # Iterate through pages
        for page_num in range(total_pages):
            page = pdf_document[page_num]
            
            # Get list of images on this page
            image_list = page.get_images(full=True)
            
            if image_list:
                logger.info(f"Page {page_num + 1}: Found {len(image_list)} images")
            
            # Extract each image
            for img_index, img_info in enumerate(image_list):
                try:
                    # Get image reference
                    xref = img_info[0]
                    
                    # Extract image data
                    base_image = pdf_document.extract_image(xref)
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                    
                    # Get image dimensions
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    
                    # Filter by size (skip small logos/icons)
                    if width < min_width or height < min_height:
                        logger.debug(
                            f"Skipping small image on page {page_num + 1}: "
                            f"{width}x{height}px"
                        )
                        continue
                    
                    # Generate filename
                    image_counter += 1
                    filename = f"figure_{image_counter:03d}_p{page_num + 1}.{image_ext}"
                    image_path = os.path.join(output_dir, filename)
                    
                    # Save image
                    with open(image_path, "wb") as img_file:
                        img_file.write(image_bytes)
                    
                    extracted_images.append(image_path)
                    logger.success(
                        f"Extracted: {filename} ({width}x{height}px) "
                        f"from page {page_num + 1}"
                    )
                    
                except Exception as e:
                    logger.warning(
                        f"Failed to extract image {img_index} from page {page_num + 1}: {e}"
                    )
                    continue
        
        pdf_document.close()
        
        logger.success(
            f"Extraction complete: {len(extracted_images)} images saved to {output_dir}"
        )
        return extracted_images
        
    except Exception as e:
        logger.error(f"Failed to process PDF: {e}")
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


def extract_images_as_base64(
    pdf_path: str,
    min_width: int = MIN_IMAGE_WIDTH,
    min_height: int = MIN_IMAGE_HEIGHT
) -> List[Dict[str, str]]:
    """
    Extract images from PDF and return them as base64-encoded strings.
    
    Useful for direct API transmission without saving to disk.
    
    Args:
        pdf_path: Path to the PDF file
        min_width: Minimum image width to keep
        min_height: Minimum image height to keep
    
    Returns:
        List of dictionaries with keys:
        - 'image_base64': Base64-encoded image data
        - 'format': Image format (png, jpeg, etc.)
        - 'page_num': Page number where image was found
        - 'dimensions': (width, height) tuple
    """
    import base64
    
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF file not found: {pdf_path}")
    
    logger.info(f"Extracting images as base64 from: {pdf_path}")
    
    images_data = []
    
    try:
        pdf_document = fitz.open(pdf_path)
        
        for page_num in range(len(pdf_document)):
            page = pdf_document[page_num]
            image_list = page.get_images(full=True)
            
            for img_info in image_list:
                try:
                    xref = img_info[0]
                    base_image = pdf_document.extract_image(xref)
                    
                    width = base_image.get("width", 0)
                    height = base_image.get("height", 0)
                    
                    # Filter by size
                    if width < min_width or height < min_height:
                        continue
                    
                    image_bytes = base_image["image"]
                    image_ext = base_image["ext"]
                    
                    # Convert to base64
                    image_base64 = base64.b64encode(image_bytes).decode('utf-8')
                    
                    images_data.append({
                        'image_base64': image_base64,
                        'format': image_ext,
                        'page_num': page_num + 1,
                        'dimensions': (width, height)
                    })
                    
                except Exception as e:
                    logger.warning(f"Failed to encode image: {e}")
                    continue
        
        pdf_document.close()
        logger.success(f"Extracted {len(images_data)} images as base64")
        return images_data
        
    except Exception as e:
        logger.error(f"Failed to extract images as base64: {e}")
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
    
    # Example 2: Extract images
    print("\n=== Extracting Images ===")
    images = extract_images_from_pdf(pdf_file)
    print(f"\nExtracted {len(images)} images:")
    for img_path in images:
        print(f"  - {img_path}")
    
    # Example 3: Extract text
    print("\n=== Extracting Text ===")
    text = extract_text_from_pdf(pdf_file)
    print(f"Extracted {len(text)} characters")
    print(f"First 500 characters:\n{text[:500]}...")
