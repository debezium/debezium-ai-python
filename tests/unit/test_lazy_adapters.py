"""Unit tests verifying lazy loading of optional vector store adapters."""

import sys
from unittest.mock import patch

import pytest

import pydebeziumai.adapters


def test_adapters_module_imports_cleanly() -> None:
    """Verify that pydebeziumai.adapters can be imported even if backends are not installed."""
    # Mock missing backends
    with patch.dict(
        sys.modules,
        {
            "chromadb": None,
            "langchain_chroma": None,
            "pymilvus": None,
            "langchain_milvus": None,
            "psycopg": None,
            "langchain_postgres": None,
        },
    ):
        # Retrieve directory listing to verify attributes are present
        attrs = dir(pydebeziumai.adapters)
        assert "ChromaAdapter" in attrs
        assert "MilvusAdapter" in attrs
        assert "PGVectorAdapter" in attrs
        assert "VectorStoreAdapter" in attrs


def test_adapter_import_failure_isolated() -> None:
    """Verify that ModuleNotFoundError is only raised when a missing adapter is accessed."""
    with patch.dict(
        sys.modules,
        {
            "chromadb": None,
            "langchain_chroma": None,
            "pymilvus": None,
            "langchain_milvus": None,
            "psycopg": None,
            "langchain_postgres": None,
        },
    ):
        # Temporarily pop loaded adapter modules from cache and adapters dict to force reload
        import pydebeziumai.adapters

        for mod in [
            "pydebeziumai.adapters.chroma",
            "pydebeziumai.adapters.milvus",
            "pydebeziumai.adapters.pgvector",
        ]:
            sys.modules.pop(mod, None)
        for attr in ["ChromaAdapter", "MilvusAdapter", "PGVectorAdapter"]:
            pydebeziumai.adapters.__dict__.pop(attr, None)

        # Accessing non-existent attribute raises standard AttributeError
        with pytest.raises(AttributeError):
            _ = pydebeziumai.adapters.NonExistentAdapter

        # Accessing ChromaAdapter should attempt import and fail with ModuleNotFoundError/ImportError
        with pytest.raises((ImportError, ModuleNotFoundError)):
            _ = pydebeziumai.adapters.ChromaAdapter
