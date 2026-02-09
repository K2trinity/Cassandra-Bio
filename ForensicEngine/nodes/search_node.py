"""
Search Node Implementation
Responsible for generating search queries and reflection queries
"""

import json
from typing import Dict, Any
from json.decoder import JSONDecodeError
from loguru import logger

from .base_node import BaseNode
from ..prompts import SYSTEM_PROMPT_FIRST_SEARCH, SYSTEM_PROMPT_REFLECTION
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_json_tags,
    extract_clean_response,
    fix_incomplete_json
)


class FirstSearchNode(BaseNode):
    """Node for generating initial search query for paragraphs"""
    
    def __init__(self, llm_client):
        """
        Initialize first search node
        
        Args:
            llm_client: LLM client instance
        """
        super().__init__(llm_client, "FirstSearchNode")
    
    def validate_input(self, input_data: Any) -> bool:
        """Validate input data"""
        if isinstance(input_data, str):
            try:
                data = json.loads(input_data)
                return "title" in data and "content" in data
            except JSONDecodeError:
                return False
        elif isinstance(input_data, dict):
            return "title" in input_data and "content" in input_data
        return False
    
    def run(self, input_data: Any, **kwargs) -> Dict[str, str]:
        """
        Invoke LLM to generate search query and reasoning
        
        Args:
            input_data: String or dict containing title and content
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing search_query and reasoning
        """
        try:
            if not self.validate_input(input_data):
                raise ValueError("Invalid input data format, requires title and content fields")
            
            # Prepare input data
            if isinstance(input_data, str):
                message = input_data
            else:
                message = json.dumps(input_data, ensure_ascii=False)
            
            logger.info("Generating first search query")
            
            # Invoke LLM
            response = self.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_FIRST_SEARCH, message)
            
            # Process response
            processed_response = self.process_output(response)
            
            logger.info(f"Generated search query: {processed_response.get('search_query', 'N/A')}")
            return processed_response
            
        except Exception as e:
            logger.exception(f"First search query generation failed: {str(e)}")
            raise e
    
    def process_output(self, output: str) -> Dict[str, str]:
        """
        处理LLM输出，提取搜索查询和推理
        
        Args:
            output: LLM原始输出
            
        Returns:
            包含search_query和reasoning的字典
        """
        try:
            # Clean response text
            cleaned_output = remove_reasoning_from_output(output)
            cleaned_output = clean_json_tags(cleaned_output)
            
            # Log cleaned output for debugging
            logger.info(f"Cleaned output: {cleaned_output}")
            
            # Parse JSON
            try:
                result = json.loads(cleaned_output)
                logger.info("JSON parsing succeeded")
            except JSONDecodeError as e:
                logger.error(f"JSON parsing failed: {str(e)}")
                # Use more robust extraction method
                result = extract_clean_response(cleaned_output)
                if "error" in result:
                    logger.error("JSON parsing failed, attempting repair...")
                    # Attempt JSON repair
                    fixed_json = fix_incomplete_json(cleaned_output)
                    if fixed_json:
                        try:
                            result = json.loads(fixed_json)
                            logger.info("JSON repair succeeded")
                        except JSONDecodeError:
                            logger.error("JSON repair failed")
                            # Return default query
                            return self._get_default_search_query()
                    else:
                        logger.error("Cannot repair JSON, using default query")
                        return self._get_default_search_query()
            
            # Validate and clean result
            search_query = result.get("search_query", "")
            reasoning = result.get("reasoning", "")
            
            if not search_query:
                logger.warning("Search query not found, using default query")
                return self._get_default_search_query()
            
            return {
                "search_query": search_query,
                "reasoning": reasoning
            }
            
        except Exception as e:
            self.log_error(f"Output processing failed: {str(e)}")
            # Return default query
            return self._get_default_search_query()
    
    def _get_default_search_query(self) -> Dict[str, str]:
        """
        Get default search query
        
        Returns:
            Default search query dictionary
        """
        return {
            "search_query": "biomedical research topic",
            "reasoning": "Default search query due to parsing failure"
        }


