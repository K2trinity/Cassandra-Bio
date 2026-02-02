# -*- coding: utf-8 -*-
"""
Cassandra - Biomedical Due Diligence Configuration

This module uses pydantic-settings to manage global configuration with automatic
loading from environment variables and .env files.

Architecture:
- Google Gemini 3.0 Pro: Primary Intelligence Layer (Global Leader)
- Neo4j: Knowledge Graph Database
- Redis: State Management & Caching
- Flask: REST API Server
- PubMed/Tavily: External Research Tools
"""

from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field, ConfigDict
from typing import Optional


# Determine .env file priority: prioritize current working directory, fallback to project root
PROJECT_ROOT: Path = Path(__file__).resolve().parent
CWD_ENV: Path = Path.cwd() / ".env"
ENV_FILE: str = str(CWD_ENV if CWD_ENV.exists() else (PROJECT_ROOT / ".env"))


class Settings(BaseSettings):
    """
    Global configuration with automatic loading from .env and environment variables.
    All variable names use UPPERCASE for consistency and easy environment overrides.
    """
    
    # ================== Section 1: Server Configuration ====================
    HOST: str = Field(
        "0.0.0.0",
        description="Flask server host address (0.0.0.0 for all interfaces, 127.0.0.1 for localhost only)"
    )
    PORT: int = Field(
        5000,
        description="Flask server port (mapped to 7897 in docker-compose)"
    )

    # ================== Section 2: Infrastructure (Database & Cache) ====================
    # Neo4j Knowledge Graph Configuration
    NEO4J_URI: str = Field(
        "bolt://neo4j:7687",
        description="Neo4j connection URI (Bolt protocol)"
    )
    NEO4J_USER: str = Field(
        "neo4j",
        description="Neo4j database username"
    )
    NEO4J_PASSWORD: str = Field(
        "password",
        description="Neo4j database password"
    )
    
    # Redis State Management Configuration
    REDIS_URL: str = Field(
        "redis://localhost:6379/0",
        description="Redis connection URL for state management and caching (use 'redis:6379' in Docker)"
    )
    
    # ================== Section 3: Intelligence Layer (Google Gemini) ====================
    # Primary API Key (Required for all engines)
    GOOGLE_API_KEY: Optional[str] = Field(
        None,
        description="Google Gemini API Key (obtain from https://ai.google.dev/)"
    )
    
    # BioHarvest Engine - PubMed/Clinical Trials Literature Search
    BIOHARVEST_MODEL_NAME: str = Field(
        "gemini-2.5-flash",
        description="BioHarvest engine model for fast literature retrieval (Fast & intelligent)"
    )
    BIOHARVEST_TEMPERATURE: float = Field(
        0.3,
        description="BioHarvest sampling temperature (lower for precise search queries)"
    )
    BIOHARVEST_MAX_TOKENS: int = Field(
        4096,
        description="BioHarvest maximum output tokens"
    )
    
    # Evidence Engine - PDF Document Mining & Dark Data Extraction
    EVIDENCE_MODEL_NAME: str = Field(
        "gemini-2.5-pro",
        description="Evidence engine model for long-context PDF analysis (Advanced reasoning)"
    )
    EVIDENCE_TEMPERATURE: float = Field(
        0.4,
        description="Evidence sampling temperature (balanced for fact extraction)"
    )
    EVIDENCE_MAX_TOKENS: int = Field(
        8192,
        description="Evidence maximum output tokens (supports long-form analysis)"
    )
    
    # Forensic Engine - Image Forensics & Multimodal Scientific Analysis
    FORENSIC_MODEL_NAME: str = Field(
        "gemini-3-pro-preview",
        description="Forensic engine model for multimodal vision analysis (Gemini 3 Pro Preview)"
    )
    FORENSIC_TEMPERATURE: float = Field(
        0.2,
        description="Forensic sampling temperature (low for rigorous forensic tasks)"
    )
    FORENSIC_MAX_TOKENS: int = Field(
        4096,
        description="Forensic maximum output tokens"
    )
    
    # Report Engine - Biomedical Due Diligence Report Generation
    REPORT_MODEL_NAME: str = Field(
        "gemini-3-pro-preview",
        description="Report engine model for comprehensive report synthesis (Gemini 3 Pro Preview)"
    )
    REPORT_TEMPERATURE: float = Field(
        0.7,
        description="Report sampling temperature (higher for natural language generation)"
    )
    REPORT_MAX_TOKENS: int = Field(
        8192,
        description="Report maximum output tokens (supports long-form reports)"
    )
    
    # ================== Section 4: External Tools ====================
    # Tavily Web Search API
    TAVILY_API_KEY: Optional[str] = Field(
        None,
        description="Tavily API key for web search capabilities (obtain from https://www.tavily.com/)"
    )
    
    # PubMed API Configuration
    PUBMED_EMAIL: Optional[str] = Field(
        None,
        description="Email address for PubMed API identification (required by NCBI)"
    )
    
    # Pydantic Settings Configuration
    model_config = ConfigDict(
        env_file=ENV_FILE,
        env_prefix="",
        case_sensitive=False,
        extra="allow"
    )


# Create global configuration instance
settings = Settings()


def reload_settings() -> Settings:
    """
    Reload configuration from .env file and environment variables.
    
    This function recreates the global settings instance, useful for
    dynamically updating configuration at runtime.
    
    Returns:
        Settings: Newly created configuration instance
    """
    global settings
    settings = Settings()
    return settings
