"""
BioHarvest Agent - Multi-source Biomedical Data Harvester

This agent collects objective biomedical data from multiple official/public
sources and normalizes them into a stable payload for downstream reporting.

Sources in this pipeline:
- ClinicalTrials.gov API v2
- NCBI E-utilities
- Europe PMC
- PubMed
- openFDA
"""

import json
from typing import Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

from src.llms import create_bioharvest_client
from src.tools import (
    search_pubmed,
    fetch_details,
    search_trials,
    EuroPMCClient,
    collect_multi_source_data,
    project_source_payloads_for_frontend,
    normalize_drug_class,
    extract_normalized_targets,
)
from src.tools.pdf_downloader import download_pdf_from_url
from loguru import logger
from src.utils.stream_validator import StreamValidator


class BioHarvestAgent:
    """
    Biomedical Evidence Harvester Agent
    
    Transforms high-level queries into standardized, source-grounded evidence
    without subjective risk conclusions.
    """
    
    def __init__(self):
        """Initialize BioHarvest Agent with Gemini LLM and biomedical search tools."""
        
        # Initialize LLM client (Gemini Pro for query generation)
        self.llm = create_bioharvest_client()
        
        # Initialize EuroPMC client (PRIMARY source for PDFs)
        self.europmc = EuroPMCClient()
        
        logger.info("BioHarvest Agent initialized with Gemini LLM + EuroPMC Client")
        
        # Tools are imported as functions (no initialization needed)
    
    def run(self, user_query: str, max_results_per_source: int = 20) -> Dict[str, Any]:
        """
        Execute biomedical evidence harvesting workflow.
        
        Args:
            user_query: High-level biomedical query
            max_results_per_source: Maximum results to retrieve from each source
        
        Returns:
            Dictionary with structure:
            {
                'results': [
                    {
                        'title': str,        # Article/trial title
                        'source': str,       # 'PubMed' or 'ClinicalTrials.gov'
                        'snippet': str,      # Abstract excerpt or why_stopped reason
                        'link': str,         # Full URL to original source
                        'status': str,
                        'date': str,         # Publication/completion date
                        'metadata': dict
                    },
                    ...
                ],
                'stats': {
                    'total': int,
                    'pubmed': int,
                    'trials': int,
                    'pdfs_downloaded': int,
                    'ncbi_records': int,
                    'openfda_records': int
                },
                'data_layers': {...},
                'source_payloads': {...}
            }
        
        Workflow:
            Step A: Query parsing and source query generation
            Step B: Source execution (EuroPMC/PubMed/ClinicalTrials)
            Step C: Multi-source enrichment (NCBI/openFDA)
            Step D: Normalization to report-oriented data layers
        
        Example:
            >>> agent = BioHarvestAgent()
            >>> results = agent.run("pembrolizumab cardiotoxicity")
            >>> print(f"Found {len(results)} evidence candidates")
            >>> for r in results[:3]:
            ...     print(f"{r['source']}: {r['title']}")
        """
        logger.info(f"\n{'='*60}")
        logger.info(f"🔍 BioHarvest: {user_query}")
        logger.info(f"{'='*60}")
        
        try:
            # ===== STEP A: Intent Parsing =====
            logger.info("\n[Step A] Parsing user intent and generating search queries...")
            search_queries = self._generate_search_queries(user_query)
            
            # ===== STEP B: Execution =====
            logger.info("\n[Step B] Executing parallel database searches...")
            
            # 🔥 PRIMARY: Search EuroPMC for papers with direct PDF access
            europmc_papers = []
            for query in search_queries.get("pubmed", []):  # Use same queries
                try:
                    papers = self.europmc.search_papers(
                        query=query,
                        max_results=max_results_per_source,
                        open_access_only=True  # Only get papers with PDFs
                    )
                    europmc_papers.extend(papers)
                except Exception as e:
                    logger.warning(f"EuroPMC search failed for '{query}': {e}")
            
            # 🔄 FALLBACK: Search PubMed only if EuroPMC returns insufficient results
            pubmed_articles = []
            if len(europmc_papers) < 5:  # Fallback threshold
                logger.info("EuroPMC returned few results, searching PubMed as fallback...")
                pubmed_articles = self._execute_pubmed_searches(
                    search_queries.get("pubmed", []),
                    max_results_per_source
                )
            
            # Search ClinicalTrials.gov (all major statuses, not only failed)
            trial_results = self._execute_trials_searches(
                search_queries.get("clinicaltrials", []),
                max_results_per_source
            )
            
            # Combine results
            pubmed_results = europmc_papers + pubmed_articles
            
            # ===== STEP C: Multi-source enrichment =====
            logger.info("\n[Step C] Enriching with NCBI/openFDA/EuropePMC unified collector...")
            source_payloads = collect_multi_source_data(
                query=user_query,
                max_results_per_source=max_results_per_source,
            )

            # ===== STEP D: Aggregation =====
            logger.info("\n[Step D] Aggregating evidence candidates...")
            evidence_candidates = self._aggregate_results(pubmed_results, trial_results)
            
            # ===== STEP E: PDF Download =====
            logger.info("\n[Step E] Downloading full-text PDFs from PMC...")
            downloaded_count = self._download_pdfs(evidence_candidates)

            # ===== STEP F: Build data layers =====
            data_layers = self._build_data_layers(
                query=user_query,
                evidence_candidates=evidence_candidates,
                source_payloads=source_payloads,
            )

            # ===== STEP G: Build frontend projection from explicit source whitelists =====
            frontend_payload = project_source_payloads_for_frontend(
                source_payloads=source_payloads,
                max_items=max_results_per_source,
            )
            
            logger.info(f"\n{'='*60}")
            logger.success(f"✅ Harvested {len(evidence_candidates)} evidence candidates")
            logger.info(f"   - PubMed articles: {len(pubmed_results)}")
            logger.info(f"   - Clinical trials: {len(trial_results)}")
            logger.info(f"   - PDFs downloaded: {downloaded_count}")
            logger.info(f"{'='*60}\n")
            
            ncbi_records = sum((source_payloads.get("ncbi", {}).get(db, {}) or {}).get("count", 0)
                               for db in ["pubmed", "gene", "protein", "clinvar", "gds"])
            openfda_counts = source_payloads.get("openfda", {}).get("counts", {})
            openfda_records = (
                int(openfda_counts.get("label", 0) or 0)
                + int(openfda_counts.get("event", 0) or 0)
                + int(openfda_counts.get("drugsfda", 0) or 0)
            )

            # Return structured result matching supervisor expectations.
            # Important: risk-related fields are intentionally not transmitted.
            return {
                "results": evidence_candidates,
                "stats": {
                    "total": len(evidence_candidates),
                    "pubmed": len(pubmed_results),
                    "trials": len(trial_results),
                    "pdfs_downloaded": downloaded_count,
                    "ncbi_records": ncbi_records,
                    "openfda_records": openfda_records,
                },
                "data_layers": data_layers,
                "source_payloads": source_payloads,
                "frontend_payload": frontend_payload,
            }
            
        except Exception as e:
            logger.error(f"BioHarvest failed: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _generate_search_queries(self, user_query: str) -> Dict[str, List[str]]:
        """
        Use Gemini LLM to generate specific search queries for PubMed and ClinicalTrials.
        
        Args:
            user_query: Original user query
        
        Returns:
            Dictionary with keys 'pubmed' and 'clinicaltrials', each containing list of queries
        """
        # 🔥 FIX: Extract core keywords FIRST to preserve them
        core_keywords = user_query.split()[:3]  # First 3 words are usually key concepts
        core_terms = ' '.join([w for w in core_keywords if len(w) > 2])  # Filter short words
        
        prompt = f"""You are a biomedical research expert analyzing investigative queries for short-selling due diligence.

USER QUERY: "{user_query}"
🔥 CORE TERMS TO PRESERVE: "{core_terms}" (MUST appear in at least 2 queries!)

Generate 3 specific search queries for each database to maximize objective evidence coverage:

1. **PubMed queries**: 
   - CRITICAL: Keep queries SIMPLE and CONCISE (2-4 keywords max)
   - MANDATORY: Include the core term "{core_terms}" in at least 2 queries
   - PubMed's search algorithm works best with SHORT queries
   - Complex multi-word queries often return 0 results
   - Focus on core concepts only
   - ✅ GOOD: "CRISPR adverse events", "CRISPR toxicity", "CRISPR off-target"
   - ❌ BAD: "CRISPR off-target adverse events clinical trials toxicity genotoxicity"
    - Include trial, efficacy, biomarker, and mechanism evidence terms

2. **ClinicalTrials.gov queries**: 
   - Use drug names, company names, or therapy types
   - MUST include core term "{core_terms}"
    - Keep queries concise and entity-focused
   - Example: "pembrolizumab", "CRISPR", "CAR-T therapy"

Return your response in this EXACT JSON format:
{{
  "pubmed": ["short query 1", "short query 2", "short query 3"],
  "clinicaltrials": ["query1", "query2", "query3"]
}}

REMEMBER: 
- PubMed queries MUST be SHORT (2-4 keywords)
- Core term "{core_terms}" MUST appear in queries!

Only respond with valid JSON, no additional text."""

        try:
            response = self.llm.generate_content(prompt)
            
            # === PROTOCOL UPGRADE: Use StreamValidator Middleware ===
            # This prevents JSON parse errors and "Data not available" crashes
            queries = StreamValidator.sanitize_llm_json(response)
            
            # Validate that we got the expected structure
            if "error" in queries:
                logger.warning(f"LLM returned invalid JSON: {queries['error']}")
                raise ValueError("Invalid JSON from LLM")
            
            # Ensure required keys exist with fallbacks
            if "pubmed" not in queries:
                queries["pubmed"] = [user_query]
            if "clinicaltrials" not in queries:
                queries["clinicaltrials"] = [user_query]
            
            logger.info(f"Generated PubMed queries: {queries['pubmed']}")
            logger.info(f"Generated ClinicalTrials queries: {queries['clinicaltrials']}")
            
            return queries
            
        except Exception as e:
            logger.warning(f"LLM query generation failed: {e}, using fallback queries")
            # Fallback: simple keyword-based queries
            return {
                "pubmed": [
                    f"{user_query} clinical trial",
                    f"{user_query} mechanism biomarker",
                    f"{user_query} efficacy safety"
                ],
                "clinicaltrials": [user_query, user_query, user_query]
            }
    
    def _execute_pubmed_searches(self, queries: List[str], max_results: int) -> List[Dict]:
        """Execute PubMed searches (FALLBACK only)."""
        all_pmids = []
        for query in queries:
            try:
                pmids = search_pubmed(query, max_results=max_results)
                all_pmids.extend(pmids)
            except Exception as e:
                logger.warning(f"PubMed search failed for '{query}': {e}")
        
        # Deduplicate and fetch details
        unique_pmids = list(set(all_pmids))
        if unique_pmids:
            return fetch_details(unique_pmids)
        return []
    
    def _execute_trials_searches(self, queries: List[str], max_results: int) -> List[Dict]:
        """Execute ClinicalTrials.gov searches."""
        all_trials = []
        for query in queries:
            try:
                trials = search_trials(query, max_results=max_results, include_statuses=None)
                all_trials.extend(trials)
            except Exception as e:
                logger.warning(f"ClinicalTrials search failed for '{query}': {e}")
        return self._deduplicate_by_key(all_trials, 'nct_id')
    
    def _execute_searches(
        self, 
        search_queries: Dict[str, List[str]], 
        max_results: int
    ) -> tuple[List[Dict], List[Dict]]:
        """
        Execute searches on PubMed and ClinicalTrials.gov in parallel.
        
        Args:
            search_queries: Dictionary with 'pubmed' and 'clinicaltrials' query lists
            max_results: Max results per source
        
        Returns:
            Tuple of (pubmed_articles, failed_trials)
        """
        pubmed_articles = []
        failed_trials = []
        
        # Use ThreadPoolExecutor for parallel execution
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = []
            
            # Submit PubMed searches
            for query in search_queries.get("pubmed", []):
                future = executor.submit(self._search_pubmed_wrapper, query, max_results)
                futures.append(('pubmed', future))
            
            # Submit ClinicalTrials searches
            for query in search_queries.get("clinicaltrials", []):
                future = executor.submit(
                    search_trials,
                    query, 
                    max_results=max_results
                )
                futures.append(('clinicaltrials', future))
            
            # Collect results
            for source_type, future in futures:
                try:
                    result = future.result(timeout=60)
                    if source_type == 'pubmed':
                        pubmed_articles.extend(result)
                    else:
                        failed_trials.extend(result)
                except Exception as e:
                    logger.error(f"Search failed for {source_type}: {e}")
        
        # Deduplicate results
        pubmed_articles = self._deduplicate_by_key(pubmed_articles, 'pmid')
        failed_trials = self._deduplicate_by_key(failed_trials, 'nct_id')
        
        return pubmed_articles, failed_trials
    
    def _search_pubmed_wrapper(self, query: str, max_results: int) -> List[Dict]:
        """Wrapper to combine search_pubmed and fetch_details into one call."""
        try:
            pmids = search_pubmed(query, max_results=max_results)
            if pmids:
                articles = fetch_details(pmids)
                return articles
            return []
        except Exception as e:
            logger.error(f"PubMed search failed for '{query}': {e}")
            return []
    
    def _deduplicate_by_key(self, items: List[Dict], key: str) -> List[Dict]:
        """Remove duplicates based on a specific key."""
        seen = set()
        unique_items = []
        for item in items:
            identifier = item.get(key)
            if identifier and identifier not in seen:
                seen.add(identifier)
                unique_items.append(item)
        return unique_items
    
    def _aggregate_results(
        self, 
        pubmed_articles: List[Dict], 
        trials: List[Dict]
    ) -> List[Dict[str, str]]:
        """
        Convert raw API results into standardized evidence candidate format.
        
        Handles both EuroPMC results (with pdf_url) and PubMed fallback results.
        
        Args:
            pubmed_articles: List of article dicts from EuroPMC or fetch_details()
            trials: List of trial dicts from ClinicalTrials.gov
        
        Returns:
            Unified list of evidence candidates
        """
        evidence_candidates = []
        
        # Process articles (EuroPMC or PubMed)
        for article in pubmed_articles:
            # Check if this is EuroPMC result (has 'source' field)
            is_europmc = article.get('source') == 'EuroPMC'
            
            evidence_candidates.append({
                'title': article.get('title', 'No title'),
                'source': 'EuroPMC' if is_europmc else 'PubMed',
                'snippet': article.get('abstract', '')[:500] + '...',  # Truncate abstract
                'link': article.get('pubmed_link', ''),
                'status': 'Published',
                'date': article.get('pub_date', 'Unknown'),
                'metadata': {
                    'pmid': article.get('pmid'),
                    'pmcid': article.get('pmcid'),
                    'authors': article.get('authors'),
                    'journal': article.get('journal'),
                    'doi': article.get('doi'),
                    'pmc_link': article.get('pmc_link'),
                    'pdf_url': article.get('pdf_url')  # 🔥 Direct PDF URL from EuroPMC
                }
            })
        
        # Process clinical trials
        for trial in trials:
            nct_id = trial.get('nct_id')

            evidence_candidates.append({
                'title': trial.get('title', 'No title'),
                'source': 'ClinicalTrials.gov',
                'snippet': trial.get('brief_summary', 'Summary not provided'),
                'link': trial.get('url', ''),
                'status': trial.get('status', 'UNKNOWN'),
                'date': trial.get('completion_date', 'Unknown'),
                # ── Top-level fields for direct template access ──────────────
                'nct_number': trial.get('nct_number', nct_id),
                'nct_id': nct_id,
                'study_url': trial.get('study_url', trial.get('url', '')),
                'url': trial.get('url', ''),
                'acronym': trial.get('acronym', 'N/A'),
                'study_status': trial.get('study_status', trial.get('status', 'N/A')),
                'brief_summary': trial.get('brief_summary', 'N/A'),
                'has_results': trial.get('has_results', 'False'),
                'study_results': trial.get('study_results', 'No posted results'),
                'results_url': trial.get('results_url', ''),
                'phases': trial.get('phases', trial.get('phase', 'N/A')),
                'phase': trial.get('phase', 'N/A'),
                'study_design': trial.get('study_design', 'N/A'),
                'why_stopped': trial.get('why_stopped', 'N/A'),
                'interventions': trial.get('interventions', 'N/A'),
                'conditions': trial.get('conditions', 'N/A'),
                'primary_outcome_measures': trial.get('primary_outcome_measures', 'Not specified'),
                'secondary_outcome_measures': trial.get('secondary_outcome_measures', 'Not specified'),
                'other_outcome_measures': trial.get('other_outcome_measures', 'Not specified'),
                'sponsor': trial.get('sponsor', 'N/A'),
                'collaborators': trial.get('collaborators', 'None'),
                'funder_type': trial.get('funder_type', 'N/A'),
                'sex': trial.get('sex', 'N/A'),
                'age': trial.get('age', 'N/A'),
                'enrollment': trial.get('enrollment', 'N/A'),
                'study_type': trial.get('study_type', 'N/A'),
                'other_ids': trial.get('other_ids', 'N/A'),
                'start_date': trial.get('start_date', 'N/A'),
                'primary_completion_date': trial.get('primary_completion_date', 'N/A'),
                'completion_date': trial.get('completion_date', 'N/A'),
                'first_posted': trial.get('first_posted', 'N/A'),
                'results_first_posted': trial.get('results_first_posted', 'N/A'),
                'last_update_posted': trial.get('last_update_posted', 'N/A'),
                'study_documents': trial.get('study_documents', 'None'),
                # ── Structured metadata dict (for programmatic access) ────────
                'metadata': {
                    'nct_number': trial.get('nct_number', nct_id),
                    'nct_id': nct_id,
                    'study_url': trial.get('study_url', trial.get('url', '')),
                    'url': trial.get('url', ''),
                    'acronym': trial.get('acronym', 'N/A'),
                    'study_status': trial.get('study_status', trial.get('status', 'N/A')),
                    'brief_summary': trial.get('brief_summary', 'N/A'),
                    'has_results': trial.get('has_results', 'False'),
                    'study_results': trial.get('study_results', 'No posted results'),
                    'results_url': trial.get('results_url', ''),
                    'phases': trial.get('phases', trial.get('phase', 'N/A')),
                    'phase': trial.get('phase'),
                    'study_design': trial.get('study_design', 'N/A'),
                    'why_stopped': trial.get('why_stopped', 'N/A'),
                    'interventions': trial.get('interventions'),
                    'conditions': trial.get('conditions'),
                    'primary_outcome_measures': trial.get('primary_outcome_measures', 'Not specified'),
                    'secondary_outcome_measures': trial.get('secondary_outcome_measures', 'Not specified'),
                    'other_outcome_measures': trial.get('other_outcome_measures', 'Not specified'),
                    'sponsor': trial.get('sponsor'),
                    'collaborators': trial.get('collaborators', 'None'),
                    'funder_type': trial.get('funder_type', 'N/A'),
                    'sex': trial.get('sex', 'N/A'),
                    'age': trial.get('age', 'N/A'),
                    'enrollment': trial.get('enrollment'),
                    'study_type': trial.get('study_type', 'N/A'),
                    'other_ids': trial.get('other_ids', 'N/A'),
                    'start_date': trial.get('start_date'),
                    'primary_completion_date': trial.get('primary_completion_date', 'N/A'),
                    'completion_date': trial.get('completion_date'),
                    'first_posted': trial.get('first_posted', 'N/A'),
                    'results_first_posted': trial.get('results_first_posted', 'N/A'),
                    'last_update_posted': trial.get('last_update_posted', 'N/A'),
                    'study_documents': trial.get('study_documents', 'None'),
                }
            })
            
            # Structured results are collected in source_payloads to avoid heavy per-item calls here.

        return evidence_candidates

    def _build_data_layers(
        self,
        query: str,
        evidence_candidates: List[Dict[str, Any]],
        source_payloads: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Build report-oriented objective layers.

        Note:
        - This function organizes data for downstream report synthesis.
        - It does not output subjective investment/risk conclusions.
        """
        trials = source_payloads.get("clinicaltrials", {}).get("studies", [])
        pubmed_articles = source_payloads.get("pubmed", {}).get("articles", [])
        openfda_payload = source_payloads.get("openfda", {}) or {}
        label_results = (openfda_payload.get("label", {}) or {}).get("results", []) or []
        event_results = (openfda_payload.get("event", {}) or {}).get("results", []) or []
        drugsfda_results = (openfda_payload.get("drugsfda", {}) or {}).get("results", []) or []

        target_counts: Dict[str, int] = {}
        drug_class_counts: Dict[str, int] = {}
        phase_counts: Dict[str, int] = {}
        status_counts: Dict[str, int] = {}
        sponsor_counts: Dict[str, int] = {}

        required_trial_fields = [
            "nct_id",
            "title",
            "url",
            "acronym",
            "status",
            "brief_summary",
            "has_results",
            "study_results",
            "conditions",
            "interventions",
            "primary_outcome_measures",
            "secondary_outcome_measures",
            "other_outcome_measures",
            "phase",
            "enrollment",
            "funder_type",
            "study_type",
            "study_design",
            "other_ids",
            "start_date",
            "primary_completion_date",
            "completion_date",
            "first_posted",
            "results_first_posted",
            "last_update_posted",
            "study_documents",
            "sponsor",
            "collaborators",
            "sex",
            "age",
        ]

        def _is_present(value: Any) -> bool:
            return value not in (None, "", "N/A", "Unknown", "Not specified", "None", [], {})

        trial_field_coverage = {
            field: sum(1 for t in trials if _is_present(t.get(field)))
            for field in required_trial_fields
        }

        for trial in trials:
            trial_target_text = " ; ".join(
                [
                    str(trial.get("target", "")),
                    str(trial.get("targets", "")),
                    str(trial.get("interventions", "")),
                ]
            )
            for target in extract_normalized_targets(trial_target_text):
                target_counts[target] = target_counts.get(target, 0) + 1

            trial_class = normalize_drug_class(
                raw_text=" ".join(
                    [
                        str(trial.get("interventions", "")),
                        str(trial.get("title", "")),
                        str(trial.get("brief_summary", "")),
                    ]
                ),
                explicit_label=trial.get("drug_class") or trial.get("modality") or trial.get("platform"),
            )
            drug_class_counts[trial_class] = drug_class_counts.get(trial_class, 0) + 1

            phase = str(trial.get("phase", "Not specified"))
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            status = str(trial.get("status", "UNKNOWN"))
            status_counts[status] = status_counts.get(status, 0) + 1
            sponsor = str(trial.get("sponsor", "Unknown"))
            sponsor_counts[sponsor] = sponsor_counts.get(sponsor, 0) + 1

        for item in evidence_candidates:
            if not isinstance(item, dict):
                continue

            metadata = item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {}

            target_text = " ; ".join(
                [
                    str(item.get("target", "")),
                    str(item.get("targets", "")),
                    str(item.get("target_description", "")),
                    str(metadata.get("target", "")),
                    str(metadata.get("target_description", "")),
                    str(item.get("interventions", "")),
                    str(metadata.get("interventions", "")),
                ]
            )
            for target in extract_normalized_targets(target_text):
                target_counts[target] = target_counts.get(target, 0) + 1

            cls = normalize_drug_class(
                raw_text=" ".join(
                    [
                        str(item.get("interventions", "")),
                        str(metadata.get("interventions", "")),
                        str(item.get("title", "")),
                        str(item.get("snippet", "")),
                        str(item.get("mechanism", "")),
                        str(metadata.get("mechanism", "")),
                    ]
                ),
                explicit_label=item.get("drug_class") or metadata.get("drug_class") or item.get("modality") or metadata.get("modality"),
            )
            drug_class_counts[cls] = drug_class_counts.get(cls, 0) + 1

        return {
            "disease_layer": {
                "query_anchor": query,
                "conditions_from_trials": list({t.get("conditions", "") for t in trials if t.get("conditions")}),
            },
            "biology_layer": {
                "ncbi_gene_hits": (source_payloads.get("ncbi", {}).get("gene", {}) or {}).get("count", 0),
                "ncbi_protein_hits": (source_payloads.get("ncbi", {}).get("protein", {}) or {}).get("count", 0),
                "ncbi_clinvar_hits": (source_payloads.get("ncbi", {}).get("clinvar", {}) or {}).get("count", 0),
                "ncbi_gds_hits": (source_payloads.get("ncbi", {}).get("gds", {}) or {}).get("count", 0),
            },
            "target_layer": {
                "target_proxy_distribution": target_counts,
            },
            "drug_layer": {
                "openfda_counts": openfda_payload.get("counts", {}),
                "class_distribution": dict(sorted(drug_class_counts.items(), key=lambda kv: kv[1], reverse=True)),
                "openfda_label_snapshot": [
                    {
                        "generic_name": ((r.get("openfda", {}) or {}).get("generic_name") or [None])[0],
                        "brand_name": ((r.get("openfda", {}) or {}).get("brand_name") or [None])[0],
                        "manufacturer_name": ((r.get("openfda", {}) or {}).get("manufacturer_name") or [None])[0],
                        "application_number": ((r.get("openfda", {}) or {}).get("application_number") or [None])[0],
                        "effective_time": r.get("effective_time"),
                    }
                    for r in label_results[:20]
                ],
                "openfda_event_snapshot": [
                    {
                        "safetyreportid": r.get("safetyreportid"),
                        "receivedate": r.get("receivedate"),
                        "serious": r.get("serious"),
                        "seriousnessdeath": r.get("seriousnessdeath"),
                        "reaction_terms": [
                            x.get("reactionmeddrapt")
                            for x in ((r.get("patient", {}) or {}).get("reaction") or [])[:10]
                            if isinstance(x, dict) and x.get("reactionmeddrapt")
                        ],
                    }
                    for r in event_results[:20]
                ],
                "sample_drugsfda_records": drugsfda_results[:10],
            },
            "pipeline_layer": {
                "phase_distribution": phase_counts,
                "status_distribution": status_counts,
            },
            "company_layer": {
                "sponsor_distribution": sponsor_counts,
            },
            "regulatory_layer": {
                "openfda_approval_records": len(drugsfda_results),
                "openfda_approval_snapshot": [
                    {
                        "application_number": r.get("application_number"),
                        "sponsor_name": r.get("sponsor_name"),
                        "brand_name": ((r.get("products", []) or [{}])[0] or {}).get("brand_name"),
                        "marketing_status": ((r.get("products", []) or [{}])[0] or {}).get("marketing_status"),
                        "dosage_form": ((r.get("products", []) or [{}])[0] or {}).get("dosage_form"),
                        "submission_status": ((r.get("submissions", []) or [{}])[0] or {}).get("submission_status"),
                        "submission_status_date": ((r.get("submissions", []) or [{}])[0] or {}).get("submission_status_date"),
                    }
                    for r in drugsfda_results[:20]
                ],
            },
            "trial_registry_layer": {
                "required_field_coverage": trial_field_coverage,
                "sample_studies": [
                    {field: t.get(field) for field in required_trial_fields}
                    for t in trials[:20]
                ],
            },
            "landscape_layer": {
                "total_evidence_candidates": len(evidence_candidates),
                "trial_count": len(trials),
                "pubmed_article_count": len(pubmed_articles),
                "europe_pmc_count": len((source_payloads.get("europe_pmc", {}) or {}).get("papers", []) or []),
            },
            "insight_inputs": {
                "note": "Objective evidence inputs only. Subjective recommendations are intentionally excluded.",
            },
        }
    
    def _download_pdfs(self, evidence_candidates: List[Dict[str, Any]]) -> int:
        """
        Download PDFs from direct URLs (EuroPMC) and add local_path to each candidate.
        
        This method:
        1. Iterates through all evidence candidates
        2. Checks for direct PDF URL (from EuroPMC)
        3. Downloads the PDF using pdf_downloader tool
        4. Adds 'local_path' field to the candidate dict
        
        Args:
            evidence_candidates: List of evidence dicts (modified in-place)
            
        Returns:
            Number of successfully downloaded PDFs
        """
        downloaded_count = 0
        
        for candidate in evidence_candidates:
            # 🔥 FIX: Get PDF URL with improved logic
            metadata = candidate.get('metadata', {})
            pdf_url = metadata.get('pdf_url')
            
            # Skip if no PDF URL available
            if not pdf_url or pdf_url == "N/A":
                # Log why PDF is not available
                pmid = metadata.get('pmid')
                pmcid = metadata.get('pmcid')
                title = candidate.get('title', 'Unknown')[:60]
                if pmid and not pmcid:
                    logger.info(f"⏭️  Skipping PMID {pmid} - no PMC version (not open access)")
                    logger.debug(f"   Title: {title}...")
                elif pmcid:
                    logger.warning(f"⚠️  PMCID {pmcid} found but no PDF URL generated")
                    logger.debug(f"   Title: {title}...")
                else:
                    # Clinical trial or other source
                    logger.debug(f"⏭️  Skipping non-PubMed source: {title}...")
                candidate['local_path'] = None
                continue
            
            # Attempt download
            try:
                local_path = download_pdf_from_url(
                    url=pdf_url,
                    output_dir="downloads/pmc_pdfs"
                )
                
                if local_path:
                    candidate['local_path'] = local_path
                    downloaded_count += 1
                    logger.debug(f"✅ Downloaded: {pdf_url} -> {local_path}")
                else:
                    candidate['local_path'] = None
                    logger.debug(f"❌ Download failed: {pdf_url}")
                    
                    # No trial fallback here. Trial results are handled in unified source payloads.

            except Exception as e:
                logger.warning(f"PDF download error for {pdf_url}: {e}")
                candidate['local_path'] = None
        
        return downloaded_count


def create_agent() -> BioHarvestAgent:
    """
    Factory function to create a BioHarvestAgent instance.
    
    Returns:
        BioHarvestAgent: Initialized agent ready for use
    
    Example:
        >>> agent = create_agent()
        >>> results = agent.run("CAR-T therapy adverse events")
    """
    return BioHarvestAgent()

