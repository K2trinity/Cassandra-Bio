"""
BioHarvest Agent - Biomedical Evidence Harvester for Bio-Short-Seller

This agent searches PubMed, EuroPMC, and ClinicalTrials.gov for "dark data":
- Failed clinical trials (terminated, suspended, withdrawn)
- Adverse event reports
- Toxicity signals in published literature
- Negative efficacy data

Core workflow:
1. Parse user intent (drug/therapy/company to investigate)
2. Generate specific search queries using Gemini LLM
3. Execute parallel searches on EuroPMC (PRIMARY for PDF access) + PubMed + ClinicalTrials.gov
4. Download PDFs directly from EuroPMC (no scraping needed)
5. Return structured evidence with local PDF paths
"""

import json
import os
from datetime import datetime
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor, as_completed

from src.llms import create_bioharvest_client
from src.tools import search_pubmed, fetch_details, search_failed_trials, EuroPMCClient
from src.tools.pdf_downloader import download_pdf_from_url
from src.tools.clinical_trials_results_client import get_trial_results_as_fallback  # P1: Second Shovel
from loguru import logger
from src.utils.stream_validator import StreamValidator


class BioHarvestAgent:
    """
    Biomedical Evidence Harvester Agent
    
    Transforms high-level investigative queries into structured evidence candidates
    by sweeping scientific databases for negative signals.
    
    Now uses EuroPMC as PRIMARY source for direct PDF access.
    """
    
    def __init__(self):
        """Initialize BioHarvest Agent with Gemini LLM and biomedical search tools."""
        
        # Initialize LLM client (Gemini Pro for query generation)
        self.llm = create_bioharvest_client()
        
        # Initialize EuroPMC client (PRIMARY source for PDFs)
        self.europmc = EuroPMCClient()
        
        logger.info("BioHarvest Agent initialized with Gemini LLM + EuroPMC Client")
        
        # Tools are imported as functions (no initialization needed)
        # - search_pubmed, fetch_details: PubMed literature search (FALLBACK)
        # - search_failed_trials: ClinicalTrials.gov failure detector
    
    def run(self, user_query: str, max_results_per_source: int = 20) -> Dict[str, Any]:
        """
        Execute biomedical evidence harvesting workflow.
        
        Args:
            user_query: High-level investigative query 
                       (e.g., "pembrolizumab toxicity", "Theranos failures", "CAR-T adverse events")
            max_results_per_source: Maximum results to retrieve from each source
        
        Returns:
            Dictionary with structure:
            {
                'results': [  # List of evidence candidates
                    {
                        'title': str,        # Article/trial title
                        'source': str,       # 'PubMed' or 'ClinicalTrials.gov'
                        'snippet': str,      # Abstract excerpt or why_stopped reason
                        'link': str,         # Full URL to original source
                        'status': str,       # For trials: TERMINATED/SUSPENDED/WITHDRAWN, for articles: 'Published'
                        'date': str,         # Publication/completion date
                        'metadata': dict     # Additional fields (authors, journal, phase, etc.)
                    },
                    ...
                ],
                'stats': {  # Summary statistics
                    'total': int,
                    'pubmed': int,
                    'trials': int
                }
            }
        
        Workflow:
            Step A: Intent Parsing → Generate specific search queries using Gemini
            Step B: Execution → Parallel searches on PubMed + ClinicalTrials.gov
            Step C: Aggregation → Structure results into evidence candidates
        
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
            
            # Search ClinicalTrials.gov for failed trials
            trial_results = self._execute_trials_searches(
                search_queries.get("clinicaltrials", []),
                max_results_per_source
            )
            
            # Combine results
            pubmed_results = europmc_papers + pubmed_articles
            
            # ===== STEP C: Aggregation =====
            logger.info("\n[Step C] Aggregating evidence candidates...")
            evidence_candidates = self._aggregate_results(pubmed_results, trial_results)
            
            # ===== STEP D: PDF Download (NEW) =====
            logger.info("\n[Step D] Downloading full-text PDFs from PMC...")
            downloaded_count = self._download_pdfs(evidence_candidates)
            
            logger.info(f"\n{'='*60}")
            logger.success(f"✅ Harvested {len(evidence_candidates)} evidence candidates")
            logger.info(f"   - PubMed articles: {len(pubmed_results)}")
            logger.info(f"   - Failed trials: {len(trial_results)}")
            logger.info(f"   - PDFs downloaded: {downloaded_count}")
            logger.info(f"{'='*60}\n")
            
            # Return structured result matching supervisor expectations
            return {
                "results": evidence_candidates,
                "stats": {
                    "total": len(evidence_candidates),
                    "pubmed": len(pubmed_results),
                    "trials": len(trial_results),
                    "pdfs_downloaded": downloaded_count
                }
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

Generate 3 specific search queries for each database to find NEGATIVE signals (failures, toxicity, adverse events, terminations):

1. **PubMed queries**: 
   - CRITICAL: Keep queries SIMPLE and CONCISE (2-4 keywords max)
   - MANDATORY: Include the core term "{core_terms}" in at least 2 queries
   - PubMed's search algorithm works best with SHORT queries
   - Complex multi-word queries often return 0 results
   - Focus on core concepts only
   - ✅ GOOD: "CRISPR adverse events", "CRISPR toxicity", "CRISPR off-target"
   - ❌ BAD: "CRISPR off-target adverse events clinical trials toxicity genotoxicity"
   - Include ONE risk term per query: "toxicity", "adverse events", "failure", "off-target"

2. **ClinicalTrials.gov queries**: 
   - Use drug names, company names, or therapy types
   - MUST include core term "{core_terms}"
   - Keep queries concise (the API will filter for failed trials automatically)
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
                    f"{user_query} toxicity",
                    f"{user_query} adverse events",
                    f"{user_query} failure"
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
                trials = search_failed_trials(query, max_results=max_results)
                all_trials.extend(trials)
            except Exception as e:
                logger.warning(f"ClinicalTrials search failed for '{query}': {e}")
        return all_trials
    
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
                    search_failed_trials, 
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
        failed_trials: List[Dict]
    ) -> List[Dict[str, str]]:
        """
        Convert raw API results into standardized evidence candidate format.
        
        Handles both EuroPMC results (with pdf_url) and PubMed fallback results.
        
        Args:
            pubmed_articles: List of article dicts from EuroPMC or fetch_details()
            failed_trials: List of trial dicts from search_failed_trials()
        
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
        
        # Process failed clinical trials
        for trial in failed_trials:
            nct_id = trial.get('nct_id')
            
            evidence_candidates.append({
                'title': trial.get('title', 'No title'),
                'source': 'ClinicalTrials.gov',
                'snippet': trial.get('why_stopped', 'Reason not provided'),
                'link': trial.get('url', ''),
                'status': trial.get('status', 'UNKNOWN'),
                'date': trial.get('completion_date', 'Unknown'),
                'metadata': {
                    'nct_id': nct_id,
                    'phase': trial.get('phase'),
                    'interventions': trial.get('interventions'),
                    'conditions': trial.get('conditions'),
                    'sponsor': trial.get('sponsor'),
                    'enrollment': trial.get('enrollment')
                }
            })
            
            # 🚨 P1: For failed trials, try to get detailed results from ClinicalTrials.gov
            if nct_id and nct_id.startswith('NCT'):
                try:
                    logger.info(f"🔍 Fetching detailed results for failed trial {nct_id}...")
                    ct_results = get_trial_results_as_fallback(nct_id)
                    if ct_results and ct_results.get('has_results'):
                        # Add to the last candidate we just appended
                        evidence_candidates[-1]['ct_structured_results'] = ct_results
                        evidence_candidates[-1]['data_source'] = 'ClinicalTrials.gov_API'
                        logger.success(f"✅ Retrieved detailed adverse event data for {nct_id}")
                except Exception as e:
                    logger.debug(f"Could not fetch detailed results for {nct_id}: {e}")
        
        return evidence_candidates
    
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
                    
                    # 🚨 P1: Second Shovel - Try ClinicalTrials.gov if NCT ID exists
                    nct_id = metadata.get('nct_id')
                    if nct_id and nct_id.startswith('NCT'):
                        logger.info(f"🔄 PDF failed, activating ClinicalTrials.gov fallback for {nct_id}...")
                        ct_results = get_trial_results_as_fallback(nct_id)
                        if ct_results and ct_results.get('has_results'):
                            candidate['ct_structured_results'] = ct_results
                            candidate['data_source'] = 'ClinicalTrials.gov_API'
                            logger.success(f"✅ Retrieved structured results from ClinicalTrials.gov")
                        else:
                            logger.warning(f"⚠️ No structured results available for {nct_id}")
                    
            except Exception as e:
                logger.warning(f"PDF download error for {pdf_url}: {e}")
                candidate['local_path'] = None
                
                # 🚨 P1: Second Shovel - Try ClinicalTrials.gov even on exception
                nct_id = metadata.get('nct_id')
                if nct_id and nct_id.startswith('NCT'):
                    try:
                        logger.info(f"🔄 Exception occurred, trying ClinicalTrials.gov fallback for {nct_id}...")
                        ct_results = get_trial_results_as_fallback(nct_id)
                        if ct_results and ct_results.get('has_results'):
                            candidate['ct_structured_results'] = ct_results
                            candidate['data_source'] = 'ClinicalTrials.gov_API'
                            logger.success(f"✅ Retrieved structured results from ClinicalTrials.gov")
                    except Exception as ct_error:
                        logger.warning(f"ClinicalTrials.gov fallback also failed: {ct_error}")
        
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

