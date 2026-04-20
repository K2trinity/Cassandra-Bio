"""BioHarvest facade agent: single external orchestration interface."""

from typing import Any, Dict, Optional

from ._logging import logger

from .config import HarvestConfig
from .core import aggregate_data, build_data_layers
from .io import PdfDownloader
from .llm import QueryParser
from .retrievers import (
    ClinicalTrialsRetriever,
    EuroPMCRetriever,
    MultiSourceEnricher,
    PubMedRetriever,
)
from .schemas import HarvestReport, HarvestStats, model_dump_compat


class BioHarvestAgent:
    """Facade over BioHarvest use cases and adapters."""

    def __init__(
        self,
        config: Optional[HarvestConfig] = None,
        query_parser: Optional[QueryParser] = None,
        europmc_retriever: Optional[EuroPMCRetriever] = None,
        pubmed_retriever: Optional[PubMedRetriever] = None,
        trials_retriever: Optional[ClinicalTrialsRetriever] = None,
        enricher: Optional[MultiSourceEnricher] = None,
        pdf_downloader: Optional[PdfDownloader] = None,
    ):
        self.config = config or HarvestConfig()
        self.query_parser = query_parser or QueryParser()
        self.europmc_retriever = europmc_retriever or EuroPMCRetriever()
        self.pubmed_retriever = pubmed_retriever or PubMedRetriever()
        self.trials_retriever = trials_retriever or ClinicalTrialsRetriever()
        self.enricher = enricher or MultiSourceEnricher()
        self.pdf_downloader = pdf_downloader or PdfDownloader()

        logger.info("BioHarvest facade initialized")

    def run(self, user_query: str, max_results_per_source: Optional[int] = None) -> Dict[str, Any]:
        """Run the end-to-end BioHarvest pipeline and return report payload."""
        max_results = max_results_per_source or self.config.max_results_per_source

        logger.info("=" * 60)
        logger.info(f"BioHarvest query: {user_query}")
        logger.info("=" * 60)

        try:
            logger.info("[Step A] Parsing user query")
            intent = self.query_parser.parse(user_query)

            logger.info("[Step B] Retrieving from EuropePMC/PubMed/ClinicalTrials")
            europmc_papers = self.europmc_retriever.retrieve(intent.pubmed, max_results)

            pubmed_articles = []
            if len(europmc_papers) < self.config.europmc_fallback_threshold:
                logger.info("EuropePMC returned few results, using PubMed fallback")
                pubmed_articles = self.pubmed_retriever.retrieve(intent.pubmed, max_results)

            trial_results = self.trials_retriever.retrieve(intent.clinicaltrials, max_results)
            pubmed_results = europmc_papers + pubmed_articles

            logger.info("[Step C] Collecting multi-source enrichment payloads")
            core_query = intent.core_entity or user_query
            source_payloads = self.enricher.collect(
                query=core_query,
                max_results_per_source=max_results,
            )

            logger.info("[Step D] Aggregating data")
            data_candidates = aggregate_data(pubmed_results, trial_results)

            logger.info("[Step E] Downloading PDFs")
            downloaded_count = self.pdf_downloader.download_for_candidates(
                data_candidates=data_candidates,
                output_dir=self.config.pdf_output_dir,
            )

            logger.info("[Step F] Building data layers")
            data_layers = build_data_layers(
                query=user_query,
                data_candidates=data_candidates,
                source_payloads=source_payloads,
            )

            logger.info("[Step G] Projecting frontend payload")
            frontend_payload = self.enricher.project_for_frontend(
                source_payloads=source_payloads,
                max_items=max_results,
            )

            ncbi_records = sum(
                (source_payloads.get("ncbi", {}).get(db, {}) or {}).get("count", 0)
                for db in ["pubmed", "gene", "protein", "clinvar", "gds"]
            )
            openfda_counts = source_payloads.get("openfda", {}).get("counts", {})
            openfda_records = (
                int(openfda_counts.get("label", 0) or 0)
                + int(openfda_counts.get("event", 0) or 0)
                + int(openfda_counts.get("drugsfda", 0) or 0)
            )

            report = HarvestReport(
                results=data_candidates,
                stats=HarvestStats(
                    total=len(data_candidates),
                    pubmed=len(pubmed_results),
                    trials=len(trial_results),
                    pdfs_downloaded=downloaded_count,
                    ncbi_records=ncbi_records,
                    openfda_records=openfda_records,
                ),
                data_layers=data_layers,
                source_payloads=source_payloads,
                frontend_payload=frontend_payload,
            )

            logger.success(f"Harvested {len(data_candidates)} data candidates")
            logger.info(f"PubMed articles: {len(pubmed_results)}")
            logger.info(f"Clinical trials: {len(trial_results)}")
            logger.info(f"PDFs downloaded: {downloaded_count}")

            return model_dump_compat(report, exclude_none=True)

        except Exception as exc:
            logger.error(f"BioHarvest failed: {exc}")
            raise


def create_agent() -> BioHarvestAgent:
    """Factory function preserving existing call pattern."""
    return BioHarvestAgent()


HarvestAgent = BioHarvestAgent
