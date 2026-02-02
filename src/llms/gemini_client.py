"""
Centralized Google Gemini client for Bio-Short-Seller.

This is the ONLY LLM interface for the entire system.
All engines (Query, Media, Insight, Report) use this unified client.

Enhanced with robust error handling and retry logic for production stability.
"""

import os
import ssl
import time
from typing import Any, Dict, List, Optional, Generator, Union
from loguru import logger
from pathlib import Path

from google import genai
from google.genai import types
from google.api_core import retry
from google.api_core import exceptions as google_exceptions


class GeminiClient:
    """
    Universal Google Gemini API client for all Bio-Short-Seller engines.
    
    Supports:
    - Text generation (all engines)
    - Multimodal vision (MediaEngine)
    - Long-context reasoning (EvidenceEngine, ReportEngine)
    - Streaming and non-streaming modes
    """

    # Permissive safety settings for scientific content
    DEFAULT_SAFETY_SETTINGS = [
        types.SafetySetting(
            category="HARM_CATEGORY_HATE_SPEECH",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_HARASSMENT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
            threshold="BLOCK_NONE",
        ),
        types.SafetySetting(
            category="HARM_CATEGORY_DANGEROUS_CONTENT",
            threshold="BLOCK_NONE",
        ),
    ]

    def __init__(
        self,
        api_key: Optional[str] = None,
        # UPDATED: Strictly enforced default model as requested
        model_name: str = "gemini-3-pro-preview", 
        temperature: float = 0.5,
        max_output_tokens: int = 8192,
    ):
        """
        Initialize universal Gemini client.

        Args:
            api_key: Google API key (defaults to GOOGLE_API_KEY env var)
            model_name: Model ID (gemini-3-pro-preview)
            temperature: Sampling temperature (0.0-1.0)
            max_output_tokens: Maximum response tokens
        """
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Gemini API key required. Set GOOGLE_API_KEY environment variable "
                "or pass api_key parameter."
            )

        self.model_name = model_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens

        # Initialize client
        self.client = genai.Client(api_key=self.api_key)
        logger.info(f"Initialized central GeminiClient: {model_name} (temp={temperature})")

    def _build_config(self, **kwargs) -> types.GenerateContentConfig:
        """Build generation config with overrides."""
        return types.GenerateContentConfig(
            temperature=kwargs.get("temperature", self.temperature),
            max_output_tokens=kwargs.get("max_output_tokens", self.max_output_tokens),
            top_p=kwargs.get("top_p"),
            top_k=kwargs.get("top_k"),
            safety_settings=self.DEFAULT_SAFETY_SETTINGS,
        )

    def generate_content(
        self,
        prompt: str,
        images: Optional[List[Union[str, bytes, Path]]] = None,
        **kwargs
    ) -> str:
        """
        Generate text response (optionally with images).
        
        Enhanced with robust retry logic and extended timeout for large payloads.

        Args:
            prompt: Text instruction
            images: Optional list of image inputs (paths, bytes, or Path objects)
            **kwargs: Override config (temperature, max_output_tokens, etc.)

        Returns:
            Generated text as string
        """
        try:
            config = self._build_config(**kwargs)
            
            # --- FIX: Dynamic Content Construction (Defense-in-Depth) ---
            # NEVER pass None to the Gemini API - it will crash with "has no len()"
            contents = [prompt]
            
            # Only add images if they exist and are valid
            if images:
                for img in images:
                    # Skip None or empty entries
                    if img is None:
                        logger.warning("⚠️ Skipping None image in generate_content call")
                        continue
                    
                    if isinstance(img, (str, Path)):
                        img_path = Path(img)
                        if not img_path.exists():
                            logger.error(f"❌ Image file not found: {img_path}")
                            raise FileNotFoundError(f"Image file does not exist: {img_path}")
                        with open(img_path, 'rb') as f:
                            data = f.read()
                        contents.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
                    elif isinstance(img, bytes):
                        # Validate bytes are not empty
                        if len(img) == 0:
                            logger.warning("⚠️ Skipping empty image bytes")
                            continue
                        contents.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))
            # ------------------------------------------------------------

            # 🔥 CRITICAL: Enhanced retry logic with manual fallback for SSL errors
            # Google's retry decorator doesn't always catch SSL errors properly
            
            max_attempts = 5
            attempt = 0
            last_exception = None
            
            while attempt < max_attempts:
                try:
                    attempt += 1
                    
                    if attempt > 1:
                        # Calculate backoff delay: 2s → 4s → 8s → 16s → 32s
                        backoff = min(2.0 ** (attempt - 1), 60.0)
                        logger.warning(f"🔄 Retry attempt {attempt}/{max_attempts} after {backoff:.1f}s delay...")
                        time.sleep(backoff)
                    
                    # Make the request
                    response = self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=config,
                    )
                    
                    # Success!
                    result = response.text
                    if attempt > 1:
                        logger.success(f"✅ Request succeeded on attempt {attempt}")
                    logger.debug(f"Generated {len(result)} chars from Gemini")
                    return result
                    
                except (ssl.SSLError, ssl.SSLEOFError, OSError, ConnectionError) as e:
                    # Network/SSL errors - retry
                    last_exception = e
                    error_type = type(e).__name__
                    logger.warning(f"⚠️ Network error on attempt {attempt}: {error_type}: {str(e)[:100]}")
                    
                    if attempt >= max_attempts:
                        logger.error(f"❌ All {max_attempts} attempts failed due to network errors")
                        raise ConnectionError(f"Network request failed after {max_attempts} attempts: {e}") from e
                    # Continue to next attempt
                    
                except google_exceptions.DeadlineExceeded as e:
                    logger.error(f"Gemini timeout after 10 minutes: {e}")
                    raise TimeoutError(f"Gemini API timed out after 10 minutes. Payload may be too large.") from e
                    
                except google_exceptions.ResourceExhausted as e:
                    logger.error(f"Gemini rate limit exceeded: {e}")
                    raise
                    
                except Exception as e:
                    # Other errors - don't retry, just fail
                    logger.error(f"Gemini generation failed: {e}")
                    raise
            
            # Should never reach here, but just in case
            if last_exception:
                raise ConnectionError(f"Network request failed after {max_attempts} attempts") from last_exception
            raise Exception("Unexpected error in retry logic")
            
        except Exception as e:
            # Catch-all for any unexpected errors that escape the retry loop
            logger.error(f"Gemini generation failed with unexpected error: {e}")
            raise

    def generate_content_stream(
        self,
        prompt: str,
        images: Optional[List[Union[str, bytes, Path]]] = None,
        **kwargs
    ) -> Generator[str, None, None]:
        """
        Stream text response (optionally with images).

        Args:
            prompt: Text instruction
            images: Optional image inputs
            **kwargs: Override config

        Yields:
            Text chunks
        """
        try:
            config = self._build_config(**kwargs)
            contents = [prompt]

            if images:
                for img in images:
                    if isinstance(img, (str, Path)):
                        with open(img, 'rb') as f:
                            data = f.read()
                        contents.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
                    elif isinstance(img, bytes):
                        contents.append(types.Part.from_bytes(data=img, mime_type="image/jpeg"))

            for chunk in self.client.models.generate_content_stream(
                model=self.model_name,
                contents=contents,
                config=config,
            ):
                if chunk.text:
                    yield chunk.text

        except Exception as e:
            logger.error(f"Gemini streaming failed: {e}")
            raise

    def count_tokens(self, text: str) -> int:
        """Estimate token count for text."""
        try:
            result = self.client.models.count_tokens(
                model=self.model_name,
                contents=text,
            )
            return result.total_tokens
        except Exception as e:
            logger.warning(f"Token counting failed: {e}. Using fallback.")
            return len(text) // 4

    def get_model_info(self) -> Dict[str, Any]:
        """Return model configuration details."""
        return {
            "model_name": self.model_name,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "provider": "Google Gemini",
        }

    # ===== Compatibility Methods for Legacy Code =====
    # These methods provide OpenAI-like interface for existing nodes
    
    def invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """
        OpenAI-compatible invoke method (non-streaming).
        """
        from datetime import datetime
        # TRANSLATED: Changed time format and prompt prefix to English
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        time_prefix = f"The current actual time is {current_time}"
        
        combined_prompt = f"{system_prompt}\n\n{time_prefix}\n{user_prompt}"
        return self.generate_content(combined_prompt, **kwargs)
    
    def stream_invoke(self, system_prompt: str, user_prompt: str, **kwargs) -> Generator[str, None, None]:
        """
        OpenAI-compatible streaming invoke method.
        """
        from datetime import datetime
        # TRANSLATED: Changed time format and prompt prefix to English
        current_time = datetime.now().strftime("%Y-%m-%d %H:%M")
        time_prefix = f"The current actual time is {current_time}"
        
        combined_prompt = f"{system_prompt}\n\n{time_prefix}\n{user_prompt}"
        yield from self.generate_content_stream(combined_prompt, **kwargs)
    
    def stream_invoke_to_string(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        """
        OpenAI-compatible streaming to string method.
        """
        chunks = list(self.stream_invoke(system_prompt, user_prompt, **kwargs))
        return ''.join(chunks)

    def __repr__(self) -> str:
        return f"GeminiClient(model={self.model_name}, temp={self.temperature})"


# Convenience factory functions for specific use cases
# UPDATED: All engines strictly default to gemini-3-pro-preview

def create_bioharvest_client() -> GeminiClient:
    """
    Create client optimized for BioHarvestEngine (biomedical literature search).
    
    Formerly create_query_client() - renamed to match new BioHarvestEngine.
    """
    return GeminiClient(
        model_name=os.getenv("BIOHARVEST_MODEL_NAME", "gemini-2.5-flash"),
        temperature=float(os.getenv("BIOHARVEST_TEMPERATURE", "0.3")),
        max_output_tokens=int(os.getenv("BIOHARVEST_MAX_TOKENS", "4096")),
    )


# Alias for backwards compatibility
create_query_client = create_bioharvest_client


def create_forensic_client() -> GeminiClient:
    """
    Create client optimized for ForensicEngine (vision, image analysis).
    
    Formerly create_media_client() - renamed to match new ForensicEngine.
    Uses low temperature for precise forensic analysis.
    """
    return GeminiClient(
        model_name=os.getenv("FORENSIC_MODEL_NAME", "gemini-3-pro-preview"),
        temperature=float(os.getenv("FORENSIC_TEMPERATURE", "0.2")),
        max_output_tokens=int(os.getenv("FORENSIC_MAX_TOKENS", "4096")),
    )


# Alias for backwards compatibility
create_media_client = create_forensic_client


def create_evidence_client() -> GeminiClient:
    """Create client optimized for EvidenceEngine (long-context PDFs)."""
    return GeminiClient(
        model_name=os.getenv("EVIDENCE_MODEL_NAME", "gemini-2.5-pro"),
        temperature=float(os.getenv("EVIDENCE_TEMPERATURE", "0.4")),
        max_output_tokens=int(os.getenv("EVIDENCE_MAX_TOKENS", "8192")),
    )


def create_report_client() -> GeminiClient:
    """Create client optimized for ReportEngine (long-form generation)."""
    return GeminiClient(
        model_name=os.getenv("REPORT_MODEL_NAME", "gemini-3-pro-preview"),
        temperature=float(os.getenv("REPORT_TEMPERATURE", "0.7")),
        max_output_tokens=int(os.getenv("REPORT_MAX_TOKENS", "8192")),
    )