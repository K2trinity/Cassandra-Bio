"""
Base Node Class
Defines the base interface for all processing nodes in Cassandra
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from src.llms import GeminiClient
from ..state.state import State
from loguru import logger


class BaseNode(ABC):
    """Base node class for all Cassandra processing nodes"""

    def __init__(self, llm_client: GeminiClient, node_name: str = ""):
        """
        Initialize node

        Args:
            llm_client: LLM client instance
            node_name: Node name identifier
        """
        self.llm_client = llm_client
        self.node_name = node_name or self.__class__.__name__

    @abstractmethod
    def run(self, input_data: Any, **kwargs) -> Any:
        """
        Execute node processing logic

        Args:
            input_data: Input data
            **kwargs: Additional parameters

        Returns:
            Processing result
        """
        pass

    def validate_input(self, input_data: Any) -> bool:
        """
        Validate input data

        Args:
            input_data: Input data

        Returns:
            Whether validation passed
        """
        return True

    def process_output(self, output: Any) -> Any:
        """
        Process output data

        Args:
            output: Raw output

        Returns:
            Processed output
        """
        return output

    def log_info(self, message: str):
        """Log information message"""
        logger.info(f"[{self.node_name}] {message}")
    
    def log_warning(self, message: str):
        """Log warning message"""
        logger.warning(f"[{self.node_name}] Warning: {message}")

    def log_error(self, message: str):
        """Log error message"""
        logger.error(f"[{self.node_name}] Error: {message}")


class StateMutationNode(BaseNode):
    """Base class for nodes with state mutation capabilities"""
    
    @abstractmethod
    def mutate_state(self, input_data: Any, state: State, **kwargs) -> State:
        """
        Mutate state
        
        Args:
            input_data: Input data
            state: Current state
            **kwargs: Additional parameters
            
        Returns:
            Modified state
        """
        pass
