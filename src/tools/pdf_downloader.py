"""
PDF Downloader - Bio-Short-Seller NCBI PMC PDF Retrieval Tool

🔐 STEALTH MODE: TLS Fingerprinting Bypass Edition
Uses curl_cffi to impersonate Chrome 120 at the TLS layer.
This bypasses NCBI/PubMed's WAF and JA3 fingerprinting detection.

Robust PDF downloader with anti-bot detection features for PubMed Central.
Uses Europe PMC as primary source (more reliable) with NCBI as fallback.

Key Function:
- download_pdf_from_url: Download PDF from URL and return local path

Critical Dependencies:
- curl_cffi: Browser impersonation at TLS layer (not just User-Agent)
- beautifulsoup4: HTML parsing to extract PDF links
- loguru: Structured logging

Why curl_cffi?
Standard `requests` library fails with 403 because NCBI detects Python's TLS handshake.
curl_cffi mimics Chrome's exact TLS fingerprint, making our requests indistinguishable from a real browser.

Strategy:
1. Extract PMC ID from URL
2. Try Europe PMC first (direct PDF download, no JavaScript)
3. Fallback to NCBI if Europe PMC fails
"""

import os
import hashlib
import time
from pathlib import Path
from loguru import logger
from urllib.parse import urlparse, urljoin

# 🔥 CRITICAL IMPORTS
from curl_cffi import requests
from bs4 import BeautifulSoup


