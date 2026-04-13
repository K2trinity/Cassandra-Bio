"""
Versioned dataflow contracts (JSON Schema-like) for cross-engine consistency.

This module defines:
- Contract version
- JSON Schema dictionaries for key handoff payloads
- Lightweight validator for runtime checks
- Risk-field stripping utility for writer payload hardening
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple


CONTRACT_VERSION = "2026-04-03.v1"


BIOHARVEST_OUTPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "cassandra://contracts/bioharvest-output",
    "title": "BioHarvest Output Contract",
    "type": "object",
    "required": ["results", "stats", "data_layers", "source_payloads", "frontend_payload"],
    "properties": {
        "results": {"type": "array"},
        "stats": {"type": "object"},
        "data_layers": {"type": "object"},
        "source_payloads": {"type": "object"},
        "frontend_payload": {"type": "object"},
    },
    "additionalProperties": True,
}


WRITER_INPUT_SCHEMA: Dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "cassandra://contracts/writer-input",
    "title": "Supervisor -> Writer Input Contract",
    "type": "object",
    "required": [
        "user_query",
        "harvest_data",
        "forensic_data",
        "evidence_data",
        "output_dir",
        "compiled_evidence_text",
        "failed_count",
        "total_files",
        "analysis_status",
        "failed_files",
        "contract_version",
    ],
    "properties": {
        "user_query": {"type": "string"},
        "harvest_data": {"type": "object"},
        "forensic_data": {"type": "array"},
        "evidence_data": {"type": "array"},
        "project_name": {"type": ["string", "null"]},
        "output_dir": {"type": "string"},
        "compiled_evidence_text": {"type": "string"},
        "failed_count": {"type": "integer"},
        "total_files": {"type": "integer"},
        "analysis_status": {"type": "string"},
        "assessment_override": {"type": ["string", "null"]},
        "failed_files": {"type": "array"},
        "contract_version": {"type": "string"},
    },
    "additionalProperties": False,
}


def _is_type(value: Any, schema_type: str) -> bool:
    if schema_type == "object":
        return isinstance(value, dict)
    if schema_type == "array":
        return isinstance(value, list)
    if schema_type == "string":
        return isinstance(value, str)
    if schema_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if schema_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if schema_type == "boolean":
        return isinstance(value, bool)
    if schema_type == "null":
        return value is None
    return True


def _match_type(value: Any, schema_type: Any) -> bool:
    if isinstance(schema_type, list):
        return any(_is_type(value, t) for t in schema_type)
    return _is_type(value, schema_type)


def validate_payload(payload: Any, schema: Dict[str, Any], path: str = "$") -> List[str]:
    """Lightweight recursive validator for a subset of JSON Schema."""
    errors: List[str] = []

    expected_type = schema.get("type")
    if expected_type and not _match_type(payload, expected_type):
        errors.append(f"{path}: expected type {expected_type}, got {type(payload).__name__}")
        return errors

    if isinstance(payload, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in payload:
                errors.append(f"{path}: missing required field '{key}'")

        properties = schema.get("properties", {})
        allow_extra = schema.get("additionalProperties", True)
        for key, value in payload.items():
            if key in properties:
                errors.extend(validate_payload(value, properties[key], f"{path}.{key}"))
            elif not allow_extra:
                errors.append(f"{path}: unexpected field '{key}'")

    if isinstance(payload, list):
        item_schema = schema.get("items")
        if item_schema:
            for idx, item in enumerate(payload):
                errors.extend(validate_payload(item, item_schema, f"{path}[{idx}]"))

    return errors


def strip_risk_fields(obj: Any) -> Any:
    """
    Recursively remove keys that contain 'risk' from dict/list payloads.

    This is used to ensure risk-specific structured fields are not transmitted
    from Supervisor payload into Writer.
    """
    if isinstance(obj, dict):
        cleaned: Dict[str, Any] = {}
        for key, value in obj.items():
            if "risk" in key.lower():
                continue
            cleaned[key] = strip_risk_fields(value)
        return cleaned
    if isinstance(obj, list):
        return [strip_risk_fields(item) for item in obj]
    return obj


def validate_bioharvest_output(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = validate_payload(payload, BIOHARVEST_OUTPUT_SCHEMA)
    return len(errors) == 0, errors


def validate_writer_input(payload: Dict[str, Any]) -> Tuple[bool, List[str]]:
    errors = validate_payload(payload, WRITER_INPUT_SCHEMA)
    return len(errors) == 0, errors
