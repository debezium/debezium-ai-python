"""LangGraph integration for PyDebeziumAI vector store adapters."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from langchain_core.tools import BaseTool, Tool

from pydebeziumai.adapters.base import VectorStoreAdapter

logger = logging.getLogger(__name__)


def create_retriever_tool(
    adapter: VectorStoreAdapter,
    name: str,
    description: str,
    **kwargs: Any,
) -> BaseTool:
    """Create a LangChain Tool backed by the VectorStoreAdapter.

    This tool is designed to be passed to LangGraph agents or standard LangChain
    agent executors.

    Args:
        adapter: The VectorStoreAdapter instance to query.
        name: Name of the tool.
        description: Description of what the tool does and when to call it.
        **kwargs: Additional parameters passed to adapter.as_retriever().

    Returns:
        A LangChain Tool instance.
    """
    retriever = adapter.as_retriever(**kwargs)
    try:
        from langchain.tools.retriever import create_retriever_tool as langchain_create_tool

        # Note: langchain's create_retriever_tool accepts a BaseRetriever
        return langchain_create_tool(retriever, name, description)
    except ImportError:
        logger.debug("langchain.tools.retriever not available. Falling back to custom Tool.")

        def retrieve(query: str) -> str:
            """Call the retriever with the query and format results."""
            docs = retriever.invoke(query)
            formatted_docs = []
            for i, doc in enumerate(docs):
                source = doc.metadata.get("source", "unknown")
                formatted_docs.append(f"Document {i + 1} (Source: {source}):\n{doc.page_content}")
            return "\n\n".join(formatted_docs)

        return Tool(
            name=name,
            description=description,
            func=retrieve,
        )


def create_retriever_node(
    adapter: VectorStoreAdapter,
    state_key: str = "documents",
    query_key: str = "query",
    query_extractor: Callable[[Any], str] | None = None,
    **retriever_kwargs: Any,
) -> Callable[[Any], dict[str, Any]]:
    """Create a LangGraph-compatible node that queries the VectorStoreAdapter.

    This node executes the retrieval query and updates the graph state with the
    resulting list of Document objects under the specified state_key.

    Args:
        adapter: The VectorStoreAdapter instance.
        state_key: The key in the returned state dictionary where retrieved documents will be stored.
        query_key: The key in the input state where the search query string is stored.
                   Only used if query_extractor is None.
        query_extractor: An optional callable that extracts the query string from the graph state.
                         If provided, it overrides query_key.
        **retriever_kwargs: Options passed to adapter.as_retriever() (e.g. search_kwargs).

    Returns:
        A callable node function for LangGraph.
    """
    retriever = adapter.as_retriever(**retriever_kwargs)

    def node_fn(state: Any) -> dict[str, Any]:
        if query_extractor is not None:
            query = query_extractor(state)
        elif isinstance(state, dict):
            if query_key in state:
                query = state[query_key]
            elif "messages" in state and len(state["messages"]) > 0:
                # Smart extraction from standard messages list
                last_msg = state["messages"][-1]
                if hasattr(last_msg, "content"):
                    query = last_msg.content
                elif isinstance(last_msg, dict):
                    query = last_msg.get("content", "")
                else:
                    query = str(last_msg)
            else:
                query = ""
        else:
            # If state is an object/Pydantic model
            query = getattr(state, query_key, "")

        if not isinstance(query, str):
            raise ValueError(f"Extracted query must be a string, got {type(query)}")

        documents = retriever.invoke(query)
        return {state_key: documents}

    return node_fn
