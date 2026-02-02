"""
PubMed Client - Bio-Short-Seller Biomedical Literature Harvester

This module provides tools to search and retrieve scientific literature from PubMed
using the NCBI E-utilities API via Biopython.

Key Functions:
- search_pubmed: Search PubMed for articles matching a query
- fetch_details: Retrieve full article details including abstracts and links

Official NCBI E-utilities Documentation: https://www.ncbi.nlm.nih.gov/books/NBK25501/
"""

import os
import time
from typing import List, Dict, Optional
from loguru import logger

try:
    from Bio import Entrez
except ImportError:
    logger.error("Biopython not installed. Run: pip install biopython")
    raise


# ========== Configuration ==========
# NCBI requires an email for API access (helps them contact you if there's a problem)
# Set via environment variable PUBMED_EMAIL or use a default
Entrez.email = os.getenv("PUBMED_EMAIL", "bio-short-seller@example.com")
Entrez.tool = "Bio-Short-Seller"
Entrez.max_tries = 3
Entrez.sleep_between_tries = 2


def search_pubmed(
    query: str,
    max_results: int = 20,
    sort_by: str = "relevance",
    retries: int = 3
) -> List[str]:
    """
    Search PubMed for articles matching the query and return a list of PMIDs.
    
    Args:
        query: Search query (supports PubMed search syntax, e.g., "cancer[Title] AND toxicity")
        max_results: Maximum number of PMIDs to return (default: 20)
        sort_by: Sort order - 'relevance' or 'pub_date' (default: 'relevance')
        retries: Number of retry attempts on network failure (default: 3)
    
    Returns:
        List of PubMed IDs (PMIDs) as strings
    
    Example:
        >>> pmids = search_pubmed("pembrolizumab adverse events", max_results=10)
        >>> print(f"Found {len(pmids)} articles")
    
    Raises:
        Exception: If all retry attempts fail
    """
    logger.info(f"Searching PubMed: '{query}' (max_results={max_results})")
    
    for attempt in range(retries):
        try:
            # ESearch parameters documentation:
            # https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.ESearch
            handle = Entrez.esearch(
                db="pubmed",
                term=query,
                retmax=max_results,
                sort=sort_by,
                usehistory="y"  # Server-side history for large result sets
            )
            
            record = Entrez.read(handle)
            handle.close()
            
            pmid_list = record.get("IdList", [])
            count = record.get("Count", "0")
            
            logger.success(f"Found {len(pmid_list)} PMIDs (total matches: {count})")
            return pmid_list
            
        except Exception as e:
            logger.warning(f"PubMed search attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)  # Exponential backoff
            else:
                logger.error(f"PubMed search failed after {retries} attempts")
                raise
    
    return []


def fetch_details(pmid_list: List[str], batch_size: int = 20) -> List[Dict[str, str]]:
    """
    Fetch detailed metadata for a list of PMIDs.
    
    Args:
        pmid_list: List of PubMed IDs (PMIDs)
        batch_size: Number of records to fetch per request (default: 20, max: 500)
    
    Returns:
        List of dictionaries containing:
        - pmid: PubMed ID
        - title: Article title
        - abstract: Article abstract (if available)
        - authors: Comma-separated list of authors
        - journal: Journal name
        - pub_date: Publication date (YYYY-MM-DD or YYYY format)
        - doi: Digital Object Identifier (if available)
        - pmc_link: Link to PubMed Central full text (if available)
        - pubmed_link: Link to PubMed abstract page
    
    Example:
        >>> pmids = ["38234567", "38123456"]
        >>> articles = fetch_details(pmids)
        >>> for article in articles:
        ...     print(f"{article['title']} - {article['journal']}")
    
    Raises:
        Exception: If fetching fails after retries
    """
    if not pmid_list:
        logger.warning("Empty PMID list provided to fetch_details")
        return []
    
    logger.info(f"Fetching details for {len(pmid_list)} PMIDs")
    
    all_articles = []
    
    # Process in batches to avoid overwhelming the API
    for i in range(0, len(pmid_list), batch_size):
        batch = pmid_list[i:i + batch_size]
        
        try:
            # EFetch parameters documentation:
            # https://www.ncbi.nlm.nih.gov/books/NBK25499/#chapter4.EFetch
            handle = Entrez.efetch(
                db="pubmed",
                id=",".join(batch),
                rettype="medline",
                retmode="xml"
            )
            
            records = Entrez.read(handle)
            handle.close()
            
            # Parse each article
            for record in records.get("PubmedArticle", []):
                article_data = _parse_pubmed_record(record)
                if article_data:
                    all_articles.append(article_data)
            
            # Be polite to NCBI servers
            if i + batch_size < len(pmid_list):
                time.sleep(0.5)
            
        except Exception as e:
            logger.error(f"Failed to fetch batch {i//batch_size + 1}: {e}")
            # Continue with other batches instead of failing completely
            continue
    
    logger.success(f"Successfully fetched {len(all_articles)} article details")
    return all_articles


def _parse_pubmed_record(record: Dict) -> Optional[Dict[str, str]]:
    """
    Parse a single PubMed XML record into a structured dictionary.
    
    Args:
        record: PubmedArticle record from Entrez.read()
    
    Returns:
        Dictionary with article metadata or None if parsing fails
    """
    try:
        medline_citation = record.get("MedlineCitation", {})
        article = medline_citation.get("Article", {})
        
        # PMID
        pmid = str(medline_citation.get("PMID", ""))
        
        # Title
        title = article.get("ArticleTitle", "No title available")
        
        # Abstract (may have multiple sections)
        abstract_data = article.get("Abstract", {})
        abstract_texts = abstract_data.get("AbstractText", [])
        if isinstance(abstract_texts, list):
            # Handle structured abstracts (BACKGROUND, METHODS, etc.)
            abstract = " ".join([str(text) for text in abstract_texts])
        else:
            abstract = str(abstract_texts)
        
        if not abstract or abstract == "[]":
            abstract = "No abstract available"
        
        # Authors
        author_list = article.get("AuthorList", [])
        authors = []
        for author in author_list[:5]:  # Limit to first 5 authors
            last_name = author.get("LastName", "")
            initials = author.get("Initials", "")
            if last_name:
                authors.append(f"{last_name} {initials}".strip())
        
        authors_str = ", ".join(authors) if authors else "Unknown authors"
        if len(author_list) > 5:
            authors_str += ", et al."
        
        # Journal
        journal = article.get("Journal", {})
        journal_title = journal.get("Title", "Unknown journal")
        
        # Publication date
        pub_date_data = article.get("ArticleDate", [])
        if pub_date_data:
            pub_date_dict = pub_date_data[0]
            year = pub_date_dict.get("Year", "")
            month = pub_date_dict.get("Month", "01").zfill(2)
            day = pub_date_dict.get("Day", "01").zfill(2)
            pub_date = f"{year}-{month}-{day}"
        else:
            # Fallback to journal issue date
            journal_issue = journal.get("JournalIssue", {})
            pub_date_fallback = journal_issue.get("PubDate", {})
            pub_date = pub_date_fallback.get("Year", "Unknown date")
        
        # DOI
        article_ids = record.get("PubmedData", {}).get("ArticleIdList", [])
        doi = None
        pmc_id = None
        
        for article_id in article_ids:
            id_type = article_id.attributes.get("IdType", "")
            if id_type == "doi":
                doi = str(article_id)
            elif id_type == "pmc":
                pmc_id = str(article_id)
        
        # Links
        pubmed_link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
        pmc_link = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/" if pmc_id else None
        
        return {
            "pmid": pmid,
            "title": title,
            "abstract": abstract,
            "authors": authors_str,
            "journal": journal_title,
            "pub_date": pub_date,
            "doi": doi or "N/A",
            "pmc_link": pmc_link or "N/A",
            "pubmed_link": pubmed_link,
        }
        
    except Exception as e:
        logger.error(f"Failed to parse PubMed record: {e}")
        return None


# ========== Example Usage ==========
if __name__ == "__main__":
    # Example 1: Search for drug toxicity
    print("\n=== Example 1: Drug Toxicity Search ===")
    pmids = search_pubmed("pembrolizumab cardiotoxicity", max_results=5)
    
    if pmids:
        articles = fetch_details(pmids)
        for article in articles:
            print(f"\nTitle: {article['title']}")
            print(f"Authors: {article['authors']}")
            print(f"Journal: {article['journal']} ({article['pub_date']})")
            print(f"Abstract: {article['abstract'][:200]}...")
            print(f"Link: {article['pubmed_link']}")
            if article['pmc_link'] != "N/A":
                print(f"Full Text: {article['pmc_link']}")
    
    # Example 2: Search for clinical trial failures
    print("\n\n=== Example 2: Clinical Trial Failures ===")
    pmids = search_pubmed("clinical trial terminated adverse events", max_results=3)
    
    if pmids:
        articles = fetch_details(pmids)
        for article in articles:
            print(f"\n{article['title']}")
            print(f"  → {article['pubmed_link']}")
