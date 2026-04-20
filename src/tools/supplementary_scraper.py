"""
Supplementary Materials Scraper - Cassandra Research Data Extractor

This module scrapes supplementary materials from major publishers' websites.
Supplementary files often contain the raw data, high-resolution figures, and
statistical code that can reveal fraud - and they're usually FREE even when
the main article is paywalled.

Key Functions:
- find_supplementary_materials: Extract all supplementary file links from article page
- download_supplementary_files: Download specific supplement files
- extract_figures_from_supplements: Find image files in supplements

Supported Publishers:
- Nature/Springer
- Science/AAAS
- Elsevier/Cell Press
- Wiley
- PLOS (fully open access)
"""

import requests
import time
from typing import List, Dict, Optional
from loguru import logger
from urllib.parse import urljoin, urlparse
from pathlib import Path
import hashlib

try:
    from curl_cffi import requests as cf_requests
    from bs4 import BeautifulSoup
except ImportError:
    logger.error("Required packages missing. Run: pip install curl_cffi beautifulsoup4")
    raise


# ========== Configuration ==========
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0"


def find_supplementary_materials(
    article_url: str,
    retries: int = MAX_RETRIES
) -> List[Dict[str, str]]:
    """
    🔥 Extract all supplementary material links from article page.
    
    This function scrapes the article landing page and extracts links to:
    - Supplementary PDFs
    - Supplementary figures (high-res images)
    - Data files (Excel, CSV, ZIP)
    - Statistical code and analysis scripts
    
    These materials are often freely accessible even when the main article
    is behind a paywall.
    
    Args:
        article_url: URL to article landing page (not PDF)
        retries: Number of retry attempts
    
    Returns:
        List of dictionaries containing:
        - title: Supplement file title/description
        - url: Direct download URL
        - file_type: File extension (pdf, xlsx, zip, jpg, etc.)
        - size: File size if available
        - category: "figure", "data", "code", "document", or "other"
    
    Example:
        >>> supplements = find_supplementary_materials(
        ...     "https://www.nature.com/articles/s41586-020-2649-2"
        ... )
        >>> for supp in supplements:
        ...     print(f"{supp['title']}: {supp['url']}")
    """
    logger.info(f"🔍 Searching for supplementary materials: {article_url}")
    
    # Detect publisher
    domain = urlparse(article_url).netloc.lower()
    
    if "nature.com" in domain or "springer.com" in domain:
        return _scrape_nature_springer_supplements(article_url, retries)
    elif "science.org" in domain or "sciencemag.org" in domain:
        return _scrape_science_supplements(article_url, retries)
    elif "sciencedirect.com" in domain or "cell.com" in domain:
        return _scrape_elsevier_supplements(article_url, retries)
    elif "wiley.com" in domain or "onlinelibrary.wiley.com" in domain:
        return _scrape_wiley_supplements(article_url, retries)
    elif "plos.org" in domain:
        return _scrape_plos_supplements(article_url, retries)
    else:
        logger.warning(f"⚠️ Publisher not supported for: {domain}")
        return _scrape_generic_supplements(article_url, retries)


