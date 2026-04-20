"""Debug script to inspect why certain figures have empty captions.

This script extracts detailed information about empty-caption figures:
- What page they're on
- What text blocks are near them
- Why the caption extraction failed

Usage:
    python utils/debug_empty_captions.py --pdf downloads/pmc_pdfs/PMC10068911_fe3f249a.pdf
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import fitz


def debug_empty_captions(pdf_path: str) -> int:
    """Inspect the PDF and analyze why certain images have empty captions."""
    
    doc = fitz.open(pdf_path)
    pdf_name = Path(pdf_path).name
    
    print(f"Analyzing PDF: {pdf_name}")
    print(f"Total pages: {len(doc)}")
    print("="*80)
    
    # Pages with empty captions (from test output)
    empty_caption_pages = {
        2: "figure_002_001_01",
        20: "figure_020_001_01",
        21: "figure_021_001_01",
        22: "figure_022_001_01",
        23: "figure_023_001_01",
    }
    
    for page_num, figure_id in empty_caption_pages.items():
        print(f"\n{'='*80}")
        print(f"PAGE {page_num}: {figure_id}")
        print("="*80)
        
        if page_num > len(doc):
            print(f"  [SKIP] Page {page_num} does not exist in PDF")
            continue
        
        page = doc[page_num - 1]  # 0-indexed
        
        # Get all text blocks
        text_dict = page.get_text("dict")
        text_blocks = text_dict.get("blocks", [])
        
        # Filter to text blocks only (not images)
        text_blocks_only = [
            block for block in text_blocks
            if block.get("type") == 0  # type 0 = text
        ]
        
        # Get images
        images = [block for block in text_blocks if block.get("type") == 1]  # type 1 = image
        
        print(f"\nImages on this page: {len(images)}")
        for img_idx, img_block in enumerate(images):
            bbox = img_block.get("bbox", [])
            print(f"  Image {img_idx}: rect={bbox}")
        
        print(f"\nText blocks on this page: {len(text_blocks_only)}")
        if not text_blocks_only:
            print("  [NO TEXT BLOCKS FOUND ON THIS PAGE]")
        else:
            for block_idx, block in enumerate(text_blocks_only):
                rect = block.get("bbox", [])
                lines = block.get("lines", [])
                
                # Extract text from lines
                full_text = ""
                for line in lines:
                    line_text = ""
                    for span in line.get("spans", []):
                        line_text += span.get("text", "")
                    full_text += line_text + " "
                
                # Normalize and preview
                preview = full_text.strip().replace('\n', ' ')[:100]
                contains_figure_label = "figure" in preview.lower() or "fig " in preview.lower()
                
                print(f"\n  Block {block_idx}:")
                print(f"    Rect:        {rect}")
                print(f"    Has 'Figure' label: {contains_figure_label}")
                print(f"    Text preview: '{preview}...'")
                print(f"    Full length: {len(full_text.strip())} chars")
    
    print(f"\n{'='*80}")
    print("Analysis complete.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug empty caption extraction")
    parser.add_argument("--pdf", required=True, help="PDF path")
    args = parser.parse_args()
    
    return debug_empty_captions(args.pdf)


if __name__ == "__main__":
    sys.exit(main())
