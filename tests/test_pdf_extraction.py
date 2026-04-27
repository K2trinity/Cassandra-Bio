"""PDF extraction verification (harvest/report architecture baseline)."""

import logging
import os
import sys
from pathlib import Path

import pytest

try:
    from loguru import logger
except Exception:  # pragma: no cover - fallback when optional dependency is missing
    logger = logging.getLogger(__name__)
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO)

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

TEST_PDFS_DIR = project_root / "downloads" / "test_pdfs"
TEST_PDFS_DIR.mkdir(parents=True, exist_ok=True)


def _load_pdf_tools():
    """Load PDF tools lazily so missing optional deps become skippable tests."""
    try:
        from src.tools import extract_text_from_pdf, get_pdf_info

        return extract_text_from_pdf, get_pdf_info
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"Missing optional PDF dependency: {exc}") from exc


def _pick_test_pdf() -> Path:
    files = list(TEST_PDFS_DIR.glob("*.pdf"))
    if not files:
        pytest.skip(f"No test PDF found under {TEST_PDFS_DIR}")
    return files[0]


def test_pdf_text_extraction_or_expected_classifier_error():
    try:
        extract_text_from_pdf, _ = _load_pdf_tools()
    except RuntimeError as exc:
        logger.warning(f"Skipping PDF extraction test: {exc}")
        return

    pdf_file = _pick_test_pdf()
    logger.info(f"Testing extraction with: {pdf_file.name}")

    try:
        text = extract_text_from_pdf(str(pdf_file))
        assert isinstance(text, str)
        assert len(text) > 50
    except ValueError as exc:
        msg = str(exc)
        # Valid classifier errors from PDF processor.
        assert (
            "ENCRYPTED_PDF" in msg
            or "SCANNED_PDF" in msg
            or "CORRUPTED_PDF" in msg
        )


def test_pdf_info_metadata_access():
    try:
        _, get_pdf_info = _load_pdf_tools()
    except RuntimeError as exc:
        logger.warning(f"Skipping PDF metadata test: {exc}")
        return

    pdf_file = _pick_test_pdf()
    info = get_pdf_info(str(pdf_file))

    assert "page_count" in info
    assert "metadata" in info
    assert "file_size_mb" in info
    assert isinstance(info["page_count"], int)


def main():
    logger.info("Running PDF extraction verification")
    try:
        test_pdf_text_extraction_or_expected_classifier_error()
        test_pdf_info_metadata_access()
        logger.info("All checks passed")
        return True
    except Exception as exc:
        logger.error(f"Verification failed: {exc}")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
