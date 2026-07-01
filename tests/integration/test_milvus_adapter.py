"""Tests for the MilvusAdapter."""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Generator

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings

from pydebeziumai.adapters.milvus import MilvusAdapter


@pytest.fixture
def milvus_adapter() -> Generator[MilvusAdapter, None, None]:
    """Fixture providing a MilvusAdapter pointing to a local Milvus Lite DB."""
    pytest.importorskip("langchain_milvus")
    pytest.importorskip("pymilvus")

    # Use a short unique DB name to satisfy Milvus Lite's < 36 characters constraint
    unique_db_path = f"/tmp/m_{uuid.uuid4().hex[:8]}.db"

    embeddings = FakeEmbeddings(size=128)
    adapter = MilvusAdapter(
        collection_name="test_collection",
        embeddings=embeddings,
        connection_uri=unique_db_path,
        drop_old=True,
    )
    yield adapter

    # Teardown: Disconnect and clean up connections to release file locks
    try:
        from pymilvus import connections

        # Try to disconnect using the specific store alias if available
        if hasattr(adapter, "store") and hasattr(adapter.store, "alias"):
            connections.disconnect(adapter.store.alias)
            connections.remove_connection(adapter.store.alias)
        connections.disconnect("default")
        connections.remove_connection("default")
    except Exception:
        pass

    if os.path.exists(unique_db_path):
        with contextlib.suppress(OSError):
            os.remove(unique_db_path)


def test_milvus_adapter_init(milvus_adapter: MilvusAdapter) -> None:
    """Verify that MilvusAdapter initializes correctly."""
    assert milvus_adapter.collection_name == "test_collection"
    assert milvus_adapter.store is not None


def test_milvus_adapter_import_error() -> None:
    """Verify that MilvusAdapter raises ImportError when langchain-milvus is not installed."""
    import sys
    from unittest.mock import patch

    embeddings = FakeEmbeddings(size=128)

    # Temporarily hide langchain_milvus
    with patch.dict(sys.modules, {"langchain_milvus": None}):
        with pytest.raises(ImportError) as exc_info:
            MilvusAdapter(
                collection_name="test_collection",
                embeddings=embeddings,
                connection_uri="/tmp/milvus_dummy.db",
            )
        assert "Milvus backend requires" in str(exc_info.value)


def test_milvus_adapter_upsert_and_delete(milvus_adapter: MilvusAdapter) -> None:
    """Verify that upsert and delete operations modify the vector store correctly."""
    doc = Document(page_content="Test content for Milvus", id="doc_123")

    # Upsert
    milvus_adapter.upsert(doc)

    # Verify retrieval
    retriever = milvus_adapter.as_retriever(search_kwargs={"k": 1})
    results = retriever.invoke("Test content")
    assert len(results) > 0
    assert results[0].page_content == "Test content for Milvus"

    # Delete
    milvus_adapter.delete("doc_123")

    # Verify deleted (similarity search should return empty or other matches)
    results_after = retriever.invoke("Test content")
    # In Milvus Lite with 1 doc, deleting it should mean 0 results
    assert len(results_after) == 0


def test_milvus_adapter_upsert_missing_id(milvus_adapter: MilvusAdapter) -> None:
    """Verify that upsert raises ValueError if the document has no ID."""
    doc = Document(page_content="Test content without ID")
    with pytest.raises(ValueError) as exc_info:
        milvus_adapter.upsert(doc)
    assert "Document ID must be provided" in str(exc_info.value)
