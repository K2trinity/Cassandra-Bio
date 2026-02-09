"""
Cassandra - API Resilience Layer
Retry mechanism for biomedical data retrieval and LLM API calls.
Provides exponential backoff with configurable retry policies for robust system operation.
"""

import time
from functools import wraps
from typing import Callable, Any
import requests
from loguru import logger


class RetryConfig:
    """
    Retry configuration for network operations and API calls.
    Supports exponential backoff with maximum delay caps.
    """
    
    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        max_delay: float = 60.0,
        retry_on_exceptions: tuple = None
    ):
        """
        Initialize retry configuration.
        
        Args:
            max_retries: Maximum number of retry attempts before failure
            initial_delay: Initial delay in seconds before first retry
            backoff_factor: Exponential backoff multiplier (delay doubles each retry)
            max_delay: Maximum delay cap in seconds to prevent excessive waiting
            retry_on_exceptions: Tuple of exception types that trigger retry logic
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.max_delay = max_delay
        
        # Default retryable exception types
        if retry_on_exceptions is None:
            self.retry_on_exceptions = (
                requests.exceptions.RequestException,
                requests.exceptions.ConnectionError,
                requests.exceptions.HTTPError,
                requests.exceptions.Timeout,
                requests.exceptions.TooManyRedirects,
                ConnectionError,
                TimeoutError,
                Exception  # Catch-all for LLM API errors (OpenAI, Google Gemini, etc.)
            )
        else:
            self.retry_on_exceptions = retry_on_exceptions

# Default configuration
DEFAULT_RETRY_CONFIG = RetryConfig()


def with_retry(config: RetryConfig = None):
    """
    Retry decorator with exponential backoff.
    
    Args:
        config: Retry configuration. Uses DEFAULT_RETRY_CONFIG if not provided.
    
    Returns:
        Decorator function that wraps target function with retry logic.
    """
    if config is None:
        config = DEFAULT_RETRY_CONFIG
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(config.max_retries + 1):  # +1 because first call is not a retry
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(f"Function {func.__name__} succeeded after {attempt + 1} attempts")
                    return result
                    
                except config.retry_on_exceptions as e:
                    last_exception = e
                    
                    if attempt == config.max_retries:
                        # Final attempt also failed
                        logger.error(f"Function {func.__name__} failed after {config.max_retries + 1} attempts")
                        logger.error(f"Final error: {str(e)}")
                        raise e
                    
                    # Calculate exponential backoff delay
                    delay = min(
                        config.initial_delay * (config.backoff_factor ** attempt),
                        config.max_delay
                    )
                    
                    logger.warning(f"Function {func.__name__} attempt {attempt + 1} failed: {str(e)}")
                    logger.info(f"Retrying in {delay:.1f} seconds (attempt {attempt + 2})...")
                    
                    time.sleep(delay)
                
                except Exception as e:
                    # Non-retryable exception - raise immediately
                    logger.error(f"Function {func.__name__} encountered non-retryable exception: {str(e)}")
                    raise e
            
            # Safety net - should never reach here
            if last_exception:
                raise last_exception
            
        return wrapper
    return decorator


def retry_on_network_error(
    max_retries: int = 3,
    initial_delay: float = 1.0,
    backoff_factor: float = 2.0
):
    """
    Simplified retry decorator specifically for network errors.
    
    Args:
        max_retries: Maximum retry attempts
        initial_delay: Initial delay in seconds
        backoff_factor: Exponential backoff multiplier
    
    Returns:
        Decorator function with pre-configured retry policy
    """
    config = RetryConfig(
        max_retries=max_retries,
        initial_delay=initial_delay,
        backoff_factor=backoff_factor
    )
    return with_retry(config)


class RetryableError(Exception):
    """Custom exception for operations that should trigger retry logic."""
    pass


def with_graceful_retry(config: RetryConfig = None, default_return=None):
    """
    Graceful retry decorator for non-critical API calls.
    Returns a default value instead of raising exceptions, ensuring system continuity.
    
    Args:
        config: Retry configuration. Uses SEARCH_API_RETRY_CONFIG if not provided.
        default_return: Default value to return if all retries fail
    
    Returns:
        Decorator function that returns default_return on failure instead of raising
    """
    if config is None:
        config = SEARCH_API_RETRY_CONFIG
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            last_exception = None
            
            for attempt in range(config.max_retries + 1):  # +1 because first call is not a retry
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        logger.info(f"Non-critical API {func.__name__} succeeded after {attempt + 1} attempts")
                    return result
                    
                except config.retry_on_exceptions as e:
                    last_exception = e
                    
                    if attempt == config.max_retries:
                        # Final attempt failed - return default value instead of raising
                        logger.warning(f"Non-critical API {func.__name__} failed after {config.max_retries + 1} attempts")
                        logger.warning(f"Final error: {str(e)}")
                        logger.info(f"Returning default value to maintain system operation: {default_return}")
                        return default_return
                    
                    # Calculate exponential backoff delay
                    delay = min(
                        config.initial_delay * (config.backoff_factor ** attempt),
                        config.max_delay
                    )
                    
                    logger.warning(f"Non-critical API {func.__name__} attempt {attempt + 1} failed: {str(e)}")
                    logger.info(f"Retrying in {delay:.1f} seconds (attempt {attempt + 2})...")
                    
                    time.sleep(delay)
                
                except Exception as e:
                    # Non-retryable exception - return default value
                    logger.warning(f"Non-critical API {func.__name__} encountered non-retryable exception: {str(e)}")
                    logger.info(f"Returning default value to maintain system operation: {default_return}")
                    return default_return
            
            # Safety net - should never reach here
            return default_return
            
        return wrapper
    return decorator


def make_retryable_request(
    request_func: Callable,
    *args,
    max_retries: int = 5,
    **kwargs
) -> Any:
    """
    Execute a retryable request without using decorator syntax.
    Useful for dynamic retry logic.
    
    Args:
        request_func: Function to execute with retry protection
        *args: Positional arguments to pass to request_func
        max_retries: Maximum retry attempts
        **kwargs: Keyword arguments to pass to request_func
    
    Returns:
        Result of request_func execution
    """
    config = RetryConfig(max_retries=max_retries)
    
    @with_retry(config)
    def _execute():
        return request_func(*args, **kwargs)
    
    return _execute()


# ============================================================================
# Pre-configured Retry Policies for Different Components
# ============================================================================

# LLM API Retry Configuration (Google Gemini, OpenAI, etc.)
LLM_RETRY_CONFIG = RetryConfig(
    max_retries=6,        # Extended retries for expensive LLM calls
    initial_delay=60.0,   # Wait at least 1 minute on first retry (rate limit recovery)
    backoff_factor=2.0,   # Exponential backoff
    max_delay=600.0       # Cap at 10 minutes per retry
)

# Search API Retry Configuration (PubMed, ClinicalTrials.gov, Tavily)
SEARCH_API_RETRY_CONFIG = RetryConfig(
    max_retries=5,        # Moderate retry count for search APIs
    initial_delay=2.0,    # Quick first retry for transient network errors
    backoff_factor=1.6,   # Moderate backoff
    max_delay=25.0        # Cap at 25 seconds
)

# Database Retry Configuration (Neo4j, Redis)
DB_RETRY_CONFIG = RetryConfig(
    max_retries=5,        # Multiple retries for database operations
    initial_delay=1.0,    # Fast retry for local database connections
    backoff_factor=1.5,   # Gentle backoff
    max_delay=10.0        # Cap at 10 seconds
)

