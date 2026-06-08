"""Redirect target validation helpers."""


def safe_next_path(next_path: str | None) -> str:
    """Normalize redirect targets so only in-app absolute paths are allowed."""
    if not next_path:
        return "/"
    if not next_path.startswith("/"):
        return "/"
    if next_path.startswith("//"):
        return "/"
    return next_path
