"""PGVector vector store adapter implementation."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.retrievers import BaseRetriever

from pydebeziumai.adapters.base import VectorStoreAdapter

logger = logging.getLogger(__name__)


class PGVectorAdapter(VectorStoreAdapter):
    """Vector store adapter for PGVector (PostgreSQL)."""

    def __init__(
        self,
        connection_string: str,
        collection_name: str,
        embeddings: Embeddings,
        pre_delete_collection: bool = False,
    ) -> None:
        """Initialises the PGVectorAdapter.

        Args:
            connection_string: SQLAlchemy async connection URL.
            collection_name: Table name for this embedding collection.
            embeddings: Embeddings model to generate vector representations.
            pre_delete_collection: Drop and recreate collection on init (default False).
        """
        self.connection_string = connection_string
        self.collection_name = collection_name
        self.embeddings = embeddings
        self._store = self._build_store(connection_string, collection_name, embeddings, pre_delete_collection)

    @staticmethod
    def _build_store(
        connection_string: str,
        collection_name: str,
        embeddings: Embeddings,
        pre_delete_collection: bool,
    ) -> Any:
        """Helper to build langchain_postgres PGVector store.

        Raises:
            ImportError: If langchain-postgres is not installed.
        """
        try:
            from langchain_postgres import PGVector
            from langchain_postgres.vectorstores import DistanceStrategy
        except ImportError as exc:
            raise ImportError("PGVector backend requires: pip install 'pydebeziumai[pgvector]'") from exc

        return PGVector(
            connection=connection_string,
            collection_name=collection_name,
            embeddings=embeddings,
            distance_strategy=DistanceStrategy.COSINE,
            pre_delete_collection=pre_delete_collection,
            use_jsonb=True,
        )

    def upsert(self, document: Document) -> None:
        """Add or replace a document in the vector store.

        Args:
            document: The LangChain Document to upsert.
        """
        if not document.id:
            raise ValueError("Document ID must be provided for idempotent upserts.")
        logger.debug("PGVector upsert: %s", document.id)
        self._store.add_documents(documents=[document], ids=[document.id])

    def delete(self, doc_id: str) -> None:
        """Remove a document by its stable ID.

        Args:
            doc_id: The stable ID of the document to remove.
        """
        try:
            logger.debug("PGVector delete: %s", doc_id)
            self._store.delete(ids=[doc_id])
        except Exception as exc:
            logger.debug("PGVector delete skipped for %r: %s", doc_id, exc)

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
                merged = dict(existing_filter)
                merged.update(metadata_filter)
                kwargs["search_kwargs"]["filter"] = merged
            else:
                kwargs["search_kwargs"]["filter"] = metadata_filter

        return self._store.as_retriever(**kwargs)

    @property
    def store(self) -> Any:
        """Direct access to the underlying langchain_postgres.PGVector instance."""
        return self._store
