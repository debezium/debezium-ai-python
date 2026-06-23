"""Chroma vector store adapter implementation."""

from __future__ import annotations

from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

from pydebeziumai.adapters.base import VectorStoreAdapter


class ChromaAdapter(VectorStoreAdapter):
    """Vector store adapter for ChromaDB."""

    def __init__(
        self,
        collection_name: str,
        embeddings: Embeddings,
        persist_directory: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialises the ChromaAdapter.

        Args:
            collection_name: Name of the Chroma collection.
            embeddings: Embeddings model to generate vector representations.
            persist_directory: Directory to persist Chroma database files.
            **kwargs: Additional arguments forwarded to the Chroma vector store.
        """
        self._vector_store = Chroma(
            collection_name=collection_name,
            embedding_function=embeddings,
            persist_directory=persist_directory,
            **kwargs,
        )

    def upsert(self, document: Document) -> None:
        """Add or replace a document in the vector store.

        Args:
            document: The LangChain Document to upsert.
        """
        if document.id is None:
            raise ValueError("Document ID must be provided for idempotent upserts.")
        self._vector_store.add_documents([document], ids=[document.id])

    def delete(self, doc_id: str) -> None:
        """Remove a document by its stable ID.

        Args:
            doc_id: The stable ID of the document to remove.
        """
        self._vector_store.delete(ids=[doc_id])

    def as_retriever(
        self,
        *,
        metadata_filter: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BaseRetriever:
        """Return a LangChain BaseRetriever backed by this vector store.

        Args:
            metadata_filter: Optional dictionary of metadata key-values to filter by.
            **kwargs: Options for the retriever (e.g. search_kwargs={"k": 5}).

        Returns:
            A LangChain BaseRetriever.
        """
        if metadata_filter:
            if "search_kwargs" not in kwargs:
                kwargs["search_kwargs"] = {}
            existing_filter = kwargs["search_kwargs"].get("filter", {})
            if existing_filter:
                kwargs["search_kwargs"]["filter"] = {"$and": [existing_filter, metadata_filter]}
            else:
                kwargs["search_kwargs"]["filter"] = metadata_filter

        return self._vector_store.as_retriever(**kwargs)
