"""Helpers for parsing environment-style configuration values."""

import json


def as_bool(value: str | None, default: bool = False) -> bool:
    """Parse common truthy environment-style values into a boolean."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def safe_csv_set(raw_value: str | None) -> set[str]:
    """Split a comma-delimited string into a trimmed set of values."""
    if not raw_value:
        return set()
    return {part.strip() for part in raw_value.split(",") if part and part.strip()}


def safe_json_string_dict(
    value: str | None, *, default: dict[str, str] | None = None
) -> dict[str, str]:
    """Parse a JSON object and coerce its keys and values to strings."""
    if not value:
        return default or {}

    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")

    return {str(k): str(v) for k, v in parsed.items()}
