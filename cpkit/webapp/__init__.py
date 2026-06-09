"""Packaged cpkit template webapp assets."""

from importlib.resources import files
from pathlib import Path


def template_webapp_directory() -> Path:
    """Return the filesystem directory containing the cpkit template webapp."""
    return Path(str(files(__package__)))


__all__ = ["template_webapp_directory"]
