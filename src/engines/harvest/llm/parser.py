"""LLM-backed query parser with safe fallback behavior."""

from typing import Any, Dict

from .._logging import logger

from .client_factory import create_harvest_client
from .json_sanitizer import sanitize_llm_json
from .prompts import QUERY_PARSING_PROMPT

from ..schemas import QueryIntent


class QueryParser:
    """Parse user query into structured retriever intents."""

    def __init__(self, llm_client: Any = None):
        self.llm = llm_client or create_harvest_client()

    def parse(self, user_query: str) -> QueryIntent:
        """Generate structured retrieval queries from user input."""
        prompt = QUERY_PARSING_PROMPT.format(user_query=user_query)

        try:
            response = self.llm.generate_content(prompt)
            parsed = sanitize_llm_json(response)

            if "error" in parsed:
                raise ValueError(parsed["error"])

            payload = self._normalize_payload(parsed, user_query)
            intent = QueryIntent(**payload)
            logger.info(f"Extracted core entity: {intent.core_entity}")
            return intent
        except Exception as exc:
            logger.warning(f"LLM query parsing failed: {exc}, using fallback queries")
            return self._fallback_intent(user_query)

    @staticmethod
    def _normalize_payload(payload: Dict[str, Any], user_query: str) -> Dict[str, Any]:
        """Ensure required query fields are always available."""
        core_entity = payload.get("core_entity") or user_query
        pubmed = payload.get("pubmed") or [core_entity]
        clinicaltrials = payload.get("clinicaltrials") or [core_entity]

        return {
            "core_entity": str(core_entity),
            "pubmed": [str(x) for x in pubmed],
            "clinicaltrials": [str(x) for x in clinicaltrials],
            "original_query": user_query,
        }

    @staticmethod
    def _fallback_intent(user_query: str) -> QueryIntent:
        """Fallback query set for robust retrieval when LLM parsing fails."""
        return QueryIntent(
            core_entity=user_query,
            pubmed=[
                f"{user_query} clinical trial",
                f"{user_query} mechanism biomarker",
                f"{user_query} efficacy safety",
            ],
            clinicaltrials=[user_query, user_query, user_query],
            original_query=user_query,
        )
