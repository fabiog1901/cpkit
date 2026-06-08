"""Claim normalization helpers."""

from typing import Any

from cpkit.config import safe_csv_set


def claim_groups(claim_value: Any) -> set[str]:
    """Normalize a groups claim into a trimmed set of group names."""
    if claim_value is None:
        return set()
    if isinstance(claim_value, str):
        return (
            safe_csv_set(claim_value)
            if "," in claim_value
            else ({claim_value.strip()} if claim_value.strip() else set())
        )
    if isinstance(claim_value, (list, tuple, set)):
        return {str(v).strip() for v in claim_value if str(v).strip()}
    return set()


def claims_groups(
    claims: dict[str, Any], groups_claim_name: str = "groups"
) -> set[str]:
    """Extract the configured groups claim from a JWT or synthetic claims payload."""
    return claim_groups(claims.get(groups_claim_name))


def jsonable_role_groups(role_groups: dict[Any, Any]) -> dict[str, list[str]]:
    """Convert role-to-groups mappings into JSON-friendly sorted lists."""
    normalized: dict[str, list[str]] = {}
    for role_name, groups in role_groups.items():
        normalized[str(getattr(role_name, "value", role_name))] = sorted(
            claim_groups(groups)
        )
    return normalized
