"""Packaged cpkit resource files."""

from importlib.resources import files
from pathlib import Path


def cpkit_resources_directory() -> Path:
    """Return the filesystem directory containing packaged cpkit resources."""
    return Path(str(files(__package__)))


def cpkit_ddl_path() -> Path:
    """Return the packaged framework DDL path."""
    return cpkit_resources_directory() / "ddl.sql"


__all__ = ["cpkit_ddl_path", "cpkit_resources_directory"]
