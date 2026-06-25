"""Milvus vector store adapter implementation."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

from pydebeziumai.adapters.base import VectorStoreAdapter

logger = logging.getLogger(__name__)


class MilvusAdapter(VectorStoreAdapter):
    """Vector store adapter for Milvus."""

    def __init__(
        self,
        collection_name: str,
        embeddings: Embeddings,
        connection_uri: str = "http://localhost:19530",
        drop_old: bool = False,
        **kwargs: Any,
    ) -> None:
        """Initialises the MilvusAdapter.

        Args:
            collection_name: Name of the Milvus collection.
            embeddings: Embeddings model to generate vector representations.
            connection_uri: Connection URI for the Milvus instance (default http://localhost:19530).
            drop_old: Drop and recreate collection on init (default False).
            **kwargs: Additional arguments forwarded to the Milvus vector store.
        """
        self.collection_name = collection_name
        self.embeddings = embeddings
        self.connection_uri = connection_uri
        self._store = self._build_store(collection_name, embeddings, connection_uri, drop_old, **kwargs)

    @staticmethod
    def _build_store(
        collection_name: str,
        embeddings: Embeddings,
        connection_uri: str,
        drop_old: bool,
        **kwargs: Any,
    ) -> Any:
        """Helper to build langchain_milvus Milvus store.

        Raises:
            ImportError: If langchain-milvus is not installed.
        """
        try:
            from langchain_milvus import Milvus
            from pymilvus import connections
        except ImportError as exc:
            raise ImportError("Milvus backend requires: pip install 'pydebeziumai[milvus]'") from exc

        # Merge connection_uri into connection_args if not already specified
        connection_args = kwargs.pop("connection_args", {})
        if "uri" not in connection_args:
            connection_args["uri"] = connection_uri

        # Ensure the pymilvus connections manager has this connection registered.
        # This prevents connection not found errors during operations.
        alias = connection_args.get("alias", "default")
        if not connections.has_connection(alias):
            connections.connect(alias=alias, uri=connection_args["uri"])

        return Milvus(
            embedding_function=embeddings,
            collection_name=collection_name,
            connection_args=connection_args,
            drop_old=drop_old,
            **kwargs,
        )

    def upsert(self, document: Document) -> None:
        """Add or replace a document in the vector store.

        Args:
            document: The LangChain Document to upsert.
        """
        if not document.id:
            raise ValueError("Document ID must be provided for idempotent upserts.")
        self._store.add_documents(documents=[document], ids=[document.id])
        logger.debug("Milvus upsert: %s", document.id)

    def delete(self, doc_id: str) -> None:
        """Remove a document by its stable ID.

        Args:
            doc_id: The stable ID of the document to remove.
        """
        try:
            self._store.delete(ids=[doc_id])
            logger.debug("Milvus delete: %s", doc_id)
        except Exception as exc:
            logger.debug("Milvus delete skipped for %r: %s", doc_id, exc)

    def as_retriever(self, **kwargs: Any) -> BaseRetriever:
        """Return a LangChain BaseRetriever backed by this vector store.

        Args:
            **kwargs: Options for the retriever (e.g. search_kwargs={"k": 5}).

        Returns:
            A LangChain BaseRetriever.
        """
        return self._store.as_retriever(**kwargs)

    @property
    def store(self) -> Any:
        """Direct access to the underlying langchain_milvus.Milvus instance."""
        return self._store
