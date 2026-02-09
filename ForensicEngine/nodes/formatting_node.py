"""
Report Formatting Node
Responsible for formatting final research results into elegant Markdown reports
"""

import json
from typing import List, Dict, Any
from loguru import logger

from .base_node import BaseNode
from ..prompts import SYSTEM_PROMPT_REPORT_FORMATTING
from ..utils.text_processing import (
    remove_reasoning_from_output,
    clean_markdown_tags
)


class ReportFormattingNode(BaseNode):
    """Node for formatting final research reports"""
    
    def __init__(self, llm_client):
        """
        Initialize report formatting node
        
        Args:
            llm_client: LLM client instance
        """
        super().__init__(llm_client, "ReportFormattingNode")
    
    def validate_input(self, input_data: Any) -> bool:
        """Validate input data"""
        if isinstance(input_data, str):
            try:
                data = json.loads(input_data)
                return isinstance(data, list) and all(
                    isinstance(item, dict) and "title" in item and "paragraph_latest_state" in item
                    for item in data
                )
            except:
                return False
        elif isinstance(input_data, list):
            return all(
                isinstance(item, dict) and "title" in item and "paragraph_latest_state" in item
                for item in input_data
            )
        return False
    
    def run(self, input_data: Any, **kwargs) -> str:
        """
        Invoke LLM to generate Markdown format report
        
        Args:
            input_data: List containing all paragraph information
            **kwargs: Additional parameters
            
        Returns:
            Formatted Markdown report
        """
        try:
            if not self.validate_input(input_data):
                raise ValueError("Invalid input data format, requires list with title and paragraph_latest_state")
            
            # Prepare input data
            if isinstance(input_data, str):
                message = input_data
            else:
                message = json.dumps(input_data, ensure_ascii=False)
            
            logger.info("Formatting final report")
            
            # Invoke LLM to generate Markdown format (streaming, safe UTF-8 concatenation)
            response = self.llm_client.stream_invoke_to_string(
                SYSTEM_PROMPT_REPORT_FORMATTING,
                message,
            )
            
            # Process response
            processed_response = self.process_output(response)
            
            logger.info("Successfully generated formatted report")
            return processed_response
            
        except Exception as e:
            logger.exception(f"Report formatting failed: {str(e)}")
            raise e
    
    def process_output(self, output: str) -> str:
        """
        Process LLM output and clean Markdown format
        
        Args:
            output: Raw LLM output
            
        Returns:
            Cleaned Markdown report
        """
        try:
            # Clean response text
            cleaned_output = remove_reasoning_from_output(output)
            cleaned_output = clean_markdown_tags(cleaned_output)
            
            # Ensure report has basic structure
            if not cleaned_output.strip():
                return "# Report Generation Failed\n\nUnable to generate valid report content."
            
            # If no title, add a default title
            if not cleaned_output.strip().startswith('#'):
                cleaned_output = "# Forensic Research Report\n\n" + cleaned_output
            
            return cleaned_output.strip()
            
        except Exception as e:
            logger.exception(f"Output processing failed: {str(e)}")
            return "# Report Processing Failed\n\nAn error occurred during report formatting."
    
    def format_report_manually(self, paragraphs_data: List[Dict[str, str]], 
                             report_title: str = "Forensic Research Report") -> str:
        """
        Manually format report (fallback method)
        
        Args:
            paragraphs_data: List of paragraph data
            report_title: Report title
            
        Returns:
            Formatted Markdown report
        """
        try:
            logger.info("Using manual formatting method")
            
            # Build report
            report_lines = [
                f"# {report_title}",
                "",
                "---",
                ""
            ]
            
            # Add all paragraphs
            for i, paragraph in enumerate(paragraphs_data, 1):
                title = paragraph.get("title", f"Paragraph {i}")
                content = paragraph.get("paragraph_latest_state", "")
                
                if content:
                    report_lines.extend([
                        f"## {title}",
                        "",
                        content,
                        "",
                        "---",
                        ""
                    ])
            
            # Add conclusion
            if len(paragraphs_data) > 1:
                report_lines.extend([
                    "## Conclusion",
                    "",
                    "This forensic research report provides comprehensive analysis through systematic literature review and evidence synthesis. "
                    "The findings presented above offer critical insights for due diligence assessment.",
                    ""
                ])
            
            return "\n".join(report_lines)
            
        except Exception as e:
            logger.exception(f"Manual formatting failed: {str(e)}")
            return "# Report Generation Failed\n\nUnable to complete report formatting."
