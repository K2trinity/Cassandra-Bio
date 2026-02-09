"""
Cassandra Evidence Miner - Text Processing Utilities
Handles LLM output cleaning, JSON parsing, and response extraction for PDF evidence analysis
"""

import re
import json
from typing import Dict, Any, List
from json.decoder import JSONDecodeError


def clean_json_tags(text: str) -> str:
    """
    Remove JSON code fence tags from text
    
    Args:
        text: Raw text string
        
    Returns:
        Cleaned text without JSON markers
    """
    # Remove ```json and ``` tags
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = re.sub(r'```', '', text)
    
    return text.strip()


def clean_markdown_tags(text: str) -> str:
    """
    Remove Markdown code fence tags from text
    
    Args:
        text: Raw text string
        
    Returns:
        Cleaned text without Markdown markers
    """
    # Remove ```markdown and ``` tags
    text = re.sub(r'```markdown\s*', '', text)
    text = re.sub(r'```\s*$', '', text)
    text = re.sub(r'```', '', text)
    
    return text.strip()


def remove_reasoning_from_output(text: str) -> str:
    """
    Remove reasoning/explanation text preceding JSON output from LLM responses
    
    Args:
        text: Raw LLM output text
        
    Returns:
        Cleaned text with only JSON content
    """
    # Find JSON starting position
    json_start = -1
    
    # Try to find first { or [
    for i, char in enumerate(text):
        if char in '{[':
            json_start = i
            break
    
    if json_start != -1:
        # Extract from JSON start position
        return text[json_start:].strip()
    
    # If no JSON markers found, try alternative methods
    # Remove common reasoning identifiers
    patterns = [
        r'(?:reasoning|推理|思考|分析)[:：]\s*.*?(?=\{|\[)',  # Remove reasoning sections
        r'(?:explanation|解释|说明)[:：]\s*.*?(?=\{|\[)',   # Remove explanation sections
        r'^.*?(?=\{|\[)',  # Remove all text before JSON
    ]
    
    for pattern in patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    
    return text.strip()


def extract_clean_response(text: str) -> Dict[str, Any]:
    """
    Extract and clean JSON content from LLM response
    
    Args:
        text: Raw response text
        
    Returns:
        Parsed JSON dictionary
    """
    # Clean text
    cleaned_text = clean_json_tags(text)
    cleaned_text = remove_reasoning_from_output(cleaned_text)
    
    # Try direct parsing
    try:
        return json.loads(cleaned_text)
    except JSONDecodeError:
        pass
    
    # Try fixing incomplete JSON
    fixed_text = fix_incomplete_json(cleaned_text)
    if fixed_text:
        try:
            return json.loads(fixed_text)
        except JSONDecodeError:
            pass
    
    # Try finding JSON object
    json_pattern = r'\{.*\}'
    match = re.search(json_pattern, cleaned_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except JSONDecodeError:
            pass
    
    # Try finding JSON array
    array_pattern = r'\[.*\]'
    match = re.search(array_pattern, cleaned_text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except JSONDecodeError:
            pass
    
    # If all methods fail, return error information
    print(f"Failed to parse JSON response: {cleaned_text[:200]}...")
    return {"error": "JSON parsing failed", "raw_text": cleaned_text}
    """
    Fix incomplete JSON responses with missing brackets/braces
    
    Args:
        text: Raw text string
        
    Returns:
        Fixed JSON text string, or empty string if unable to repair
    """
    # Remove trailing commas and whitespace
    text = re.sub(r',\s*}', '}', text)
    text = re.sub(r',\s*]', ']', text)
    
    # Check if already valid JSON
    try:
        json.loads(text)
        return text
    except JSONDecodeError:
        pass
    
    # Check if missing opening array bracket
    if text.strip().startswith('{') and not text.strip().startswith('['):
        # If starting with object, try wrapping in array
        if text.count('{') > 1:
            # Multiple objects, wrap in array
            text = '[' + text + ']'
        else:
            # Single object, wrap in array
            text = '[' + text + ']'
    
    # Check if missing closing array bracket
    if text.strip().endswith('}') and not text.strip().endswith(']'):
        # If ending with object, try wrapping in array
        if text.count('}') > 1:
            # Multiple objects, wrap in array
            text = '[' + text + ']'
        else:
            # Single object, wrap in array
            text = '[' + text + ']'
    
    # Check bracket balance
    open_braces = text.count('{')
    close_braces = text.count('}')
    open_brackets = text.count('[')
    close_brackets = text.count(']')
    
    # Fix mismatched brackets
    if open_braces > close_braces:
        text += '}' * (open_braces - close_braces)
    if open_brackets > close_brackets:
        text += ']' * (open_brackets - close_brackets)
    
    # Validate fixed JSON
    try:
        json.loads(text)
        return text
    except JSONDecodeError:
        # If still invalid, try aggressive repair
        return fix_aggressive_json(text)


def fix_aggressive_json(text: str) -> str:
    """
    Aggressive JSON repair method for severely malformed responses
    
    Args:
        text: Raw text string
        
    Returns:
        Repaired JSON text
    """
    # Find all potential JSON objects
    objects = re.findall(r'\{[^{}]*\}', text)
    
    if len(objects) >= 2:
        # If multiple objects found, wrap in array
        return '[' + ','.join(objects) + ']'
    elif len(objects) == 1:
        # If single object found, wrap in array
        return '[' + objects[0] + ']'
    else:
        # If no objects found, return empty array
        return '[]'


def update_state_with_search_results(search_results: List[Dict[str, Any]], 
                                   paragraph_index: int, state: Any) -> Any:
    """
    Update state with search results from PDF evidence queries
    
    Args:
        search_results: List of search results from PDF evidence sources
        paragraph_index: Index of target paragraph/section
        state: State object for report workflow
        
    Returns:
        Updated state object
    """
    if 0 <= paragraph_index < len(state.paragraphs):
        # Get last search query (assume current query)
        current_query = ""
        if search_results:
            # Infer query from search results (needs improvement to get actual query)
            current_query = "Search query"
        
        # Add search results to state
        state.paragraphs[paragraph_index].research.add_search_results(
            current_query, search_results
        )
    
    return state


def validate_json_schema(data: Dict[str, Any], required_fields: List[str]) -> bool:
    """
    Validate JSON data contains required fields
    
    Args:
        data: Data to validate
        required_fields: List of required field names
        
    Returns:
        True if validation passes, False otherwise
    """
    return all(field in data for field in required_fields)


def truncate_content(content: str, max_length: int = 20000) -> str:
    """
    Truncate content to specified length with word boundary awareness
    
    Args:
        content: Original content string
        max_length: Maximum allowed length
        
    Returns:
        Truncated content with ellipsis if needed
    """
    if len(content) <= max_length:
        return content
    
    # Try to truncate at word boundary
    truncated = content[:max_length]
    last_space = truncated.rfind(' ')
    
    if last_space > max_length * 0.8:  # If last space position is reasonable
        return truncated[:last_space] + "..."
    else:
        return truncated + "..."


def format_search_results_for_prompt(search_results: List[Dict[str, Any]], 
                                   max_length: int = 20000) -> List[str]:
    """
    Format PDF evidence results for LLM prompt construction
    
    Args:
        search_results: List of search results from PDF evidence sources
        max_length: Maximum length per result
        
    Returns:
        List of formatted content strings ready for prompt injection
    """
    formatted_results = []
    
    for result in search_results:
        content = result.get('content', '')
        if content:
            truncated_content = truncate_content(content, max_length)
            formatted_results.append(truncated_content)
    
    return formatted_results
