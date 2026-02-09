"""
Report Structure Generation Node
Responsible for generating the overall report structure based on query
"""

import json
from typing import Dict, Any, List
from json.decoder import JSONDecodeError
from loguru import logger

from .base_node import StateMutationNode
from ..state.state import State
from ..prompts import SYSTEM_PROMPT_REPORT_STRUCTURE
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_json_tags,
    extract_clean_response,
    fix_incomplete_json
)


class ReportStructureNode(StateMutationNode):
    """Node for generating report structure"""
    
    def __init__(self, llm_client, query: str):
        """
        Initialize report structure node
        
        Args:
            llm_client: LLM client instance
            query: User query
        """
        super().__init__(llm_client, "ReportStructureNode")
        self.query = query
    
    def validate_input(self, input_data: Any) -> bool:
        """Validate input data"""
        return isinstance(self.query, str) and len(self.query.strip()) > 0
    
    def run(self, input_data: Any = None, **kwargs) -> List[Dict[str, str]]:
        """
        Invoke LLM to generate report structure
        
        Args:
            input_data: Input data (not used here, uses query from initialization)
            **kwargs: Additional parameters
            
        Returns:
            Report structure list
        """
        try:
            logger.info(f"Generating report structure for query: {self.query}")
            
            # Invoke LLM
            response = self.llm_client.stream_invoke_to_string(SYSTEM_PROMPT_REPORT_STRUCTURE, self.query)
            
            # Process response
            processed_response = self.process_output(response)
            
            logger.info(f"Successfully generated {len(processed_response)} paragraph structures")
            return processed_response
            
        except Exception as e:
            logger.exception(f"Report structure generation failed: {str(e)}")
            raise e
    
    def process_output(self, output: str) -> List[Dict[str, str]]:
        """
        Process LLM output and extract report structure
        
        Args:
            output: Raw LLM output
            
        Returns:
            Processed report structure list
        """
        try:
            # Clean response text
            cleaned_output = remove_reasoning_from_output(output)
            cleaned_output = clean_json_tags(cleaned_output)
            
            # Log cleaned output for debugging
            logger.info(f"Cleaned output: {cleaned_output}")
            
            # Parse JSON
            try:
                report_structure = json.loads(cleaned_output)
                logger.info("JSON parsing succeeded")
            except JSONDecodeError as e:
                logger.error(f"JSON parsing failed: {str(e)}")
                # Use more robust extraction method
                report_structure = extract_clean_response(cleaned_output)
                if "error" in report_structure:
                    logger.error("JSON parsing failed, attempting repair...")
                    # Attempt JSON repair
                    fixed_json = fix_incomplete_json(cleaned_output)
                    if fixed_json:
                        try:
                            report_structure = json.loads(fixed_json)
                            logger.info("JSON repair succeeded")
                        except JSONDecodeError:
                            logger.error("JSON repair failed")
                            # Return default structure
                            return self._generate_default_structure()
                    else:
                        logger.error("Cannot repair JSON, using default structure")
                        return self._generate_default_structure()
            
            # Validate structure
            if not isinstance(report_structure, list):
                logger.info("Report structure is not a list, attempting conversion...")
                if isinstance(report_structure, dict):
                    # If single object, wrap in list
                    report_structure = [report_structure]
                else:
                    logger.error("Invalid report structure format, using default structure")
                    return self._generate_default_structure()
            
            # Validate each paragraph
            validated_structure = []
            for i, paragraph in enumerate(report_structure):
                if not isinstance(paragraph, dict):
                    logger.warning(f"Paragraph {i+1} is not in dict format, skipping")
                    continue
                
                title = paragraph.get("title", f"Paragraph {i+1}")
                content = paragraph.get("content", "")
                
                if not title or not content:
                    logger.warning(f"Paragraph {i+1} missing title or content, skipping")
                    continue
                
                validated_structure.append({
                    "title": title,
                    "content": content
                })
            
            if not validated_structure:
                logger.warning("No valid paragraph structure, using default structure")
                return self._generate_default_structure()
            
            logger.info(f"Successfully validated {len(validated_structure)} paragraph structures")
            return validated_structure
            
        except Exception as e:
            logger.exception(f"Output processing failed: {str(e)}")
            return self._generate_default_structure()
    
    def _generate_default_structure(self) -> List[Dict[str, str]]:
        """
        Generate default report structure
        
        Returns:
            Default report structure list
        """
        logger.info("Generating default report structure")
        return [
            {
                "title": "Research Overview",
                "content": "Comprehensive overview and analysis of the biomedical research topic"
            },
            {
                "title": "In-depth Analysis",
                "content": "Detailed examination of key aspects including clinical evidence, risk factors, and scientific findings"
            }
        ]
    
    def mutate_state(self, input_data: Any = None, state: State = None, **kwargs) -> State:
        """
        Write report structure to state
        
        Args:
            input_data: Input data
            state: Current state, creates new state if None
            **kwargs: Additional parameters
            
        Returns:
            Updated state
        """
        if state is None:
            state = State()
        
        try:
            # Generate report structure
            report_structure = self.run(input_data, **kwargs)
            
            # Set query and report title
            state.query = self.query
            if not state.report_title:
                state.report_title = f"Forensic Research Report: {self.query}"
            
            # Add paragraphs to state
            for paragraph_data in report_structure:
                state.add_paragraph(
                    title=paragraph_data["title"],
                    content=paragraph_data["content"]
                )
            
            logger.info(f"Added {len(report_structure)} paragraphs to state")
            return state
            
        except Exception as e:
            logger.exception(f"State update failed: {str(e)}")
            raise e
