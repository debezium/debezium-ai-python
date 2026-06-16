"""Unit tests for retrieval layer and LangGraph node helpers."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from pydebeziumai.adapters.base import VectorStoreAdapter
from pydebeziumai.retrieval.langgraph import create_retriever_node, create_retriever_tool


class MockRetriever(BaseRetriever):
    """Mock LangChain retriever for testing."""

    mock_docs: list[Document]

    def _get_relevant_documents(self, query: str, *, run_manager: Any = None) -> list[Document]:
        return self.mock_docs


class MockAdapter(VectorStoreAdapter):
    """Mock vector store adapter to pass to helpers."""

    def __init__(self, mock_docs: list[Document]) -> None:
        self.retriever = MockRetriever(mock_docs=mock_docs)

    def upsert(self, document: Document) -> None:
        pass

    def delete(self, doc_id: str) -> None:
        pass

    def as_retriever(self, **kwargs: Any) -> BaseRetriever:
        return self.retriever


class MockMessage:
    """Mock message class resembling LangChain's HumanMessage/AIMessage."""

    def __init__(self, content: str) -> None:
        self.content = content


class MockStateObject:
    """Mock state object class to test attribute extraction."""

    def __init__(self, query: str) -> None:
        self.query = query


@pytest.fixture
def mock_documents() -> list[Document]:
    """Fixture returning sample documents."""
    return [
        Document(page_content="Apple is a fruit.", metadata={"source": "db.fruits"}),
        Document(page_content="Carrot is a vegetable.", metadata={"source": "db.vegetables"}),
    ]


@pytest.fixture
def mock_adapter(mock_documents: list[Document]) -> MockAdapter:
    """Fixture returning a mock adapter configured with sample documents."""
    return MockAdapter(mock_documents)


def test_create_retriever_tool(mock_adapter: MockAdapter) -> None:
    """Test that create_retriever_tool generates a Tool with correct behaviors."""
    tool = create_retriever_tool(
        adapter=mock_adapter,
        name="test_tool",
        description="A test tool to retrieve information",
    )

    assert tool.name == "test_tool"
    assert tool.description == "A test tool to retrieve information"

    # Invoke tool and check formatting
    res = tool.invoke("test query")
    assert "Apple is a fruit." in res
    assert "Carrot is a vegetable." in res


def test_create_retriever_node_dict_query(mock_adapter: MockAdapter, mock_documents: list[Document]) -> None:
    """Test create_retriever_node with query key in a dict state."""
    node = create_retriever_node(mock_adapter, state_key="results", query_key="search_term")

    state = {"search_term": "query info"}
    output = node(state)

    assert isinstance(output, dict)
    assert "results" in output
    assert output["results"] == mock_documents


def test_create_retriever_node_dict_messages(mock_adapter: MockAdapter, mock_documents: list[Document]) -> None:
    """Test create_retriever_node with a messages key in a dict state."""
    node = create_retriever_node(mock_adapter, state_key="results")

    state: dict[str, Any] = {
        "messages": [
            MockMessage("hello"),
            MockMessage("tell me about vegetables"),
        ]
    }
    output = node(state)

    assert output["results"] == mock_documents


def test_create_retriever_node_object_query(mock_adapter: MockAdapter, mock_documents: list[Document]) -> None:
    """Test create_retriever_node with an object state and attribute query."""
    node = create_retriever_node(mock_adapter, state_key="results", query_key="query")

    state = MockStateObject("custom query text")
    output = node(state)

    assert output["results"] == mock_documents


def test_create_retriever_node_custom_extractor(mock_adapter: MockAdapter, mock_documents: list[Document]) -> None:
    """Test create_retriever_node with a custom query extractor function."""
    node = create_retriever_node(
        mock_adapter,
        state_key="results",
        query_extractor=lambda s: s["nested"]["query_value"],
    )

    state = {
        "nested": {
            "query_value": "extracted text",
        }
    }
    output = node(state)

    assert output["results"] == mock_documents


def test_create_retriever_node_invalid_query_type(mock_adapter: MockAdapter) -> None:
    """Test create_retriever_node raises ValueError when the extracted query is not a string."""
    node = create_retriever_node(mock_adapter, query_key="search")

    state = {"search": 12345}  # Integer instead of string

    with pytest.raises(ValueError, match="Extracted query must be a string"):
        node(state)
