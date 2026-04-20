"""
Preprint Client - Cassandra Preprint Harvester

This module provides tools to search BioRxiv and MedRxiv for preprints (unpublished research).
90% of published articles have preprint versions that are freely accessible, making this a
critical fallback when paywalled papers block access.

Key Functions:
- search_biorxiv: Search BioRxiv for biology/life sciences preprints
- search_medrxiv: Search MedRxiv for medical/clinical preprints  
- find_preprint_by_doi: Find preprint version of a published article
- find_preprint_by_title: Find preprint by matching article title

Official APIs:
- BioRxiv/MedRxiv API: https://api.biorxiv.org/
"""

try:
    from curl_cffi import requests
except ImportError:
    import requests
import time
from typing import List, Dict, Optional
from loguru import logger
from datetime import datetime, timedelta
from difflib import SequenceMatcher


# ========== Configuration ==========
BIORXIV_API_BASE = "https://api.biorxiv.org/details/biorxiv"
MEDRXIV_API_BASE = "https://api.biorxiv.org/details/medrxiv"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3


def search_preprints(
    query: str,
    server: str = "both",
    days_back: int = 365,
    max_results: int = 20,
    retries: int = MAX_RETRIES
) -> List[Dict[str, str]]:
    """
    Search BioRxiv and/or MedRxiv for preprints matching the query.
    
    Args:
        query: Search keyword (title, author, subject)
        server: Which server to search - "biorxiv", "medrxiv", or "both" (default)
        days_back: How many days back to search (default: 365)
        max_results: Maximum number of results to return (default: 20)
        retries: Number of retry attempts (default: 3)
    
    Returns:
        List of preprint dictionaries containing:
        - doi: Preprint DOI
        - title: Article title
        - authors: Author list
        - abstract: Full abstract
        - date: Publication date
        - category: Subject category
        - pdf_url: Direct PDF download link
        - version: Preprint version number
        - server: "biorxiv" or "medrxiv"
    
    Example:
        >>> preprints = search_preprints("CRISPR off-target", server="both")
        >>> for p in preprints:
        ...     print(f"{p['title']}: {p['pdf_url']}")
    """
    logger.info(f"Searching preprints: '{query}' on {server} (last {days_back} days)")
    
    # Calculate date range
    end_date = datetime.now().strftime("%Y-%m-%d")
    start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    
    results = []
    
    servers_to_search = []
    if server in ["biorxiv", "both"]:
        servers_to_search.append(("biorxiv", BIORXIV_API_BASE))
    if server in ["medrxiv", "both"]:
        servers_to_search.append(("medrxiv", MEDRXIV_API_BASE))
    
    for server_name, api_base in servers_to_search:
        url = f"{api_base}/{start_date}/{end_date}"
        
        for attempt in range(retries):
            try:
                response = requests.get(
                    url,
                    timeout=DEFAULT_TIMEOUT,
                    headers={"User-Agent": "Cassandra/1.0"}
                )
                
                response.raise_for_status()
                data = response.json()
                
                # Parse results
                collection = data.get("collection", [])
                
                # Filter by query (case-insensitive search in title and authors)
                query_lower = query.lower()
                filtered = []
                
                for article in collection:
                    title = article.get("title", "").lower()
                    authors = article.get("authors", "").lower()
                    abstract = article.get("abstract", "").lower()
                    
                    if (query_lower in title or 
                        query_lower in authors or 
                        query_lower in abstract):
                        filtered.append(article)
                
                logger.success(f"Found {len(filtered)} preprints on {server_name}")
                
                # Format results
                for article in filtered[:max_results]:
                    results.append(_format_preprint(article, server_name))
                
                break  # Success, exit retry loop
                
            except requests.exceptions.RequestException as e:
                logger.warning(f"{server_name} request attempt {attempt + 1}/{retries} failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                else:
                    logger.error(f"{server_name} search failed after {retries} attempts")
            except Exception as e:
                logger.error(f"Unexpected error searching {server_name}: {e}")
                break
    
    logger.info(f"Total preprints found: {len(results)}")
    return results[:max_results]


def find_preprint_by_doi(doi: str, retries: int = MAX_RETRIES) -> Optional[Dict[str, str]]:
    """
    🔥 Find preprint version of a published article by DOI.
    
    This is the PRIMARY FALLBACK for paywalled papers. Many publishers allow
    authors to post preprints, which contain nearly identical content.
    
    Args:
        doi: Published article DOI (e.g., "10.1038/s41586-020-2012-7")
        retries: Number of retry attempts
    
    Returns:
        Preprint dictionary if found, None otherwise
    
    Example:
        >>> preprint = find_preprint_by_doi("10.1126/science.aay3224")
        >>> if preprint:
        ...     print(f"Found preprint: {preprint['pdf_url']}")
    """
    logger.info(f"Searching for preprint version of DOI: {doi}")
    
    # Try both servers
    for server_name, api_base in [("biorxiv", BIORXIV_API_BASE), 
                                    ("medrxiv", MEDRXIV_API_BASE)]:
        url = f"{api_base.replace('/details/', '/pubs/')}/{doi}"
        
        for attempt in range(retries):
            try:
                response = requests.get(
                    url,
                    timeout=DEFAULT_TIMEOUT,
                    headers={"User-Agent": "Cassandra/1.0"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    collection = data.get("collection", [])
                    
                    if collection:
                        logger.success(f"Found preprint on {server_name} for DOI: {doi}")
                        return _format_preprint(collection[0], server_name)
                
            except requests.exceptions.RequestException as e:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Error searching {server_name} for DOI: {e}")
                break
    
    logger.warning(f"No preprint found for DOI: {doi}")
    return None


def find_preprint_by_title(
    title: str,
    similarity_threshold: float = 0.85,
    days_back: int = 730,
    retries: int = MAX_RETRIES
) -> Optional[Dict[str, str]]:
    """
    🔥 Find preprint by fuzzy matching article title.
    
    Use this when DOI lookup fails. Matches titles with >85% similarity
    to handle minor formatting differences.
    
    Args:
        title: Article title to search for
        similarity_threshold: Minimum similarity score (0-1) to consider a match
        days_back: How many days back to search (default: 730 = 2 years)
        retries: Number of retry attempts
    
    Returns:
        Best matching preprint if found, None otherwise
    
    Example:
        >>> title = "CRISPR-Cas9 genome editing induces off-target mutations"
        >>> preprint = find_preprint_by_title(title)
        >>> if preprint:
        ...     print(f"Match: {preprint['title']}")
    """
    logger.info(f"Searching for preprint by title: '{title[:50]}...'")
    
    # Extract key terms from title for broad search
    key_terms = title.lower().split()[:5]  # First 5 words
    query = " ".join(key_terms)
    
    # Search both servers
    candidates = search_preprints(
        query=query,
        server="both",
        days_back=days_back,
        max_results=50,
        retries=retries
    )
    
    if not candidates:
        logger.warning(f"No preprints found matching title keywords")
        return None
    
    # Find best match by title similarity
    best_match = None
    best_score = 0.0
    
    title_normalized = title.lower().strip()
    
    for candidate in candidates:
        candidate_title = candidate['title'].lower().strip()
        score = SequenceMatcher(None, title_normalized, candidate_title).ratio()
        
        if score > best_score:
            best_score = score
            best_match = candidate
    
    if best_score >= similarity_threshold:
        logger.success(f"Found preprint match (similarity: {best_score:.2%}): {best_match['title'][:60]}...")
        return best_match
    else:
        logger.warning(f"Best match similarity ({best_score:.2%}) below threshold ({similarity_threshold:.2%})")
        return None


def _format_preprint(article: Dict, server: str) -> Dict[str, str]:
    """Format preprint data into standardized dictionary."""
    doi = article.get("doi", "")
    
    return {
        "doi": doi,
        "title": article.get("title", "No title"),
        "authors": article.get("authors", "Unknown authors"),
        "abstract": article.get("abstract", "No abstract available"),
        "date": article.get("date", "Unknown date"),
        "category": article.get("category", "Uncategorized"),
        "pdf_url": f"https://www.{server}.org/content/{doi}v{article.get('version', '1')}.full.pdf",
        "html_url": f"https://www.{server}.org/content/{doi}",
        "version": str(article.get("version", 1)),
        "server": server
    }


# ========== Example Usage ==========
if __name__ == "__main__":
    # Example 1: Search for CRISPR preprints
    print("\n=== Example 1: Search CRISPR Preprints ===")
    preprints = search_preprints("CRISPR off-target", server="both", max_results=5)
    
    for p in preprints:
        print(f"\n{p['title'][:70]}...")
        print(f"  Server: {p['server']} | Date: {p['date']}")
        print(f"  PDF: {p['pdf_url']}")
    
    # Example 2: Find preprint by DOI (fallback for paywalled paper)
    print("\n\n=== Example 2: Find Preprint by DOI ===")
    # This is a real Nature paper with a BioRxiv preprint
    doi = "10.1038/s41586-020-2649-2"
    preprint = find_preprint_by_doi(doi)
    
    if preprint:
        print(f"✅ Found preprint for {doi}")
        print(f"  Title: {preprint['title']}")
        print(f"  Free PDF: {preprint['pdf_url']}")
    else:
        print(f"❌ No preprint found for {doi}")
    
    # Example 3: Find preprint by title fuzzy matching
    print("\n\n=== Example 3: Find Preprint by Title ===")
    title = "Structure-guided design of a SARS-CoV-2 main protease inhibitor"
    preprint = find_preprint_by_title(title, similarity_threshold=0.8)
    
    if preprint:
        print(f"✅ Found matching preprint")
        print(f"  Title: {preprint['title']}")
        print(f"  Similarity: High")
        print(f"  PDF: {preprint['pdf_url']}")
    else:
        print(f"❌ No matching preprint found")
