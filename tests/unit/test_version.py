"""Tests for pydebeziumai version and metadata."""

import pydebeziumai


def test_version() -> None:
    """Verifies that the package version is correct."""
    assert pydebeziumai.__version__ == "0.1.0"