def download_pdf_from_url(url: str, output_dir: str = "downloads") -> str:
    """
    🔐 Stealth PDF Downloader with TLS Fingerprinting Bypass
    
    Downloads PDF from PMC article URLs using browser impersonation.
    
    Strategy:
    1. Extract PMC ID from URL
    2. Try Europe PMC first (direct PDF, no JavaScript redirects)
    3. Fallback to NCBI HTML parsing if Europe PMC fails
    
    Args:
        url: PMC article URL (landing page or direct PDF link)
        output_dir: Directory to save PDFs (default: 'downloads')
        
    Returns:
        Absolute path to downloaded PDF file, or None if download fails
        
    Example:
        >>> path = download_pdf_from_url("https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8675309/")
        >>> print(path)
        downloads/PMC8675309_a1b2c3d4.pdf
        
    Key Features:
        - TLS Fingerprinting Bypass via curl_cffi impersonation
        - Europe PMC as primary source (more reliable)
        - PDF Magic Bytes Validation (%PDF signature)
        - Exponential backoff retry on 403/timeout
        - MD5-based filename caching
    """
    try:
        # 1. Setup paths
        save_dir = Path(output_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

        # 2. Extract PMC ID
        parsed_url = urlparse(url)
        path_parts = parsed_url.path.strip("/").split("/")
        
        pmc_id = "unknown"
        for part in path_parts:
            if part.startswith("PMC"):
                pmc_id = part
                break
        
        if pmc_id == "unknown":
            logger.warning(f"❌ Could not extract PMC ID from URL: {url}")
            return None
        
        logger.info(f"📄 Target: {pmc_id}")

        # Generate safe filename with MD5 hash
        url_hash = hashlib.md5(url.encode()).hexdigest()
        filename = f"{pmc_id}_{url_hash[:8]}.pdf"
        file_path = save_dir / filename

        # 3. Check Cache
        if file_path.exists() and file_path.stat().st_size > 5000:  # >5KB
            logger.info(f"⚡ PDF cached: {file_path}")
            return str(file_path.absolute())

        # 4. Method 1: Try Europe PMC (Primary - Most Reliable)
        europe_pmc_url = f"https://europepmc.org/articles/{pmc_id}?pdf=render"
        logger.info(f"🌍 Method 1: Trying Europe PMC...")
        logger.info(f"   URL: {europe_pmc_url}")
        
        max_retries = 3
        backoff_delay = 2
        
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    europe_pmc_url,
                    impersonate="chrome120",
                    timeout=30,
                    allow_redirects=True
                )
                
                if response.status_code == 200:
                    content = response.content
                    
                    # Validate PDF magic bytes
                    if len(content) >= 4 and content[:4] == b'%PDF':
                        with open(file_path, 'wb') as f:
                            f.write(content)
                        
                        file_size = file_path.stat().st_size
                        
                        if file_size < 1000:
                            logger.warning(f"⚠️ File too small ({file_size} bytes)")
                            file_path.unlink()
                            break  # Try Method 2
                        
                        logger.success(f"✅ Europe PMC Success: {file_path} ({file_size / 1024:.1f} KB)")
                        return str(file_path.absolute())
                    else:
                        logger.warning("⚠️ Europe PMC returned non-PDF content")
                        break  # Try Method 2
                        
                elif response.status_code == 404:
                    logger.warning("❌ Europe PMC: Article not found")
                    break  # Try Method 2
                    
                elif response.status_code == 403:
                    logger.warning(f"🚫 Europe PMC 403 (attempt {attempt + 1}/{max_retries})")
                    if attempt < max_retries - 1:
                        time.sleep(backoff_delay * (2 ** attempt))
                        continue
                    break  # Try Method 2
                else:
                    logger.warning(f"❌ Europe PMC HTTP {response.status_code}")
                    break  # Try Method 2
                    
            except Exception as e:
                logger.warning(f"❌ Europe PMC error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(backoff_delay * (2 ** attempt))
                    continue
                break  # Try Method 2
        
        # 5. Method 2: Fallback to NCBI (with HTML parsing)
        logger.info(f"🔄 Method 2: Trying NCBI...")
        
        session = requests.Session()
        landing_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/"
        
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
        
        for attempt in range(max_retries):
            try:
                # Visit landing page
                logger.info(f"   Visiting landing page (attempt {attempt + 1}/{max_retries})...")
                landing_response = session.get(
                    landing_url,
                    headers=headers,
                    impersonate="chrome120",
                    timeout=15,
                    allow_redirects=True
                )
                
                if landing_response.status_code != 200:
                    logger.warning(f"   Landing page: HTTP {landing_response.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(backoff_delay * (2 ** attempt))
                        continue
                    return None
                
                # Parse HTML to find PDF link
                soup = BeautifulSoup(landing_response.text, 'html.parser')
                
                # 🎯 Smart PDF link selection: prioritize main article PDF over supplementary materials
                pdf_link = None
                
                # Priority 1: Look for link with text containing "PDF" (main article)
                for link in soup.find_all('a', href=lambda x: x and '.pdf' in x.lower()):
                    link_text = link.get_text(strip=True).lower()
                    href = link.get('href', '')
                    
                    # Skip supplementary materials
                    if any(skip in href.lower() for skip in ['supplement', 'supp', '/bin/', 's001', 's002']):
                        continue
                    
                    # Prefer links with "pdf" in text
                    if 'pdf' in link_text:
                        pdf_link = link
                        break
                
                # Priority 2: If no main PDF found, try any non-supplementary PDF
                if not pdf_link:
                    for link in soup.find_all('a', href=lambda x: x and '.pdf' in x.lower()):
                        href = link.get('href', '')
                        if not any(skip in href.lower() for skip in ['supplement', 'supp', '/bin/', 's001', 's002']):
                            pdf_link = link
                            break
                
                # Priority 3: Last resort - standard PMC PDF path
                if not pdf_link:
                    # Try constructing standard PMC PDF URL
                    standard_pdf_url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmc_id}/pdf/"
                    logger.info(f"   No PDF link in HTML, trying standard path: {standard_pdf_url}")
                    pdf_url = standard_pdf_url
                else:
                    relative_pdf_path = pdf_link.get('href')
                    pdf_url = urljoin(landing_url, relative_pdf_path)
                    
                    # 🛡️ Validate: Only accept PMC article links
                    if '/pmc/articles/' not in pdf_url.lower():
                        logger.warning(f"   ⚠️ PDF link is not a PMC article: {pdf_url}")
                        logger.info(f"   💡 This may be a non-PMC article. Skipping Method 2.")
                        return None
                    
                    logger.info(f"   Found PDF link: {pdf_url}")
                
                if not pdf_url:
                    logger.warning("   No PDF link found (HTML-only article)")
                    return None
                
                time.sleep(0.5)
                
                # Download PDF
                pdf_headers = headers.copy()
                pdf_headers["Accept"] = "application/pdf,*/*"
                pdf_headers["Referer"] = landing_url
                
                pdf_response = session.get(
                    pdf_url,
                    headers=pdf_headers,
                    impersonate="chrome120",
                    timeout=30,
                    allow_redirects=True
                )
                
                if pdf_response.status_code == 200:
                    content = pdf_response.content
                    
                    if len(content) >= 4 and content[:4] == b'%PDF':
                        with open(file_path, 'wb') as f:
                            f.write(content)
                        
                        file_size = file_path.stat().st_size
                        
                        if file_size < 1000:
                            logger.warning(f"⚠️ File too small ({file_size} bytes)")
                            file_path.unlink()
                            return None
                        
                        logger.success(f"✅ NCBI Success: {file_path} ({file_size / 1024:.1f} KB)")
                        return str(file_path.absolute())
                    else:
                        logger.warning("⚠️ NCBI returned non-PDF content")
                        return None
                else:
                    logger.warning(f"   PDF download: HTTP {pdf_response.status_code}")
                    if attempt < max_retries - 1:
                        time.sleep(backoff_delay * (2 ** attempt))
                        continue
                    return None
                    
            except Exception as e:
                logger.warning(f"   NCBI error (attempt {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(backoff_delay * (2 ** attempt))
                    continue
                return None
        
        logger.error(f"❌ All methods failed for {pmc_id}")
        return None

    except Exception as e:
        logger.error(f"❌ Download Exception: {e}")
        import traceback
        traceback.print_exc()
        return None
