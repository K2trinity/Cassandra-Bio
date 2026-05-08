"""
PubPeer Client - Cassandra Publication Integrity Intelligence Harvester

🏴‍☠️ THE ULTIMATE WEAPON: PubPeer is where the scientific community exposes fraud.

PubPeer is a post-publication peer review platform where scientists anonymously
flag problematic research. For controversial drugs like Simufilam, PubPeer often
has detailed analyses of manipulated figures BEFORE fraud becomes mainstream news.

Key Functions:
- search_pubpeer_by_doi: Get all PubPeer comments for an article
- get_fraud_signals: Summarize fraud indicators from comments

Why PubPeer is Critical:
1. Early Warning System: Fraud is often flagged on PubPeer years before retraction
2. Community Evidence: Comments often describe suspected manipulation or data issues
3. Statistical Red Flags: Scientists post detailed analyses of impossible data
4. Community Validation: Multiple independent researchers confirming issues

⚠️ IMPORTANT: PubPeer does not have an official public API.
We use web scraping with extreme politeness (slow rate limits, caching).
"""

import requests
import time
from typing import List, Dict, Optional
from loguru import logger
from urllib.parse import urljoin, quote
import hashlib
import json
from pathlib import Path

try:
    from curl_cffi import requests as cf_requests
    from bs4 import BeautifulSoup
except ImportError:
    logger.error("Required packages missing. Run: pip install curl_cffi beautifulsoup4")
    raise


# ========== Configuration ==========
PUBPEER_BASE_URL = "https://pubpeer.com"
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RATE_LIMIT_DELAY = 2  # Seconds between requests (be respectful!)
CACHE_DIR = Path("cache/pubpeer")
CACHE_EXPIRY_DAYS = 7


