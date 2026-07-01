"""Integration tests for the Chroma adapter and synchronization pipeline."""

from __future__ import annotations

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings

from pydebeziumai.adapters.chroma import ChromaAdapter
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.sync.manager import SyncManager
from pydebeziumai.transformation.document_builder import DocumentBuilder


@pytest.fixture
def chroma_adapter() -> ChromaAdapter:
    """Fixture providing a ChromaAdapter with a fake embedding model."""
    embeddings = FakeEmbeddings(size=128)
    return ChromaAdapter(
        collection_name="test_collection",
        embeddings=embeddings,
    )


def test_chroma_adapter_basic_ops(chroma_adapter: ChromaAdapter) -> None:
    """Verify basic upsert and delete operations directly on ChromaAdapter."""
    # 1. Test upsert
    doc = Document(page_content="Test content", metadata={"key": "value"}, id="test_id_1")
    chroma_adapter.upsert(doc)

    res = chroma_adapter._vector_store.get(ids=["test_id_1"])
    assert res["ids"] == ["test_id_1"]
    assert res["documents"] == ["Test content"]
    assert res["metadatas"][0]["key"] == "value"

    # 2. Test delete
    chroma_adapter.delete("test_id_1")
    res = chroma_adapter._vector_store.get(ids=["test_id_1"])
    assert res["ids"] == []


def test_chroma_as_retriever(chroma_adapter: ChromaAdapter) -> None:
    """Verify that as_retriever returns a working LangChain retriever."""
    doc = Document(page_content="Special search term", metadata={"category": "test"}, id="test_id_retriever")
    chroma_adapter.upsert(doc)

    retriever = chroma_adapter.as_retriever(search_kwargs={"k": 1})
    results = retriever.invoke("Special search term")
    assert len(results) == 1
    assert results[0].page_content == "Special search term"
    assert results[0].id == "test_id_retriever"


def test_chroma_metadata_filtering(chroma_adapter: ChromaAdapter) -> None:
    """Verify that ChromaAdapter retrieves only filtered metadata matching documents."""
    doc_match = Document(
        page_content="Electronics topic query", metadata={"category": "electronics", "tenant": "user1"}, id="doc_match"
    )
    doc_skip = Document(
        page_content="Electronics topic query", metadata={"category": "clothing", "tenant": "user1"}, id="doc_skip"
    )
    chroma_adapter.upsert(doc_match)
    chroma_adapter.upsert(doc_skip)

    # Filter exactly category=electronics
    retriever = chroma_adapter.as_retriever(metadata_filter={"category": "electronics"}, search_kwargs={"k": 2})
    results = retriever.invoke("Electronics topic query")
    assert len(results) == 1
    assert results[0].id == "doc_match"


def test_e2e_pipeline_chroma_hard_delete(
    chroma_adapter: ChromaAdapter,
    document_builder: DocumentBuilder,
    insert_event: DebeziumEventModel,
    update_event: DebeziumEventModel,
    delete_event: DebeziumEventModel,
) -> None:
    """Verify the end-to-end sync pipeline with Chroma using hard deletes."""
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=chroma_adapter,
        soft_delete=False,
    )

    # 1. Sync Insert
    manager.sync(insert_event)
    res = chroma_adapter._vector_store.get(ids=["public.products:1"])
    assert res["ids"] == ["public.products:1"]
    assert "Widget A" in res["documents"][0]
    assert res["metadatas"][0]["_op"] == "c"

    # 2. Sync Update
    manager.sync(update_event)
    res = chroma_adapter._vector_store.get(ids=["public.products:1"])
    assert res["ids"] == ["public.products:1"]
    assert "Widget A Pro" in res["documents"][0]
    assert res["metadatas"][0]["_op"] == "u"

    # 3. Sync Delete (Hard)
    manager.sync(delete_event)
    res = chroma_adapter._vector_store.get(ids=["public.products:1"])
    assert res["ids"] == []


def test_e2e_pipeline_chroma_soft_delete(
    chroma_adapter: ChromaAdapter,
    document_builder: DocumentBuilder,
    insert_event: DebeziumEventModel,
    delete_event: DebeziumEventModel,
) -> None:
    """Verify the end-to-end sync pipeline with Chroma using soft deletes."""
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=chroma_adapter,
        soft_delete=True,
    )

    # 1. Sync Insert
    manager.sync(insert_event)
    res = chroma_adapter._vector_store.get(ids=["public.products:1"])
    assert res["ids"] == ["public.products:1"]
    assert res["metadatas"][0].get("_is_deleted") is None

    # 2. Sync Delete (Soft)
    manager.sync(delete_event)
    res = chroma_adapter._vector_store.get(ids=["public.products:1"])
    assert res["ids"] == ["public.products:1"]  # Document is still present
    assert res["metadatas"][0]["_is_deleted"] is True
    assert res["metadatas"][0]["_op"] == "d"
    assert "Widget A Pro" in res["documents"][0]
