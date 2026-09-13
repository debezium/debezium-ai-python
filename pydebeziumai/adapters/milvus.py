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
        import hashlib
        uri_hash = hashlib.md5(connection_uri.encode("utf-8")).hexdigest()[:8]
        alias = connection_args.get("alias", f"pydebeziumai_{uri_hash}")
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
        """Add or replace a document in the vector store atomically.

        Args:
            document: The LangChain Document to upsert.
        """
        if not document.id:
            raise ValueError("Document ID must be provided for idempotent upserts.")
        logger.debug("Milvus upsert: %s", document.id)
        self._store.add_documents(documents=[document], ids=[document.id])

    def upsert_batch(self, documents: list[Document]) -> None:
        """Add or replace a list of documents in the vector store atomically.

        Args:
            documents: The list of LangChain Documents to upsert.
        """
        if not documents:
            return
        ids = []
        for doc in documents:
            if not doc.id:
                raise ValueError("Document ID must be provided for idempotent upserts.")
            ids.append(doc.id)
        logger.debug("Milvus upsert_batch: %d documents", len(documents))
        self._store.add_documents(documents=documents, ids=ids)

    def delete(self, doc_id: str) -> None:
        """Remove a document by its stable ID.

        Args:
            doc_id: The stable ID of the document to remove.
        """
        logger.debug("Milvus delete: %s", doc_id)
        try:
            self._store.delete(ids=[doc_id])
        except Exception as exc:
            if "collection not found" in str(exc).lower() or "not exist" in str(exc).lower():
                logger.debug("Milvus delete ignored for missing collection: %s", exc)
            else:
                raise

    def delete_batch(self, doc_ids: list[str]) -> None:
        """Remove a list of documents by their stable IDs in bulk.

        Args:
            doc_ids: The stable IDs of the documents to remove.
        """
        if not doc_ids:
            return
        logger.debug("Milvus delete_batch: %d documents", len(doc_ids))
        try:
            self._store.delete(ids=doc_ids)
        except Exception as exc:
            if "collection not found" in str(exc).lower() or "not exist" in str(exc).lower():
                logger.debug("Milvus delete_batch ignored for missing collection: %s", exc)
            else:
                raise

    @staticmethod
    def _dict_to_milvus_expr(filter_dict: dict[str, Any]) -> str:
        """Helper to convert a dictionary of metadata filters into a Milvus boolean expression string."""
        expr_parts = []
        for key, val in filter_dict.items():
            if not key.replace("_", "").isalnum():
                raise ValueError(f"Invalid metadata filter key name: {key!r}")
            if isinstance(val, str):
                escaped_val = val.replace("\\", "\\\\").replace("'", "\\'")
                expr_parts.append(f"{key} == '{escaped_val}'")
            elif isinstance(val, bool):
                expr_parts.append(f"{key} == {str(val).lower()}")
            elif isinstance(val, (int, float)):
                expr_parts.append(f"{key} == {val}")
            elif val is None:
                expr_parts.append(f"{key} == None")
            else:
                raise ValueError(f"Unsupported metadata filter value type for key {key!r}: {type(val)}")
        return " and ".join(expr_parts)

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
            expr_str = self._dict_to_milvus_expr(metadata_filter)
            if "search_kwargs" not in kwargs:
                kwargs["search_kwargs"] = {}
            existing_expr = kwargs["search_kwargs"].get("expr")
            if existing_expr:
                kwargs["search_kwargs"]["expr"] = f"({existing_expr}) and ({expr_str})"
            else:
                kwargs["search_kwargs"]["expr"] = expr_str

        return self._store.as_retriever(**kwargs)

    @property
    def store(self) -> Any:
        """Direct access to the underlying langchain_milvus.Milvus instance."""
        return self._store
