"""Prompt templates for BioHarvest query parsing."""

QUERY_PARSING_PROMPT = """You are a biomedical research expert analyzing investigative queries for objective evidence collection.

USER QUERY: \"{user_query}\"

Your task is to identify the core biomedical entity (drug, disease, gene, or target) and generate 3 specific search queries for each database to maximize objective evidence coverage.

1. core_entity: Extract ONLY the core biomedical term(s) (e.g., disease, drug, or gene).
   - Example: for \"conduct a comprehensive survey on Alzheimer\", core_entity is \"Alzheimer\".
   - Avoid action verbs and conversational words.
2. pubmed queries:
   - Keep queries SIMPLE and CONCISE (2-4 keywords max)
   - MUST include the extracted core_entity
   - Favor short search terms over long phrases
3. clinicaltrials queries:
   - Use drug names, company names, or therapy types
   - MUST include the core_entity
   - Keep queries concise and entity-focused

Return your response in this EXACT JSON format:
{{
  \"core_entity\": \"extracted core term\",
  \"pubmed\": [\"short query 1\", \"short query 2\", \"short query 3\"],
  \"clinicaltrials\": [\"query1\", \"query2\", \"query3\"]
}}

Only respond with valid JSON, no additional text."""
