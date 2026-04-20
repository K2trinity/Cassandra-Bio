"""PDF download side-effect adapter."""

from typing import List

from .._logging import logger

from src.tools.pdf_downloader import download_pdf_from_url

from ..schemas import DataCandidate


class PdfDownloader:
    """Download PDFs and write local file paths back into harvested records."""

    def download_for_candidates(self, data_candidates: List[DataCandidate], output_dir: str) -> int:
        downloaded_count = 0

        for candidate in data_candidates:
            metadata = candidate.metadata if isinstance(candidate.metadata, dict) else {}
            pdf_url = metadata.get("pdf_url")

            if not pdf_url or pdf_url == "N/A":
                pmid = metadata.get("pmid")
                pmcid = metadata.get("pmcid")
                title = (candidate.title or "Unknown")[:60]
                if pmid and not pmcid:
                    logger.info(f"Skipping PMID {pmid} - no PMC version (not open access)")
                    logger.debug(f"Title: {title}...")
                elif pmcid:
                    logger.warning(f"PMCID {pmcid} found but no PDF URL generated")
                    logger.debug(f"Title: {title}...")
                else:
                    logger.debug(f"Skipping non-PubMed source: {title}...")
                candidate.local_path = None
                continue

            try:
                local_path = download_pdf_from_url(url=pdf_url, output_dir=output_dir)
                if local_path:
                    candidate.local_path = local_path
                    downloaded_count += 1
                    logger.debug(f"Downloaded: {pdf_url} -> {local_path}")
                else:
                    candidate.local_path = None
                    logger.debug(f"Download failed: {pdf_url}")
            except Exception as exc:
                logger.warning(f"PDF download error for {pdf_url}: {exc}")
                candidate.local_path = None

        return downloaded_count