class ReflectionNode(BaseNode):
    """Node for reflecting on paragraphs and generating new search queries"""
    
    def __init__(self, llm_client):
        """
        Initialize reflection node
        
        Args:
            llm_client: LLM client instance
        """
        super().__init__(llm_client, "ReflectionNode")
    
    def validate_input(self, input_data: Any) -> bool:
        """Validate input data"""
        if isinstance(input_data, str):
            try:
                data = json.loads(input_data)
                required_fields = ["title", "content", "paragraph_latest_state"]
                return all(field in data for field in required_fields)
            except JSONDecodeError:
                return False
        elif isinstance(input_data, dict):
            required_fields = ["title", "content", "paragraph_latest_state"]
            return all(field in input_data for field in required_fields)
        return False
    
    def run(self, input_data: Any, **kwargs) -> Dict[str, str]:
        """
        Invoke LLM to reflect and generate search query
        
        Args:
            input_data: String or dict containing title, content and paragraph_latest_state
            **kwargs: Additional parameters
            
        Returns:
            Dictionary containing search_query and reasoning
        """
        try:
            if not self.validate_input(input_data):
                raise ValueError("Invalid input data format, requires title, content and paragraph_latest_state fields")
            
            # Prepare input data
            if isinstance(input_data, str):
                message = input_data
            else:
                message = json.dumps(input_data, ensure_ascii=False)
            
            logger.info("Reflecting and generating new search query")
            
            # Invoke LLM
            response = self.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_REFLECTION, message)
            
            # Process response
            processed_response = self.process_output(response)
            
            logger.info(f"Reflection generated search query: {processed_response.get('search_query', 'N/A')}")
            return processed_response
            
        except Exception as e:
            logger.exception(f"Reflection search query generation failed: {str(e)}")
            raise e
    
    def process_output(self, output: str) -> Dict[str, str]:
        """
        处理LLM输出，提取搜索查询和推理
        
        Args:
            output: LLM原始输出
            
        Returns:
            包含search_query和reasoning的字典
        """
        try:
            # Clean response text
            cleaned_output = remove_reasoning_from_output(output)
            cleaned_output = clean_json_tags(cleaned_output)
            
            # Log cleaned output for debugging
            logger.info(f"Cleaned output: {cleaned_output}")
            
            # Parse JSON
            try:
                result = json.loads(cleaned_output)
                logger.info("JSON parsing succeeded")
            except JSONDecodeError as e:
                logger.error(f"JSON parsing failed: {str(e)}")
                # Use more robust extraction method
                result = extract_clean_response(cleaned_output)
                if "error" in result:
                    logger.error("JSON parsing failed, attempting repair...")
                    # Attempt JSON repair
                    fixed_json = fix_incomplete_json(cleaned_output)
                    if fixed_json:
                        try:
                            result = json.loads(fixed_json)
                            logger.info("JSON repair succeeded")
                        except JSONDecodeError:
                            logger.error("JSON repair failed")
                            # Return default query
                            return self._get_default_reflection_query()
                    else:
                        logger.error("Cannot repair JSON, using default query")
                        return self._get_default_reflection_query()
            
            # Validate and clean result
            search_query = result.get("search_query", "")
            reasoning = result.get("reasoning", "")
            
            if not search_query:
                logger.warning("Search query not found, using default query")
                return self._get_default_reflection_query()
            
            return {
                "search_query": search_query,
                "reasoning": reasoning
            }
            
        except Exception as e:
            logger.exception(f"Output processing failed: {str(e)}")
            # Return default query
            return self._get_default_reflection_query()
    
    def _get_default_reflection_query(self) -> Dict[str, str]:
        """
        Get default reflection search query
        
        Returns:
            Default reflection search query dictionary
        """
        return {
            "search_query": "additional biomedical research evidence",
            "reasoning": "Default reflection query due to parsing failure"
        }