def _scrape_nature_springer_supplements(url: str, retries: int) -> List[Dict[str, str]]:
    """Scrape supplements from Nature/Springer articles."""
    logger.info("📰 Scraping Nature/Springer supplements...")
    
    supplements = []
    
    for attempt in range(retries):
        try:
            response = cf_requests.get(
                url,
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
            
            # Method 1: Look for supplementary information section
            supp_section = soup.find('section', {'data-title': 'Supplementary information'})
            if not supp_section:
                supp_section = soup.find('div', {'id': 'supplementary-information'})
            
            if supp_section:
                links = supp_section.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    
                    # Filter out navigation links
                    if not href or href.startswith('#'):
                        continue
                    
                    # Build absolute URL
                    full_url = urljoin(url, href)
                    
                    # Determine file type
                    file_type = _extract_file_type(full_url)
                    category = _categorize_supplement(text, file_type)
                    
                    supplements.append({
                        'title': text or 'Supplementary Material',
                        'url': full_url,
                        'file_type': file_type,
                        'size': 'Unknown',
                        'category': category
                    })
            
            # Method 2: Look for "Download" buttons/links
            download_links = soup.find_all('a', string=lambda s: s and 'download' in s.lower())
            for link in download_links:
                href = link.get('href', '')
                if href and ('supplement' in href.lower() or 'suppl' in href.lower()):
                    full_url = urljoin(url, href)
                    text = link.get_text(strip=True)
                    file_type = _extract_file_type(full_url)
                    
                    # Avoid duplicates
                    if not any(s['url'] == full_url for s in supplements):
                        supplements.append({
                            'title': text,
                            'url': full_url,
                            'file_type': file_type,
                            'size': 'Unknown',
                            'category': _categorize_supplement(text, file_type)
                        })
            
            logger.success(f"✅ Found {len(supplements)} Nature/Springer supplements")
            return supplements
            
        except Exception as e:
            logger.warning(f"Scrape attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
            else:
                logger.error(f"Failed to scrape Nature/Springer supplements")
                return []
    
    return []


def _scrape_science_supplements(url: str, retries: int) -> List[Dict[str, str]]:
    """Scrape supplements from Science/AAAS articles."""
    logger.info("🔬 Scraping Science supplements...")
    
    supplements = []
    
    for attempt in range(retries):
        try:
            response = cf_requests.get(
                url,
                impersonate="chrome120",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True
            )
            
            if response.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Science typically has a "Data/Materials" or "Supplementary Materials" section
            supp_section = soup.find('section', {'aria-labelledby': lambda x: x and 'supplementary' in x.lower()})
            
            if supp_section:
                links = supp_section.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    
                    if not href or href.startswith('#'):
                        continue
                    
                    full_url = urljoin(url, href)
                    file_type = _extract_file_type(full_url)
                    
                    supplements.append({
                        'title': text or 'Supplementary Material',
                        'url': full_url,
                        'file_type': file_type,
                        'size': 'Unknown',
                        'category': _categorize_supplement(text, file_type)
                    })
            
            logger.success(f"✅ Found {len(supplements)} Science supplements")
            return supplements
            
        except Exception as e:
            logger.warning(f"Scrape attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    
    return []


def _scrape_elsevier_supplements(url: str, retries: int) -> List[Dict[str, str]]:
    """Scrape supplements from Elsevier/ScienceDirect articles."""
    logger.info("📚 Scraping Elsevier supplements...")
    
    supplements = []
    
    for attempt in range(retries):
        try:
            response = cf_requests.get(
                url,
                impersonate="chrome120",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True
            )
            
            if response.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Elsevier uses specific class names for attachments
            attachment_links = soup.find_all('a', {'class': lambda x: x and 'attachment' in x.lower()})
            
            for link in attachment_links:
                href = link.get('href', '')
                text = link.get_text(strip=True)
                
                if not href:
                    continue
                
                full_url = urljoin(url, href)
                file_type = _extract_file_type(full_url)
                
                supplements.append({
                    'title': text or 'Supplementary Material',
                    'url': full_url,
                    'file_type': file_type,
                    'size': 'Unknown',
                    'category': _categorize_supplement(text, file_type)
                })
            
            logger.success(f"✅ Found {len(supplements)} Elsevier supplements")
            return supplements
            
        except Exception as e:
            logger.warning(f"Scrape attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    
    return []


def _scrape_wiley_supplements(url: str, retries: int) -> List[Dict[str, str]]:
    """Scrape supplements from Wiley articles."""
    logger.info("📖 Scraping Wiley supplements...")
    
    return _scrape_generic_supplements(url, retries)


def _scrape_plos_supplements(url: str, retries: int) -> List[Dict[str, str]]:
    """Scrape supplements from PLOS articles (fully open access)."""
    logger.info("🔓 Scraping PLOS supplements...")
    
    supplements = []
    
    for attempt in range(retries):
        try:
            response = cf_requests.get(
                url,
                impersonate="chrome120",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True
            )
            
            if response.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # PLOS has a "Supporting Information" section
            supp_section = soup.find('div', {'id': 'supporting-information'})
            
            if supp_section:
                links = supp_section.find_all('a', href=True)
                
                for link in links:
                    href = link.get('href', '')
                    text = link.get_text(strip=True)
                    
                    if not href or href.startswith('#'):
                        continue
                    
                    full_url = urljoin(url, href)
                    file_type = _extract_file_type(full_url)
                    
                    supplements.append({
                        'title': text or 'Supporting Information',
                        'url': full_url,
                        'file_type': file_type,
                        'size': 'Unknown',
                        'category': _categorize_supplement(text, file_type)
                    })
            
            logger.success(f"✅ Found {len(supplements)} PLOS supplements")
            return supplements
            
        except Exception as e:
            logger.warning(f"Scrape attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    
    return []


def _scrape_generic_supplements(url: str, retries: int) -> List[Dict[str, str]]:
    """Generic supplement scraper for unsupported publishers."""
    logger.info("🔍 Using generic supplement scraper...")
    
    supplements = []
    
    for attempt in range(retries):
        try:
            response = cf_requests.get(
                url,
                impersonate="chrome120",
                timeout=DEFAULT_TIMEOUT,
                allow_redirects=True
            )
            
            if response.status_code != 200:
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                    continue
                return []
            
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Look for common supplement keywords
            keywords = ['supplement', 'supporting', 'additional', 'suppl']
            
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                text = link.get_text(strip=True).lower()
                
                # Check if link contains supplement keywords
                if any(kw in text or kw in href.lower() for kw in keywords):
                    full_url = urljoin(url, href)
                    file_type = _extract_file_type(full_url)
                    
                    # Only include actual file downloads
                    if file_type != 'html':
                        supplements.append({
                            'title': link.get_text(strip=True) or 'Supplementary Material',
                            'url': full_url,
                            'file_type': file_type,
                            'size': 'Unknown',
                            'category': _categorize_supplement(text, file_type)
                        })
            
            logger.success(f"✅ Found {len(supplements)} supplements (generic scraper)")
            return supplements
            
        except Exception as e:
            logger.warning(f"Scrape attempt {attempt + 1}/{retries} failed: {e}")
            if attempt < retries - 1:
                time.sleep(2 ** attempt)
    
    return []


def _extract_file_type(url: str) -> str:
    """Extract file extension from URL."""
    path = urlparse(url).path.lower()
    
    if '.pdf' in path:
        return 'pdf'
    elif '.xlsx' in path or '.xls' in path:
        return 'xlsx'
    elif '.csv' in path:
        return 'csv'
    elif '.zip' in path:
        return 'zip'
    elif '.jpg' in path or '.jpeg' in path:
        return 'jpg'
    elif '.png' in path:
        return 'png'
    elif '.tif' in path or '.tiff' in path:
        return 'tiff'
    elif '.docx' in path or '.doc' in path:
        return 'docx'
    elif '.txt' in path:
        return 'txt'
    elif '.r' in path:
        return 'r'
    elif '.py' in path:
        return 'python'
    else:
        return 'html'


def _categorize_supplement(title: str, file_type: str) -> str:
    """Categorize supplement based on title and file type."""
    title_lower = title.lower()
    
    # Image files
    if file_type in ['jpg', 'png', 'tiff'] or 'figure' in title_lower or 'image' in title_lower:
        return 'figure'
    
    # Data files
    if file_type in ['xlsx', 'csv', 'zip'] or 'data' in title_lower or 'table' in title_lower:
        return 'data'
    
    # Code files
    if file_type in ['r', 'python'] or 'code' in title_lower or 'script' in title_lower:
        return 'code'
    
    # Documents
    if file_type in ['pdf', 'docx'] or 'text' in title_lower or 'methods' in title_lower:
        return 'document'
    
    return 'other'


def download_supplementary_file(
    file_url: str,
    output_dir: str = "downloads/supplements",
    filename: str = None
) -> Optional[str]:
    """
    Download a supplementary file.
    
    Args:
        file_url: Direct URL to supplement file
        output_dir: Directory to save file
        filename: Custom filename (optional, will generate from URL if not provided)
    
    Returns:
        Path to downloaded file, or None if download fails
    """
    try:
        save_dir = Path(output_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        
        if not filename:
            # Generate filename from URL
            url_hash = hashlib.md5(file_url.encode()).hexdigest()[:8]
            file_ext = _extract_file_type(file_url)
            filename = f"supplement_{url_hash}.{file_ext}"
        
        file_path = save_dir / filename
        
        # Check cache
        if file_path.exists() and file_path.stat().st_size > 100:
            logger.info(f"⚡ File cached: {file_path}")
            return str(file_path.absolute())
        
        logger.info(f"📥 Downloading: {file_url}")
        
        response = cf_requests.get(
            file_url,
            impersonate="chrome120",
            timeout=60,
            allow_redirects=True
        )
        
        if response.status_code == 200:
            with open(file_path, 'wb') as f:
                f.write(response.content)
            
            file_size = file_path.stat().st_size
            logger.success(f"✅ Downloaded: {file_path} ({file_size / 1024:.1f} KB)")
            return str(file_path.absolute())
        else:
            logger.warning(f"❌ Download failed: HTTP {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ Download exception: {e}")
        return None


# ========== Example Usage ==========
if __name__ == "__main__":
    # Example: Extract supplements from Nature article
    print("\n=== Example: Nature Article Supplements ===")
    
    article_url = "https://www.nature.com/articles/s41586-020-2649-2"
    supplements = find_supplementary_materials(article_url)
    
    print(f"\nFound {len(supplements)} supplementary files:")
    for supp in supplements:
        print(f"\n📎 {supp['title']}")
        print(f"   Type: {supp['file_type']} | Category: {supp['category']}")
        print(f"   URL: {supp['url']}")
    
    # Download first supplement if available
    if supplements:
        print("\n=== Downloading First Supplement ===")
        first_supp = supplements[0]
        path = download_supplementary_file(first_supp['url'])
        if path:
            print(f"✅ Saved to: {path}")
