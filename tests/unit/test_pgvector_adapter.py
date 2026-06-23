"""Unit tests for the PGVectorAdapter."""

import sys
from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings

from pydebeziumai.adapters.pgvector import PGVectorAdapter


@pytest.fixture
def mock_pgvector() -> Generator[MagicMock, None, None]:
    """Fixture providing a mock PGVector store and distance strategy."""
    mock_store = MagicMock()
    mock_class = MagicMock(return_value=mock_store)

    # Mock the imports of langchain_postgres
    modules = {
        "langchain_postgres": MagicMock(),
        "langchain_postgres.vectorstores": MagicMock(),
    }

    with patch.dict(sys.modules, modules):
        # Attach the mock class and distance strategy
        sys.modules["langchain_postgres"].PGVector = mock_class  # type: ignore[attr-defined]
        sys.modules["langchain_postgres.vectorstores"].DistanceStrategy = MagicMock()  # type: ignore[attr-defined]
        yield mock_class


def test_pgvector_adapter_init(mock_pgvector: MagicMock) -> None:
    """Verify that PGVectorAdapter initializes the underlying PGVector store correctly."""
    embeddings = FakeEmbeddings(size=128)
    adapter = PGVectorAdapter(
        connection_string="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
        collection_name="test_collection",
        embeddings=embeddings,
        pre_delete_collection=True,
    )

    assert adapter.connection_string == "postgresql+psycopg://postgres:secret@localhost:5432/mydb"
    assert adapter.collection_name == "test_collection"
    assert adapter.embeddings == embeddings

    # Assert that PGVector was instantiated with correct arguments
    mock_pgvector.assert_called_once_with(
        connection="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
        collection_name="test_collection",
        embeddings=embeddings,
        distance_strategy=mock_pgvector.call_args[1]["distance_strategy"],
        pre_delete_collection=True,
        use_jsonb=True,
    )


def test_pgvector_adapter_import_error() -> None:
    """Verify that PGVectorAdapter raises ImportError when langchain-postgres is not installed."""
    embeddings = FakeEmbeddings(size=128)

    # Temporarily hide langchain_postgres if it exists in sys.modules
    with patch.dict(sys.modules, {"langchain_postgres": None}):
        with pytest.raises(ImportError) as exc_info:
            PGVectorAdapter(
                connection_string="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
                collection_name="test_collection",
                embeddings=embeddings,
            )
        assert "PGVector backend requires" in str(exc_info.value)


def test_pgvector_adapter_upsert(mock_pgvector: MagicMock) -> None:
    """Verify that upsert calls add_documents on the underlying PGVector store."""
    embeddings = FakeEmbeddings(size=128)
    adapter = PGVectorAdapter(
        connection_string="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
        collection_name="test_collection",
        embeddings=embeddings,
    )

    doc = Document(page_content="Test content", id="doc_1")
    adapter.upsert(doc)

    adapter.store.add_documents.assert_called_once_with(
        documents=[doc],
        ids=["doc_1"],
    )


def test_pgvector_adapter_upsert_missing_id(mock_pgvector: MagicMock) -> None:
    """Verify that upsert raises ValueError if the document has no ID."""
    embeddings = FakeEmbeddings(size=128)
    adapter = PGVectorAdapter(
        connection_string="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
        collection_name="test_collection",
        embeddings=embeddings,
    )

    doc = Document(page_content="Test content")
    with pytest.raises(ValueError) as exc_info:
        adapter.upsert(doc)
    assert "Document ID must be provided" in str(exc_info.value)


def test_pgvector_adapter_delete(mock_pgvector: MagicMock) -> None:
    """Verify that delete calls delete on the underlying PGVector store."""
    embeddings = FakeEmbeddings(size=128)
    adapter = PGVectorAdapter(
        connection_string="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
        collection_name="test_collection",
        embeddings=embeddings,
    )

    adapter.delete("doc_1")
    adapter.store.delete.assert_called_once_with(ids=["doc_1"])


def test_pgvector_adapter_delete_handles_exception(mock_pgvector: MagicMock) -> None:
    """Verify that delete gracefully handles exceptions raised by the underlying store."""
    embeddings = FakeEmbeddings(size=128)
    adapter = PGVectorAdapter(
        connection_string="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
        collection_name="test_collection",
        embeddings=embeddings,
    )
    adapter.store.delete.side_effect = Exception("Database error")

    # This should not raise an exception
    adapter.delete("doc_1")
    adapter.store.delete.assert_called_once_with(ids=["doc_1"])


def test_pgvector_adapter_as_retriever(mock_pgvector: MagicMock) -> None:
    """Verify that as_retriever calls as_retriever on the underlying PGVector store."""
    embeddings = FakeEmbeddings(size=128)
    adapter = PGVectorAdapter(
        connection_string="postgresql+psycopg://postgres:secret@localhost:5432/mydb",
        collection_name="test_collection",
        embeddings=embeddings,
    )

    adapter.as_retriever(search_kwargs={"k": 3})
    adapter.store.as_retriever.assert_called_once_with(search_kwargs={"k": 3})
