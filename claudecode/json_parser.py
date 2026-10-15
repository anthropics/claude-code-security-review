#!/usr/bin/env python3
"""Utilities for parsing JSON from text output."""

import json
import re
import logging

# Configure logging
logger = logging.getLogger(__name__)


def extract_json_from_text(text):
    """
    Extract JSON object from text, looking in various formats and locations.
    
    Args:
        text: The text that may contain JSON
        
    Returns:
        dict: Parsed JSON object if found, None otherwise
    """
    try:
        # First, try to extract JSON from markdown code blocks (with or without language tag)
        json_matches = [
            re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL),
            re.search(r'```\s*(\{.*?\})\s*```', text, re.DOTALL)
        ]
        
        for json_match in json_matches:
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    continue
        
        # If no JSON found in code blocks, try to find JSON objects anywhere in the text
        for potential_json in _iter_brace_delimited_objects(text):
            try:
                return json.loads(potential_json)
            except json.JSONDecodeError:
                # This wasn't valid JSON, continue looking
                continue
    except Exception:
        pass
    
    return None


def _iter_brace_delimited_objects(text):
    """
    Yield each top-level ``{...}`` span in `text`, outermost first.

    Braces inside JSON string literals are ignored. Claude's findings quote
    source code, so a description mentioning a lone ``}`` would otherwise close
    the object early; the truncated candidate then failed to parse and the
    counter went negative, so the real closing brace never matched and the
    entire payload was reported as invalid JSON - silently dropping findings.

    Args:
        text: The text to scan

    Yields:
        str: Substrings that start with '{' and end with the matching '}'
    """
    brace_count = 0
    json_start = -1
    in_string = False
    escaped = False

    for i, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == '{':
            if brace_count == 0:
                json_start = i
            brace_count += 1
        elif char == '}':
            # Guarded so a stray '}' in prose can't drive the count negative
            # and disable matching for the rest of the text.
            if brace_count > 0:
                brace_count -= 1
                if brace_count == 0 and json_start != -1:
                    yield text[json_start:i + 1]
                    json_start = -1


def parse_json_with_fallbacks(text, error_context=""):
    """
    Parse JSON from text with multiple fallback strategies and error handling.
    
    Args:
        text: The text to parse
        error_context: Context string for error messages
        
    Returns:
        tuple: (success, result) where result is either the parsed JSON dict or error info
    """
    try:
        # First, try direct JSON parsing
        return True, json.loads(text)
    except json.JSONDecodeError:
        pass
    
    # Try extracting JSON from text
    # `is not None`, not truthiness: `{}` and `[]` are valid JSON and a
    # legitimate "nothing to report" response, not a parse failure.
    extracted_json = extract_json_from_text(text)
    if extracted_json is not None:
        return True, extracted_json
    
    # If all parsing failed, return error info
    error_msg = "Failed to parse JSON"
    if error_context:
        error_msg = f"{error_context}: {error_msg}"
    
    logger.error(f"{error_msg}. Raw output: {repr(text)}")
    return False, {"error": f"Invalid JSON response -- raw output: {repr(text)}"}