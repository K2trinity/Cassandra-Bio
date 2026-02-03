"""
Quick diagnostic script to test Gemini API connection and search functionality
"""

import os
import sys

# Simple logger replacement
class SimpleLogger:
    def info(self, msg): print(f"ℹ️  {msg}")
    def success(self, msg): print(f"✅ {msg}")
    def warning(self, msg): print(f"⚠️  {msg}")
    def error(self, msg): print(f"❌ {msg}")

logger = SimpleLogger()

def test_gemini_connection():
    """Test basic Gemini API connectivity"""
    logger.info("🔍 Testing Gemini API Connection...")
    
    try:
        from src.llms import create_harvest_client
        
        client = create_harvest_client()
        logger.success("✅ Gemini client initialized")
        
        # Test simple generation
        response = client.generate_content("Say 'Hello'")
        logger.success(f"✅ API Response: {response[:50]}...")
        
        return True
    except Exception as e:
        logger.error(f"❌ Gemini connection failed: {e}")
        return False

def test_europmc_search():
    """Test EuroPMC search with better queries"""
    logger.info("🔍 Testing EuroPMC Search...")
    
    try:
        from src.tools.search_tools import search_europmc
        
        # Try a simpler, more common query
        test_queries = [
            "CRISPR off-target",
            "CRISPR clinical trial",
            "CRISPR genome editing safety"
        ]
        
        for query in test_queries:
            results = search_europmc(query, max_results=5)
            logger.info(f"Query: '{query}' → Found {len(results)} papers")
            
            if len(results) > 0:
                logger.success(f"✅ Sample result: {results[0].get('title', 'No title')[:80]}...")
                return True
        
        logger.warning("⚠️ No results found for any test query")
        return False
        
    except Exception as e:
        logger.error(f"❌ EuroPMC search failed: {e}")
        return False

def check_api_key():
    """Check if API key is properly configured"""
    logger.info("🔍 Checking API Key Configuration...")
    
    try:
        from config import settings
        
        if settings.GOOGLE_API_KEY:
            masked_key = settings.GOOGLE_API_KEY[:8] + "..." + settings.GOOGLE_API_KEY[-4:]
            logger.success(f"✅ API Key found: {masked_key}")
            return True
        else:
            logger.error("❌ API Key not configured")
            logger.info("💡 Set GOOGLE_API_KEY in .env file")
            return False
            
    except Exception as e:
        logger.error(f"❌ Config check failed: {e}")
        return False

def main():
    logger.info("=" * 60)
    logger.info("🔧 CASSANDRA CONNECTION DIAGNOSTICS")
    logger.info("=" * 60)
    
    results = {
        "API Key": check_api_key(),
        "Gemini Connection": test_gemini_connection(),
        "EuroPMC Search": test_europmc_search()
    }
    
    logger.info("\n" + "=" * 60)
    logger.info("📊 DIAGNOSTIC RESULTS")
    logger.info("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        logger.info(f"{status} - {test_name}")
    
    if all(results.values()):
        logger.success("\n✅ ALL SYSTEMS OPERATIONAL")
        logger.info("💡 The SSL error was likely temporary. Try running main.py again.")
    else:
        logger.error("\n❌ ISSUES DETECTED")
        logger.info("💡 Check the errors above and fix before running main.py")

if __name__ == "__main__":
    main()
