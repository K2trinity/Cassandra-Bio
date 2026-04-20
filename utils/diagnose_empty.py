"""Detailed diagnostic for PDFs with empty captions."""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.tools.pdf_processor import extract_images_as_base64


def diagnose_empty_captions(pdf_path: str) -> int:
    """Extract images and report records without caption metadata."""

    results = extract_images_as_base64(pdf_path)
    
    pdf_name = Path(pdf_path).name
    print(f"Analyzing: {pdf_name}")
    print(f"Total images extracted: {len(results)}")
    print("="*80)

    missing_caption = [r for r in results if not r.get("caption")]
    print(f"\n⚠️ Records without caption metadata: {len(missing_caption)}")
    for idx, rec in enumerate(missing_caption, 1):
        page = rec.get("page")
        image_b64 = rec.get("image_base64", "")
        print(f"  - image_{idx}: page={page}, base64_len={len(image_b64)}")

    if not missing_caption:
        print("\n✅ All extracted records contain captions")

    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="PDF path")
    args = parser.parse_args()
    
    sys.exit(diagnose_empty_captions(args.pdf))
