"""
Europe PMC API Client - Bio-Short-Seller PDF Retrieval

Europe PMC (https://europepmc.org) provides a comprehensive database of life sciences literature
with direct access to full-text PDFs via a REST API.

Key advantages over NCBI:
- Direct PDF URLs without JavaScript redirects
- No aggressive anti-bot protection
- Better API rate limits
- More reliable for automated downloads

API Documentation: https://europepmc.org/RestfulWebService
"""

import time
from typing import List, Dict, Optional, Any
from loguru import logger

try:
    from curl_cffi import requests
    HAS_CURL_CFFI = True
except ImportError:
    import requests
    HAS_CURL_CFFI = False
    logger.warning("curl-cffi not available, falling back to standard requests (may encounter 403 errors)")


class EuroPMCClient:
    """
    Europe PMC API client for searching and downloading biomedical literature.
    
    Provides:
    - Literature search with filters
    - Direct PDF URL extraction
    - Full-text availability checking
    - Metadata retrieval
    """
    
    BASE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest"
    
    def __init__(self, email: Optional[str] = None):
        """
        Initialize Europe PMC client.
        
        Args:
            email: Optional email for API courtesy (not required but recommended)
        """
        self.email = email
        self.session = requests.Session() if HAS_CURL_CFFI else requests.Session()
        logger.info("EuroPMC Client initialized")
    
    def search_papers(
        self,
        query: str,
        max_results: int = 20,
        sort: str = "relevance",
        open_access_only: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Search Europe PMC for papers matching query.
        
        Args:
            query: Search query (PubMed-style syntax)
            max_results: Maximum number of results to return
            sort: Sort order ('relevance', 'cited', 'date')
            open_access_only: Only return papers with full-text access
        
        Returns:
            List of paper dictionaries with metadata and PDF URLs
            
        Example:
            >>> client = EuroPMCClient()
            >>> papers = client.search_papers("CRISPR adverse events", max_results=10)
            >>> for paper in papers:
            ...     if paper.get('pdf_url'):
            ...         print(f"PDF available: {paper['title']}")
        """
        logger.info(f"Searching EuroPMC: '{query}' (max_results={max_results})")
        
        try:
            # Build query with filters
            search_query = query
            if open_access_only:
                search_query += " AND OPEN_ACCESS:y"
            
            # API parameters
            params = {
                "query": search_query,
                "format": "json",
                "pageSize": max_results,
                "sort": sort,
                "resultType": "core"
            }
            
            # Make request
            url = f"{self.BASE_URL}/search"
            
            if HAS_CURL_CFFI:
                response = self.session.get(
                    url,
                    params=params,
                    impersonate="chrome120",
                    timeout=30
                )
            else:
                response = self.session.get(url, params=params, timeout=30)
            
            response.raise_for_status()
            data = response.json()
            
            # Parse results
            hit_count = data.get("hitCount", 0)
            results = data.get("resultList", {}).get("result", [])
            
            logger.success(f"Found {len(results)} papers (total matches: {hit_count})")
            
            # Extract structured data with PDF URLs
            papers = []
            for item in results:
                paper = self._parse_paper(item)
                if paper:
                    papers.append(paper)
            
            pdf_count = sum(1 for p in papers if p.get('pdf_url'))
            logger.info(f"Papers with PDFs: {pdf_count}/{len(papers)}")
            
            return papers
            
        except Exception as e:
            logger.error(f"EuroPMC search failed: {e}")
            return []
    
    def _parse_paper(self, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Parse Europe PMC API result into standardized paper dict.
        
        Args:
            item: Raw API result item
        
        Returns:
            Structured paper dictionary or None if invalid
        """
        try:
            # Extract PMC ID and PMID
            pmcid = item.get("pmcid")  # e.g., "PMC8675309"
            pmid = item.get("pmid")
            
            # Get PDF URL from fullTextUrlList
            pdf_url = None
            full_text_urls = item.get("fullTextUrlList", {}).get("fullTextUrl", [])
            
            for url_entry in full_text_urls:
                if url_entry.get("documentStyle") == "pdf":
                    pdf_url = url_entry.get("url")
                    break
            
            # If no PDF URL but has PMCID, construct EuroPMC download URL
            if not pdf_url and pmcid:
                pdf_url = f"https://europepmc.org/articles/{pmcid}?pdf=render"
            
            # Build paper dictionary
            paper = {
                "title": item.get("title", "No title"),
                "pmid": pmid,
                "pmcid": pmcid,
                "doi": item.get("doi"),
                "authors": self._extract_authors(item),
                "journal": item.get("journalTitle"),
                "pub_date": item.get("firstPublicationDate"),
                "abstract": item.get("abstractText", ""),
                "pdf_url": pdf_url,
                "pubmed_link": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else None,
                "pmc_link": f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/" if pmcid else None,
                "source": "EuroPMC"
            }
            
            return paper
            
        except Exception as e:
            logger.warning(f"Failed to parse paper: {e}")
            return None
    
    def _extract_authors(self, item: Dict[str, Any]) -> str:
        """Extract author list from API response."""
        try:
            author_list = item.get("authorList", {}).get("author", [])
            if not author_list:
                return "Unknown"
            
            # Format: "LastName FM, LastName FM, ..."
            authors = []
            for author in author_list[:5]:  # Limit to first 5
                last_name = author.get("lastName", "")
                initials = author.get("initials", "")
                if last_name:
                    authors.append(f"{last_name} {initials}".strip())
            
            result = ", ".join(authors)
            if len(author_list) > 5:
                result += ", et al."
            
            return result or "Unknown"
            
        except Exception:
            return "Unknown"
    
    def get_pdf_url(self, pmcid: str) -> Optional[str]:
        """
        Get direct PDF download URL for a PMC article.
        
        Args:
            pmcid: PubMed Central ID (e.g., "PMC8675309")
        
        Returns:
            Direct PDF URL or None if not available
            
        Example:
            >>> client = EuroPMCClient()
            >>> pdf_url = client.get_pdf_url("PMC8675309")
            >>> if pdf_url:
            ...     download_pdf(pdf_url)
        """
        # EuroPMC provides a consistent PDF rendering URL
        if not pmcid or not pmcid.startswith("PMC"):
            logger.warning(f"Invalid PMCID: {pmcid}")
            return None
        
        return f"https://europepmc.org/articles/{pmcid}?pdf=render"
    
    def check_pdf_availability(self, pmcid: str) -> bool:
        """
        Check if PDF is available for a PMC article.
        
        Args:
            pmcid: PubMed Central ID
        
        Returns:
            True if PDF is available, False otherwise
        """
        try:
            url = f"{self.BASE_URL}/{pmcid}"
            params = {"format": "json"}
            
            if HAS_CURL_CFFI:
                response = self.session.get(
                    url,
                    params=params,
                    impersonate="chrome120",
                    timeout=15
                )
            else:
                response = self.session.get(url, params=params, timeout=15)
            
            data = response.json()
            
            # Check for PDF in fullTextUrlList
            full_text_urls = data.get("fullTextUrlList", {}).get("fullTextUrl", [])
            for url_entry in full_text_urls:
                if url_entry.get("documentStyle") == "pdf":
                    return True
            
            return False
            
        except Exception as e:
            logger.warning(f"PDF availability check failed for {pmcid}: {e}")
            return False


def search_europmc(
    query: str,
    max_results: int = 20,
    open_access_only: bool = True
) -> List[Dict[str, Any]]:
    """
    Convenience function to search Europe PMC.
    
    Args:
        query: Search query
        max_results: Maximum results to return
        open_access_only: Only return open-access papers
    
    Returns:
        List of paper dictionaries
        
    Example:
        >>> papers = search_europmc("CRISPR toxicity", max_results=10)
        >>> print(f"Found {len(papers)} papers")
    """
    client = EuroPMCClient()
    return client.search_papers(
        query=query,
        max_results=max_results,
        open_access_only=open_access_only
    )
