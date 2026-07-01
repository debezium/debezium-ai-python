"""Abstract VectorStoreAdapter — the contract all backends must implement.

Keeping this boundary explicit means:
  1. SyncManager has no knowledge of which backend is in use.
  2. New backends require only implementing three methods.
  3. Contract tests can verify any adapter against this interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever


class VectorStoreAdapter(ABC):
    """
    Abstract interface for vector store backends.

    Each backend wraps a LangChain VectorStore and exposes the three
    operations the SyncManager needs: ``upsert``, ``delete``, and
    ``as_retriever``.
    """

    @abstractmethod
    def upsert(self, document: Document) -> None:
        """
        Add or replace a document in the vector store.

        The implementation should use the ``document.id`` field as the
        canonical identifier for idempotent upserts.
        """
        ...

    @abstractmethod
    def delete(self, doc_id: str) -> None:
        """
        Remove a document by its stable ID.

        Implementations must handle the case where the ID does not exist
        (e.g. soft-delete stores, delete events arriving before inserts).
        """
        ...

    @abstractmethod
    def as_retriever(
        self,
        *,
        metadata_filter: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> BaseRetriever:
        """Return a LangChain BaseRetriever backed by this vector store."""
        ...
