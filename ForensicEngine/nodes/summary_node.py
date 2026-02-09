"""
Summary Node Implementation
Responsible for generating and updating paragraph content based on search results
"""

import json
from typing import Dict, Any, List
from json.decoder import JSONDecodeError
from loguru import logger

from .base_node import StateMutationNode
from ..state.state import State
from ..prompts import SYSTEM_PROMPT_FIRST_SUMMARY, SYSTEM_PROMPT_REFLECTION_SUMMARY
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_json_tags,
    extract_clean_response,
    fix_incomplete_json,
    format_search_results_for_prompt
)




class FirstSummaryNode(StateMutationNode):
    """Node for generating initial paragraph summary based on search results"""
    
    def __init__(self, llm_client):
        """
        Initialize first summary node
        
        Args:
            llm_client: LLM client instance
        """
        super().__init__(llm_client, "FirstSummaryNode")
    
    def validate_input(self, input_data: Any) -> bool:
        """Validate input data"""
        if isinstance(input_data, str):
            try:
                data = json.loads(input_data)
                required_fields = ["title", "content", "search_query", "search_results"]
                return all(field in data for field in required_fields)
            except JSONDecodeError:
                return False
        elif isinstance(input_data, dict):
            required_fields = ["title", "content", "search_query", "search_results"]
            return all(field in input_data for field in required_fields)
        return False
    
    def run(self, input_data: Any, **kwargs) -> str:
        """
        Invoke LLM to generate paragraph summary
        
        Args:
            input_data: Data containing title, content, search_query and search_results
            **kwargs: Additional parameters
            
        Returns:
            Paragraph summary content
        """
        try:
            if not self.validate_input(input_data):
                raise ValueError("Invalid input data format")
            
            # Prepare input data
            if isinstance(input_data, str):
                message = input_data
            else:
                message = json.dumps(input_data, ensure_ascii=False)
            
            logger.info("Generating first paragraph summary")
            
            # Invoke LLM to generate summary (streaming, safely concatenating UTF-8)
            response = self.llm_client.stream_invoke_to_string(
                SYSTEM_PROMPT_FIRST_SUMMARY,
                message,
            )
            
            # Process response
            processed_response = self.process_output(response)
            
            logger.info("Successfully generated first paragraph summary")
            return processed_response
            
        except Exception as e:
            logger.exception(f"First summary generation failed: {str(e)}")
            raise e
    
    def process_output(self, output: str) -> str:
        """
        Process LLM output and extract paragraph content
        
        Args:
            output: Raw LLM output
            
        Returns:
            Paragraph content
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
                # Attempt to repair JSON
                fixed_json = fix_incomplete_json(cleaned_output)
                if fixed_json:
                    try:
                        result = json.loads(fixed_json)
                        logger.info("JSON repair succeeded")
                    except JSONDecodeError:
                        logger.exception("JSON repair failed, using cleaned text directly")
                        # If not JSON format, return cleaned text directly
                        return cleaned_output
                else:
                    logger.exception("Cannot repair JSON, using cleaned text directly")
                    # If not JSON format, return cleaned text directly
                    return cleaned_output
            
            # Extract paragraph content
            if isinstance(result, dict):
                paragraph_content = result.get("paragraph_latest_state", "")
                if paragraph_content:
                    return paragraph_content
            
            # If extraction failed, return original cleaned text
            return cleaned_output
            
        except Exception as e:
            logger.exception(f"Output processing failed: {str(e)}")
            return "Failed to generate paragraph summary"
    
    def mutate_state(self, input_data: Any, state: State, paragraph_index: int, **kwargs) -> State:
        """
        Update paragraph's latest summary to state
        
        Args:
            input_data: Input data
            state: Current state
            paragraph_index: Paragraph index
            **kwargs: Additional parameters
            
        Returns:
            Updated state
        """
        try:
            # Generate summary
            summary = self.run(input_data, **kwargs)
            
            # Update state
            if 0 <= paragraph_index < len(state.paragraphs):
                state.paragraphs[paragraph_index].research.latest_summary = summary
                logger.info(f"Updated first summary for paragraph {paragraph_index}")
            else:
                raise ValueError(f"Paragraph index {paragraph_index} out of range")
            
            state.update_timestamp()
            return state
            
        except Exception as e:
            logger.exception(f"State update failed: {str(e)}")
            raise e


class ReflectionSummaryNode(StateMutationNode):
    """Node for updating paragraph summary based on reflection search results"""
    
    def __init__(self, llm_client):
        """
        Initialize reflection summary node
        
        Args:
            llm_client: LLM client instance
        """
        super().__init__(llm_client, "ReflectionSummaryNode")
    
    def validate_input(self, input_data: Any) -> bool:
        """Validate input data"""
        if isinstance(input_data, str):
            try:
                data = json.loads(input_data)
                required_fields = ["title", "content", "search_query", "search_results", "paragraph_latest_state"]
                return all(field in data for field in required_fields)
            except JSONDecodeError:
                return False
        elif isinstance(input_data, dict):
            required_fields = ["title", "content", "search_query", "search_results", "paragraph_latest_state"]
            return all(field in input_data for field in required_fields)
        return False
    
    def run(self, input_data: Any, **kwargs) -> str:
        """
        Invoke LLM to update paragraph content
        
        Args:
            input_data: Data containing complete reflection information
            **kwargs: Additional parameters
            
        Returns:
            Updated paragraph content
        """
        try:
            if not self.validate_input(input_data):
                raise ValueError("Invalid input data format")
            
            # Prepare input data
            if isinstance(input_data, str):
                message = input_data
            else:
                message = json.dumps(input_data, ensure_ascii=False)
            
            logger.info("Generating reflection summary")
            
            # Invoke LLM to generate summary (streaming, safely concatenating UTF-8)
            response = self.llm_client.stream_invoke_to_string(
                SYSTEM_PROMPT_REFLECTION_SUMMARY,
                message,
            )
            
            # Process response
            processed_response = self.process_output(response)
            
            logger.info("Successfully generated reflection summary")
            return processed_response
            
        except Exception as e:
            logger.exception(f"Reflection summary generation failed: {str(e)}")
            raise e
    
    def process_output(self, output: str) -> str:
        """
        Process LLM output and extract updated paragraph content
        
        Args:
            output: Raw LLM output
            
        Returns:
            Updated paragraph content
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
                # Attempt to repair JSON
                fixed_json = fix_incomplete_json(cleaned_output)
                if fixed_json:
                    try:
                        result = json.loads(fixed_json)
                        logger.info("JSON repair succeeded")
                    except JSONDecodeError:
                        logger.error("JSON repair failed, using cleaned text directly")
                        # If not JSON format, return cleaned text directly
                        return cleaned_output
                else:
                    logger.error("Cannot repair JSON, using cleaned text directly")
                    # If not JSON format, return cleaned text directly
                    return cleaned_output
            
            # Extract updated paragraph content
            if isinstance(result, dict):
                updated_content = result.get("updated_paragraph_latest_state", "")
                if updated_content:
                    return updated_content
            
            # If extraction failed, return original cleaned text
            return cleaned_output
            
        except Exception as e:
            logger.exception(f"Output processing failed: {str(e)}")
            return "Failed to generate reflection summary"
    
    def mutate_state(self, input_data: Any, state: State, paragraph_index: int, **kwargs) -> State:
        """
        Write updated summary to state
        
        Args:
            input_data: Input data
            state: Current state
            paragraph_index: Paragraph index
            **kwargs: Additional parameters
            
        Returns:
            Updated state
        """
        try:
            # Generate updated summary
            updated_summary = self.run(input_data, **kwargs)
            
            # Update state
            if 0 <= paragraph_index < len(state.paragraphs):
                state.paragraphs[paragraph_index].research.latest_summary = updated_summary
                state.paragraphs[paragraph_index].research.increment_reflection()
                logger.info(f"Updated reflection summary for paragraph {paragraph_index}")
            else:
                raise ValueError(f"Paragraph index {paragraph_index} out of range")
            
            state.update_timestamp()
            return state
            
        except Exception as e:
            logger.exception(f"State update failed: {str(e)}")
            raise e