def search_pubpeer_by_doi(
    doi: str,
    use_cache: bool = True,
    retries: int = MAX_RETRIES
) -> Optional[Dict]:
    """
    🔥 Search PubPeer for comments/flags on a specific article by DOI.
    
    This is the PRIMARY tool for detecting known fraud. If an article has
    PubPeer comments with image analysis, it's a major red flag.
    
    Args:
        doi: Article DOI (e.g., "10.1038/s41586-020-2012-7")
        use_cache: Use cached results if available (default: True)
        retries: Number of retry attempts
    
    Returns:
        Dictionary containing:
        - doi: Article DOI
        - has_comments: Boolean indicating if comments exist
        - comment_count: Number of comments
        - pubpeer_url: Direct link to PubPeer page
        - comments: List of comment dictionaries with:
            - text: Comment text
            - author: Commenter name (often "Anonymous")
            - date: Comment date
            - images: List of image URLs in comment
        - fraud_signals: Dict of detected fraud indicators:
            - image_manipulation: Boolean
            - data_inconsistency: Boolean
            - statistical_issues: Boolean
            - plagiarism: Boolean
    
    Example:
        >>> result = search_pubpeer_by_doi("10.3233/JAD-220762")  # Simufilam
        >>> if result['has_comments']:
        ...     print(f"⚠️ {result['comment_count']} PubPeer comments found!")
        ...     for comment in result['comments']:
        ...         print(f"  - {comment['text'][:100]}...")
    """
    logger.info(f"🔍 Searching PubPeer for DOI: {doi}")
    
    # Check cache first
    if use_cache:
        cached = _load_from_cache(doi)
        if cached:
            logger.info("⚡ Loaded from cache")
            return cached
    
    # Rate limiting (be respectful!)
    time.sleep(RATE_LIMIT_DELAY)
    
    # PubPeer URL format: https://pubpeer.com/publications/DOI_HERE
    # DOI needs to be URL-encoded
    encoded_doi = quote(doi, safe='')
    pubpeer_url = f"{PUBPEER_BASE_URL}/publications/{encoded_doi}"
    
    logger.info(f"📡 Fetching: {pubpeer_url}")
    
    for attempt in range(retries):
        try:
            response = cf_requests.get(
                pubpeer_url,
                impersonate="chrome120",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True
            )
            
            # PubPeer returns 404 if no comments exist
            if response.status_code == 404:
                logger.info(f"✅ No PubPeer comments found for {doi} (clean)")
                result = {
                    'doi': doi,
                    'has_comments': False,
                    'comment_count': 0,
                    'pubpeer_url': pubpeer_url,
                    'comments': [],
                    'fraud_signals': {
                        'image_manipulation': False,
                        'data_inconsistency': False,
                        'statistical_issues': False,
                        'plagiarism': False
                    }
                }
                _save_to_cache(doi, result)
                return result
            
            if response.status_code != 200:
                logger.warning(f"HTTP {response.status_code}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return None
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract comments
            comments = _parse_pubpeer_comments(soup)
            
            # Analyze for fraud signals
            fraud_signals = _detect_fraud_signals(comments)
            
            result = {
                'doi': doi,
                'has_comments': len(comments) > 0,
                'comment_count': len(comments),
                'pubpeer_url': pubpeer_url,
                'comments': comments,
                'fraud_signals': fraud_signals
            }
            
            if result['has_comments']:
                logger.warning(f"⚠️ Found {len(comments)} PubPeer comments - FRAUD RISK!")
            else:
                logger.success(f"✅ No PubPeer comments (article appears clean)")
            
            # Cache result
            _save_to_cache(doi, result)
            
            return result
            
        except Exception as e:
            logger.warning(f"PubPeer scrape attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Failed to scrape PubPeer for {doi}")
                return None
    
    return None


def search_pubpeer_by_title(
    title: str,
    use_cache: bool = True,
    retries: int = MAX_RETRIES
) -> List[Dict]:
    """
    Search PubPeer by article title (fuzzy matching).
    
    Use this when DOI is not available.
    
    Args:
        title: Article title
        use_cache: Use cached results if available
        retries: Number of retry attempts
    
    Returns:
        List of matching articles with PubPeer data
    """
    logger.info(f"🔍 Searching PubPeer by title: '{title[:50]}...'")
    
    # Rate limiting
    time.sleep(RATE_LIMIT_DELAY)
    
    # PubPeer search URL
    search_url = f"{PUBPEER_BASE_URL}/search"
    params = {
        'q': title
    }
    
    for attempt in range(retries):
        try:
            response = cf_requests.get(
                search_url,
                params=params,
                impersonate="chrome120",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True
            )
            
            if response.status_code != 200:
                logger.warning(f"HTTP {response.status_code}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Parse search results
            results = _parse_pubpeer_search_results(soup)
            
            logger.success(f"✅ Found {len(results)} PubPeer entries")
            return results
            
        except Exception as e:
            logger.warning(f"Search attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    
    return []


def _parse_pubpeer_comments(soup: BeautifulSoup) -> List[Dict]:
    """Parse comments from PubPeer HTML."""
    comments = []
    
    # PubPeer comments are in <div class="comment"> elements
    comment_divs = soup.find_all('div', {'class': lambda x: x and 'comment' in x})
    
    for comment_div in comment_divs:
        try:
            # Extract comment text
            text_elem = comment_div.find('div', {'class': lambda x: x and 'text' in x})
            text = text_elem.get_text(strip=True) if text_elem else ""
            
            # Extract author (often "Anonymous")
            author_elem = comment_div.find('span', {'class': lambda x: x and 'author' in x})
            author = author_elem.get_text(strip=True) if author_elem else "Anonymous"
            
            # Extract date
            date_elem = comment_div.find('time')
            date = date_elem.get('datetime', 'Unknown') if date_elem else "Unknown"
            
            if text:  # Only add if comment has text
                comments.append({
                    'text': text,
                    'author': author,
                    'date': date
                })
        
        except Exception as e:
            logger.warning(f"Failed to parse comment: {e}")
            continue
    
    return comments


def _detect_fraud_signals(comments: List[Dict]) -> Dict[str, bool]:
    """
    Analyze comments for fraud indicators.
    
    Returns dict of boolean flags for different fraud types.
    """
    fraud_signals = {
        'image_manipulation': False,
        'data_inconsistency': False,
        'statistical_issues': False,
        'plagiarism': False
    }
    
    # Combine all comment text
    all_text = " ".join([c.get('text', '').lower() for c in comments])
    
    # Image manipulation keywords
    image_keywords = [
        'duplicate', 'duplication', 'clone', 'copy', 'paste',
        'photoshop', 'manipulat', 'altered', 'edited', 'western blot'
    ]
    if any(kw in all_text for kw in image_keywords):
        fraud_signals['image_manipulation'] = True
    
    # Data inconsistency keywords
    data_keywords = [
        'inconsisten', 'mismatch', 'error', 'discrepancy',
        'contradiction', 'doesn\'t match', 'wrong'
    ]
    if any(kw in all_text for kw in data_keywords):
        fraud_signals['data_inconsistency'] = True
    
    # Statistical issues keywords
    stats_keywords = [
        'statistic', 'p-value', 'impossible', 'improbable',
        'too good', 'unrealistic', 'fabricat'
    ]
    if any(kw in all_text for kw in stats_keywords):
        fraud_signals['statistical_issues'] = True
    
    # Plagiarism keywords
    plagiarism_keywords = [
        'plagiar', 'copied', 'stolen', 'reused', 'duplicate text'
    ]
    if any(kw in all_text for kw in plagiarism_keywords):
        fraud_signals['plagiarism'] = True
    
    # Check if any images are attached (strong fraud indicator)
    has_images = any(len(c.get('images', [])) > 0 for c in comments)
    if has_images:
        fraud_signals['image_manipulation'] = True  # Images usually show manipulation
    
    return fraud_signals


def _parse_pubpeer_search_results(soup: BeautifulSoup) -> List[Dict]:
    """Parse PubPeer search results page."""
    results = []
    
    # Search results are typically in <div class="result"> or similar
    result_divs = soup.find_all('div', {'class': lambda x: x and 'result' in x})
    
    for result_div in result_divs:
        try:
            title_elem = result_div.find('a')
            title = title_elem.get_text(strip=True) if title_elem else ""
            url = urljoin(PUBPEER_BASE_URL, title_elem.get('href', '')) if title_elem else ""
            
            # Extract DOI from URL if possible
            doi = ""
            if '/publications/' in url:
                doi = url.split('/publications/')[-1]
            
            results.append({
                'title': title,
                'doi': doi,
                'pubpeer_url': url
            })
        
        except Exception as e:
            logger.warning(f"Failed to parse search result: {e}")
            continue
    
    return results


def _load_from_cache(doi: str) -> Optional[Dict]:
    """Load cached PubPeer data."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        cache_key = hashlib.md5(doi.encode()).hexdigest()
        cache_file = CACHE_DIR / f"{cache_key}.json"
        
        if not cache_file.exists():
            return None
        
        # Check cache age
        file_age_days = (time.time() - cache_file.stat().st_mtime) / 86400
        if file_age_days > CACHE_EXPIRY_DAYS:
            logger.info(f"Cache expired ({file_age_days:.1f} days old)")
            return None
        
        with open(cache_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    except Exception as e:
        logger.warning(f"Failed to load cache: {e}")
        return None


def _save_to_cache(doi: str, data: Dict):
    """Save PubPeer data to cache."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        
        cache_key = hashlib.md5(doi.encode()).hexdigest()
        cache_file = CACHE_DIR / f"{cache_key}.json"
        
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        logger.info(f"💾 Cached to: {cache_file}")
    
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")


# ========== Example Usage ==========
if __name__ == "__main__":
    # Example 1: Check Simufilam paper (known fraud case)
    print("\n=== Example 1: Simufilam PubPeer Check ===")
    doi = "10.3233/JAD-220762"  # Simufilam efficacy paper
    
    result = search_pubpeer_by_doi(doi)
    
    if result and result['has_comments']:
        print(f"\n⚠️ FRAUD WARNING: {result['comment_count']} PubPeer comments found!")
        print(f"🔗 PubPeer URL: {result['pubpeer_url']}")
        
        print("\n🚩 Fraud Signals Detected:")
        for signal, detected in result['fraud_signals'].items():
            if detected:
                print(f"   ✅ {signal.replace('_', ' ').title()}")
        
        print("\n📝 Comments:")
        for i, comment in enumerate(result['comments'][:3], 1):  # Show first 3
            print(f"\n  {i}. {comment['author']} ({comment['date']})")
            print(f"     {comment['text'][:150]}...")
    else:
        print(f"\n✅ No PubPeer comments found (article appears clean)")
    
    # Example 2: Search by title
    print("\n\n=== Example 2: Title Search ===")
    results = search_pubpeer_by_title("CRISPR off-target effects")
    
    print(f"Found {len(results)} articles with PubPeer comments:")
    for r in results[:5]:
        print(f"  - {r['title'][:60]}...")
        print(f"    {r['pubpeer_url']}")
