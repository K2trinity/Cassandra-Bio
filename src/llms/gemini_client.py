"""
Centralized Google Gemini client for Cassandra.

This is the ONLY LLM interface for the entire system.
All engines (Query, Media, Insight, Report) use this unified client.

Enhanced with robust error handling and retry logic for production stability.
"""

import os
import ssl
import time
import json
import importlib
from typing import Any, Dict, List, Optional, Generator, Union
from pathlib import Path

from google import genai
from google.genai import types
from google.api_core import retry
from google.api_core import exceptions as google_exceptions

# Import SSL error types for explicit handling
from ssl import SSLError, SSLEOFError


def _resolve_logger():
    try:
        return importlib.import_module("loguru").logger
    except Exception:  # pragma: no cover - optional dependency fallback
        import logging

        return logging.getLogger(__name__)


logger = _resolve_logger()


def _settings_value(name: str, default: Any = None) -> Any:
    """Read repo settings first so .env overrides stale shell variables."""
    try:
        from config import settings

        value = getattr(settings, name, None)
        if value not in (None, ""):
            return value
    except Exception:
        pass
    return os.getenv(name, default)


class GeminiClient:
    """
    Universal Google Gemini API client for active Cassandra engines.
    
    Supports text generation with streaming and non-streaming modes.
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
        project: Optional[str] = None,
        location: Optional[str] = None,
        # UPDATED: Strictly enforced default model as requested
        model_name: str = "gemini-3.1-pro-preview",
        temperature: float = 1.0,  # 🔥 Gemini 3: MUST keep at 1.0 (default), DO NOT change
        max_output_tokens: int = 8192,  # Gemini 3 supports up to 64k output
    ):
        """
        Initialize universal Gemini client via Vertex AI with auto-fallback support.

        Args:
            project: Google Cloud project ID (defaults to GOOGLE_CLOUD_PROJECT env var)
            location: Vertex AI region (defaults to GOOGLE_CLOUD_LOCATION env var, fallback 'global')
            model_name: Model ID (e.g. gemini-3.1-pro-preview)
            temperature: Sampling temperature - KEEP AT 1.0 for Gemini 3 (changing may cause looping)
            max_output_tokens: Maximum response tokens (Gemini 3 supports up to 64k)
            
        ⚠️  VERTEX AI AUTHENTICATION:
            - Uses Application Default Credentials (ADC).
            - For local dev: run `gcloud auth application-default login`
            - For production: use service account or workload identity.
            
        ⚠️  GEMINI 3 RECOMMENDATIONS:
            - Temperature: MUST keep at 1.0 (default). Lower values may cause looping or degraded performance.
            - Thinking Level: Use thinking_level parameter instead of temperature tuning for reasoning control.
            - Context Window: 1M input / 64k output (as of Jan 2025 knowledge cutoff).
        """
        self.project = project or _settings_value("GOOGLE_CLOUD_PROJECT")
        self.location = location or _settings_value("GOOGLE_CLOUD_LOCATION", "global")
        if not self.project:
            raise ValueError(
                "Google Cloud project ID required. Set GOOGLE_CLOUD_PROJECT environment variable "
                "or pass project parameter. Auth via ADC: run `gcloud auth application-default login`."
            )

        self.model_name = model_name
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        
        # 🔥 NEW: Model fallback chain for quota exhaustion
        fallback_chain_str = _settings_value(
            "MODEL_FALLBACK_CHAIN",
            "gemini-3.1-pro-preview,gemini-3-flash-preview,gemini-3.1-flash-lite,gemini-2.5-pro,gemini-2.5-flash,gemini-2.5-flash-lite"
        )
        self.fallback_models = [m.strip() for m in fallback_chain_str.split(",")]
        
        # Track current model index in fallback chain
        try:
            self.current_model_index = self.fallback_models.index(model_name)
        except ValueError:
            # Model not in fallback chain, add it at the beginning
            self.fallback_models.insert(0, model_name)
            self.current_model_index = 0
        
        # Track if model was downgraded
        self.original_model = model_name
        self.downgraded = False

        # Initialize Vertex AI client (ADC handles auth automatically)
        self.client = genai.Client(
            vertexai=True,
            project=self.project,
            location=self.location,
        )
        logger.info(f"Initialized central GeminiClient (Vertex AI): {model_name} (temp={temperature}, project={self.project}, location={self.location})")
        logger.debug(f"Model fallback chain: {' → '.join(self.fallback_models)}")

    def _try_downgrade_model(self) -> bool:
        """
        Attempt to downgrade to the next model in fallback chain.
        
        Returns:
            True if successfully downgraded, False if no more models available
        """
        next_index = self.current_model_index + 1
        
        if next_index >= len(self.fallback_models):
            logger.error("❌ No more fallback models available - all models exhausted")
            return False
        
        # Downgrade to next model
        old_model = self.model_name
        self.model_name = self.fallback_models[next_index]
        self.current_model_index = next_index
        self.downgraded = True
        
        logger.warning(f"⬇️  Model downgraded: {old_model} → {self.model_name}")
        logger.info(f"📊 Remaining fallback models: {self.fallback_models[next_index+1:] if next_index+1 < len(self.fallback_models) else 'None'}")
        
        return True
    
    def reset_model(self):
        """Reset to original model (useful for new requests)."""
        if self.downgraded:
            self.model_name = self.original_model
            self.current_model_index = self.fallback_models.index(self.original_model)
            self.downgraded = False
            logger.info(f"🔄 Model reset to original: {self.model_name}")

    @staticmethod
    def _is_model_access_error(error_msg: str) -> bool:
        """Detect model-not-found / model-access-denied errors returned by Vertex AI."""
        msg = (error_msg or "").lower()
        return (
            ("publisher model" in msg and ("not found" in msg or "does not have access" in msg))
            or ("404 not_found" in msg and "models/" in msg)
            or ("permission_denied" in msg and "models/" in msg)
        )
    
    def _build_config(self, **kwargs) -> types.GenerateContentConfig:
        """Build generation config with overrides.
        
        🔥 NEW: Supports structured JSON output via response_mime_type and response_schema.
        🔥 Gemini 3: Supports thinking_level parameter (low, medium, high, minimal).
        """
        config_params = {
            "temperature": kwargs.get("temperature", self.temperature),
            "max_output_tokens": kwargs.get("max_output_tokens", self.max_output_tokens),
            "top_p": kwargs.get("top_p"),
            "top_k": kwargs.get("top_k"),
            "safety_settings": self.DEFAULT_SAFETY_SETTINGS,
        }
        
        # 🔥 NEW: Add structured output parameters if provided
        if "response_mime_type" in kwargs:
            config_params["response_mime_type"] = kwargs["response_mime_type"]
        if "response_schema" in kwargs:
            config_params["response_schema"] = kwargs["response_schema"]
        
        # 🔥 Gemini 3: Add thinking_config if thinking_level is specified
        # Options: "low", "medium" (Flash only), "high" (default), "minimal" (Flash only)
        if "thinking_level" in kwargs:
            thinking_level = kwargs["thinking_level"]
            config_params["thinking_config"] = types.ThinkingConfig(
                thinking_level=thinking_level
            )
            logger.debug(f"🧠 Thinking level set to: {thinking_level}")
        
        return types.GenerateContentConfig(**config_params)

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
            **kwargs: Override config (temperature, max_output_tokens, thinking_level, etc.)
            
        Keyword Args:
            thinking_level: (Gemini 3) Control reasoning depth - "low", "high" (default), "medium" (Flash), "minimal" (Flash)
            temperature: Sampling temperature (default 1.0 - do not change for Gemini 3)
            max_output_tokens: Maximum response tokens

        Returns:
            Generated text as string
        """
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
        
        max_attempts = 7  # 🔥 Increased from 5 to 7 for better SSL stability
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
                
                # 🔥 CRITICAL FIX: Check for None before calling len()
                if result is None:
                    logger.error(f"⚠️ Gemini returned None response on attempt {attempt}")
                    if attempt < max_attempts:
                        continue  # Retry
                    else:
                        raise ValueError("Gemini API returned None after all retries")
                
                if attempt > 1:
                    logger.success(f"✅ Request succeeded on attempt {attempt}")
                logger.debug(f"Generated {len(result)} chars from Gemini")
                
                # 🔥 NEW: 如果请求JSON格式，验证响应有效性
                if kwargs.get('response_mime_type') == 'application/json':
                    # 快速检查是否看起来像JSON
                    stripped = result.strip()
                    if not stripped.startswith(('{', '[')):
                        logger.warning(f"⚠️ JSON response doesn't start with {{ or [. First 100 chars: {stripped[:100]}")
                        # 尝试提取JSON内容
                        if '```json' in stripped:
                            logger.info("🔧 Detected markdown wrapper, will be handled by validator")
                        elif '{' in stripped:
                            # 找到第一个 {
                            json_start = stripped.index('{')
                            logger.warning(f"⚠️ Found {{ at position {json_start}, response has {json_start} chars of non-JSON prefix")
                
                return result
                
            except (ssl.SSLError, ssl.SSLEOFError, OSError, ConnectionError, BrokenPipeError) as e:
                # Network/SSL errors - retry with longer backoff
                last_exception = e
                error_type = type(e).__name__
                error_msg = str(e)
                logger.warning(f"⚠️ Network error on attempt {attempt}: {error_type}: {error_msg[:100]}")
                
                # Special handling for SSL EOF errors (common with large payloads)
                if "EOF" in error_msg or "UNEXPECTED_EOF_WHILE_READING" in error_msg:
                    logger.info("🔍 SSL EOF detected - likely network instability or large payload")
                
                if attempt >= max_attempts:
                    logger.error(f"❌ All {max_attempts} attempts failed due to network errors")
                    raise ConnectionError(f"Network request failed after {max_attempts} attempts: {e}") from e
                
                # Use longer backoff for SSL errors (5s → 10s → 20s → 40s → 80s → 160s)
                backoff = min(5.0 * (2.0 ** (attempt - 1)), 180.0)  # 🔥 Max 3 minutes
                logger.info(f"🔄 Retrying in {backoff:.1f}s due to network instability...")
                
                # 🔥 SSL 预热: 尝试轻量请求来重建连接
                if attempt < max_attempts - 1:
                    try:
                        logger.debug("🔥 Attempting SSL connection warmup...")
                        warmup_response = self.client.models.generate_content(
                            model=self.model_name,
                            contents="test",
                            config=types.GenerateContentConfig(max_output_tokens=10)
                        )
                        logger.success("✅ SSL warmup successful")
                    except Exception as warmup_e:
                        logger.debug(f"⚠️ SSL warmup failed: {warmup_e}")
                
                time.sleep(backoff)
                # Continue to next attempt
            
            except google_exceptions.InternalServerError as e:
                # 🔥 NEW: Google 500 errors - retry with exponential backoff
                last_exception = e
                logger.warning(f"⚠️ Google Internal Server Error (500) on attempt {attempt}")
                
                if attempt >= max_attempts:
                    logger.error(f"❌ All {max_attempts} attempts failed due to Google 500 errors")
                    raise ConnectionError(f"Google server error after {max_attempts} attempts: {e}") from e
                
                # Longer backoff for server errors (up to 2 minutes)
                backoff = min(2.0 ** (attempt), 120.0)
                logger.info(f"🔄 Retrying in {backoff:.1f}s...")
                time.sleep(backoff)
                # Continue to next attempt
                
            except google_exceptions.DeadlineExceeded as e:
                logger.error(f"Gemini timeout after 10 minutes: {e}")
                raise TimeoutError(f"Gemini API timed out after 10 minutes. Payload may be too large.") from e
            
            except (SSLError, SSLEOFError) as e:
                # 🔥 NEW: Handle SSL connection errors with retry
                last_exception = e
                error_msg = str(e)
                
                # Check if this is the EOF protocol violation
                is_ssl_eof = (
                    "UNEXPECTED_EOF_WHILE_READING" in error_msg or
                    "EOF occurred in violation of protocol" in error_msg or
                    "ssl.c:" in error_msg
                )
                
                if is_ssl_eof:
                    logger.warning(f"⚠️ SSL Protocol Error (EOF) on attempt {attempt}/{max_attempts}")
                    logger.debug(f"SSL Error details: {error_msg}")
                else:
                    logger.warning(f"⚠️ SSL Connection Error on attempt {attempt}/{max_attempts}: {type(e).__name__}")
                
                if attempt >= max_attempts:
                    logger.error(f"❌ SSL errors persisted after {max_attempts} attempts")
                    raise ConnectionError(f"SSL connection failed after {max_attempts} attempts: {error_msg}") from e
                
                # Progressive backoff for SSL issues (10s, 20s, 40s, 60s)
                backoff = min(10.0 * (2 ** (attempt - 1)), 60.0)
                logger.info(f"🔄 SSL connection issue, retrying in {backoff:.1f}s...")
                
                # Force SSL warmup before retry
                try:
                    logger.debug("🔧 Attempting SSL connection warmup...")
                    # Create new client to force fresh SSL handshake
                    self.client = genai.Client(
                        vertexai=True,
                        project=self.project,
                        location=self.location,
                    )
                    # Test connection with minimal request
                    self.client.models.generate_content(
                        model=self.model_name,
                        contents="test",
                        config=types.GenerateContentConfig(max_output_tokens=10)
                    )
                    logger.success("✅ SSL warmup successful, retrying original request")
                except Exception as warmup_e:
                    logger.debug(f"⚠️ SSL warmup failed: {warmup_e}")
                
                time.sleep(backoff)
                continue  # Retry the request
            
            except google_exceptions.ResourceExhausted as e:
                # 🔥 ENHANCED: Auto-downgrade model when quota exhausted
                last_exception = e
                error_msg = str(e)
                
                # Check if this is a daily quota exhaustion (not rate limit)
                is_quota_exhausted = (
                    "quota exceeded" in error_msg.lower() or
                    "limit: 0" in error_msg.lower() or
                    "per_day" in error_msg.lower()
                )
                
                if is_quota_exhausted:
                    logger.error(f"💥 Model quota exhausted: {self.model_name}")
                    
                    # Try to downgrade to next model
                    if self._try_downgrade_model():
                        logger.info(f"♻️  Retrying with downgraded model: {self.model_name}")
                        # Reset attempt counter for new model
                        attempt = 1
                        continue
                    else:
                        # No more models to try
                        logger.error("❌ All fallback models exhausted - cannot proceed")
                        raise
                else:
                    # Regular rate limit (RPM) - use backoff
                    logger.warning(f"⚠️ Gemini rate limit (RPM) exceeded on attempt {attempt}")
                    
                    if attempt >= max_attempts:
                        logger.error(f"❌ Rate limit persisted after {max_attempts} attempts")
                        raise
                    
                    # Aggressive backoff for rate limit (minimum 30s)
                    backoff = max(30.0, min(2.0 ** (attempt + 3), 300.0))
                    logger.info(f"🔄 Rate limit hit, waiting {backoff:.1f}s before retry...")
                    time.sleep(backoff)
                    # Continue to next attempt

            except google_exceptions.NotFound as e:
                # Model version not available in current region/project
                last_exception = e
                logger.error(f"⚠️ Model not found or not accessible: {self.model_name}")

                if self._try_downgrade_model():
                    logger.info(f"♻️  Retrying with fallback model: {self.model_name}")
                    attempt = 1
                    continue

                logger.error("❌ No fallback model left for 404 NOT_FOUND")
                raise

            except google_exceptions.PermissionDenied as e:
                # Some projects are denied for specific publisher models.
                last_exception = e
                error_msg = str(e)
                if self._is_model_access_error(error_msg):
                    logger.error(f"⚠️ Model access denied: {self.model_name}")
                    if self._try_downgrade_model():
                        logger.info(f"♻️  Retrying with fallback model: {self.model_name}")
                        attempt = 1
                        continue
                raise
            
            except Exception as e:
                # 🔥 CRITICAL FIX: Catch errors that aren't properly typed
                error_msg = str(e)
                error_dict = getattr(e, 'args', ())

                # Some SDK layers surface 404/permission issues as generic exceptions.
                if self._is_model_access_error(error_msg):
                    logger.error(f"⚠️ Model unavailable for current project/region: {self.model_name}")
                    if self._try_downgrade_model():
                        logger.info(f"♻️  Retrying with fallback model: {self.model_name}")
                        attempt = 1
                        continue
                
                # 🔥 NEW: Check for SSL errors that weren't caught by specific handler
                is_ssl_error = (
                    "SSL" in error_msg or
                    "ssl" in error_msg.lower() or
                    "UNEXPECTED_EOF" in error_msg or
                    "EOF occurred in violation of protocol" in error_msg or
                    isinstance(e, (SSLError, SSLEOFError))
                )
                
                if is_ssl_error:
                    logger.warning(f"⚠️ Uncaught SSL Error (attempt {attempt}/{max_attempts}): {error_msg[:200]}")
                    
                    if attempt < max_attempts:
                        backoff = min(10.0 * (2 ** (attempt - 1)), 60.0)
                        logger.info(f"🔄 SSL issue detected, retrying in {backoff:.1f}s...")
                        
                        # Force client recreation
                        try:
                            self.client = genai.Client(
                                vertexai=True,
                                project=self.project,
                                location=self.location,
                            )
                            logger.debug("🔧 Recreated Gemini client for SSL recovery")
                        except Exception as recreate_error:
                            logger.debug(f"⚠️ Client recreation failed: {recreate_error}")
                        
                        time.sleep(backoff)
                        continue  # Retry
                    else:
                        logger.error(f"❌ SSL errors persisted after {max_attempts} attempts")
                        raise ConnectionError(f"SSL connection failed: {error_msg}") from e
                
                # Check if this is a 503 service overload error
                is_503_overload = (
                    "503" in error_msg and 
                    ("UNAVAILABLE" in error_msg or "overloaded" in error_msg.lower())
                )
                
                if is_503_overload:
                    logger.error(f"⚠️ 503 Service Overloaded: Gemini servers are at capacity")
                    
                    if attempt < max_attempts:
                        # For 503, use much longer backoff (30-60 seconds)
                        backoff = min(30.0 * (2 ** (attempt - 1)), 120.0)  # 30s, 60s, 120s
                        logger.warning(f"🔄 Waiting {backoff:.0f}s for service to recover...")
                        time.sleep(backoff)
                        continue  # Retry
                    else:
                        logger.error(f"❌ Service still overloaded after {max_attempts} attempts")
                        raise
                
                # Check if this is actually a 429 quota exhaustion error
                is_429_quota = (
                    ("429" in error_msg and "RESOURCE_EXHAUSTED" in error_msg) or
                    ("quota exceeded" in error_msg.lower() and ("limit: 0" in error_msg.lower() or "per_day" in error_msg.lower()))
                )
                
                if is_429_quota:
                    logger.error(f"💥 Model quota exhausted (429): {self.model_name}")
                    logger.debug(f"Error type: {type(e).__module__}.{type(e).__name__}")
                    
                    # Try to downgrade to next model
                    if self._try_downgrade_model():
                        logger.info(f"♻️  Retrying with downgraded model: {self.model_name}")
                        # Reset attempt counter for new model
                        attempt = 1
                        continue
                    else:
                        # No more models to try
                        logger.error("❌ All fallback models exhausted - cannot proceed")
                        raise
                
                # Check for server disconnection errors (common with large payloads)
                is_disconnect = (
                    "disconnected" in error_msg.lower() or
                    "server disconnected" in error_msg.lower() or
                    "remote end closed connection" in error_msg.lower() or
                    "connection reset" in error_msg.lower() or
                    "RemoteProtocolError" in str(type(e).__name__)
                )
                
                if is_disconnect:
                    last_exception = e
                    logger.warning(f"⚠️ Server disconnected on attempt {attempt}/{max_attempts}: {error_msg[:200]}")
                    
                    if attempt < max_attempts:
                        backoff = min(10.0 * (2 ** (attempt - 1)), 120.0)
                        logger.info(f"🔄 Server disconnected, retrying in {backoff:.1f}s...")
                        
                        # Recreate client to establish fresh connection
                        try:
                            self.client = genai.Client(
                                vertexai=True,
                                project=self.project,
                                location=self.location,
                            )
                            logger.debug("🔧 Recreated Gemini client after disconnect")
                        except Exception as recreate_error:
                            logger.debug(f"⚠️ Client recreation failed: {recreate_error}")
                        
                        time.sleep(backoff)
                        continue  # Retry
                    else:
                        logger.error(f"❌ Server disconnections persisted after {max_attempts} attempts")
                        raise ConnectionError(f"Server disconnected after {max_attempts} attempts: {error_msg}") from e
                
                # Not a quota exhaustion error - re-raise
                # Other errors - don't retry, just fail
                logger.error(f"Gemini generation failed: {e}")
                raise
        
        # Should never reach here, but just in case
        if last_exception:
            raise ConnectionError(f"Network request failed after {max_attempts} attempts") from last_exception
        raise Exception("Unexpected error in retry logic")

    def generate_json(
        self,
        prompt: str,
        response_schema: Optional[Dict[str, Any]] = None,
        images: Optional[List[Union[str, bytes, Path]]] = None,
        system_instruction: Optional[str] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        🔥 NEW: Generate structured JSON output with guaranteed format.
        
        This method forces Gemini to output pure JSON (no markdown wrappers)
        by using response_mime_type="application/json".
        
        Args:
            prompt: Text instruction (user prompt)
            response_schema: Optional JSON schema to enforce output structure
            images: Optional image inputs
            system_instruction: Optional system prompt (prepended to user prompt)
            **kwargs: Override config
            
        Returns:
            Parsed JSON dictionary (guaranteed valid)
            
        Example:
            >>> schema = {
            ...     "type": "object",
            ...     "properties": {
            ...         "status": {"type": "string"},
            ...         "score": {"type": "number"}
            ...     },
            ...     "required": ["status", "score"]
            ... }
            >>> client.generate_json(prompt, response_schema=schema)
            {"status": "CLEAN", "score": 0.15}
        """
        # Combine system instruction with user prompt if provided
        if system_instruction:
            combined_prompt = f"{system_instruction}\n\n{prompt}"
        else:
            combined_prompt = prompt
        
        # Force JSON output
        kwargs["response_mime_type"] = "application/json"
        if response_schema:
            kwargs["response_schema"] = response_schema
        
        # Generate content (will be pure JSON)
        response = self.generate_content(combined_prompt, images=images, **kwargs)
        
        # Parse and validate
        try:
            data = json.loads(response)
            logger.debug(f"✅ Structured JSON output: {len(str(data))} chars")
            return data
        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse JSON output: {e}")
            logger.debug(f"Raw response (first 500 chars): {response[:500]}")
            
            # 🔥 TRIPLE-LAYER DEFENSE: Attempt json-repair as fallback
            try:
                # Check if json-repair is available
                try:
                    from json_repair import repair_json
                    logger.info("🔧 Attempting JSON repair with json-repair library...")
                    repaired_data = repair_json(response)
                    logger.success(f"✅ JSON repaired successfully via json-repair library")
                    return repaired_data
                except ImportError:
                    logger.warning("⚠️ json-repair library not installed, using manual repair")
                    
                    # Manual repair: Try to close unterminated strings
                    if "Unterminated string" in str(e):
                        # Find the position of the error
                        pos = e.pos if hasattr(e, 'pos') else len(response)
                        # Try adding closing quote at various positions
                        for offset in [0, 1, 2, -1, -2]:
                            try:
                                repair_pos = min(max(0, pos + offset), len(response))
                                repaired = response[:repair_pos] + '"}}' + response[repair_pos:]
                                data = json.loads(repaired)
                                logger.success(f"✅ Manual repair successful (offset={offset})")
                                return data
                            except:
                                continue
                    
                    logger.error("❌ All repair strategies failed")
            except Exception as repair_error:
                logger.error(f"❌ Repair attempt failed: {repair_error}")
            
            # Return error dict instead of crashing
            return {"error": "JSON parse failed", "raw": response[:200], "details": str(e)}

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
            "provider": "Google Gemini (Vertex AI)",
            "project": self.project,
            "location": self.location,
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


# Convenience factory functions for active use cases

def create_bioharvest_client() -> GeminiClient:
    """
    Legacy shim for Harvest query client construction.

    The canonical factory now lives in Harvest to keep harvest-specific
    instantiation out of src.
    """
    from src.engines.harvest.llm.client_factory import create_harvest_client

    return create_harvest_client()


# Alias for backwards compatibility
create_query_client = create_bioharvest_client


def create_report_client() -> GeminiClient:
    """
    Create client optimized for ReportEngine (long-form generation).
    
    Uses a stable default model with automatic fallback for region/access differences.
    Uses default temperature (1.0) for optimal reasoning performance.
    """
    return GeminiClient(
        model_name=str(_settings_value("REPORT_MODEL_NAME", "gemini-3.1-pro-preview")),
        temperature=float(_settings_value("REPORT_TEMPERATURE", "1.0")),
        max_output_tokens=int(_settings_value("REPORT_MAX_TOKENS", "8192")),
    )
