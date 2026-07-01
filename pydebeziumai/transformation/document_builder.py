"""Document builder — converts CDC events into LangChain Documents.

This is the bridge between the ingestion/canonical layer and the
synchronization/vector-store layer. Each CDC event produces a
(Document, doc_id, op) BuildResult that the SyncManager consumes.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.transformation.id_strategy import IdStrategy, TablePkIdStrategy
from pydebeziumai.transformation.projection_policy import ProjectionPolicy

logger = logging.getLogger(__name__)


@dataclass
class BuildResult:
    """Output of DocumentBuilder.build() for a single CDC event.

    Attributes:
        doc_id: Stable, deterministic document ID for vector store operations.
        op: CDC operation: 'c' (create), 'u' (update), 'd' (delete), 'r' (read/snapshot).
        document: The LangChain Document (None for delete operations).
    """

    doc_id: str
    op: str
    document: Document | None = None

    @property
    def is_delete(self) -> bool:
        return self.op == "d"


class DocumentBuilder:
    """
    Converts a DebeziumEventModel into a BuildResult (Document + ID + op).

    Wires together:
      - IdStrategy   → stable document ID
      - ProjectionPolicy → which fields → page_content / metadata

    Additional system metadata injected into every document:
      - ``_table``       table name
      - ``_schema``      schema/namespace
      - ``_op``          CDC operation character
      - ``_ts_ms``       source event timestamp (ms since epoch)
      - ``_source``      optional Debezium source block fields

    Usage::

        builder = DocumentBuilder()
        result = builder.build(event)
        # result.doc_id, result.op, result.document
    """

    def __init__(
        self,
        id_strategy: IdStrategy | None = None,
        projection_policy: ProjectionPolicy | None = None,
        extra_metadata: dict[str, Any] | None = None,
        sanitizer: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    ) -> None:
        from pydebeziumai.transformation.sanitizer import sanitize_metadata

        self.id_strategy = id_strategy or TablePkIdStrategy()
        self.projection_policy = projection_policy or ProjectionPolicy.default_policy()
        self.extra_metadata = extra_metadata or {}
        self.sanitizer = sanitizer or sanitize_metadata

    def build(self, event: DebeziumEventModel, allow_soft_delete: bool = False) -> BuildResult:
        """Build a BuildResult from a canonical CDC event.

        Args:
            event: The DebeziumEventModel to convert.
            allow_soft_delete: If True, builds a Document with _is_deleted=True
                               instead of returning None for delete operations.
        """
        doc_id = self.id_strategy.generate(event)
        op = event.payload.op
        logger.debug("Building document for doc_id=%s, op=%r, allow_soft_delete=%s", doc_id, op, allow_soft_delete)

        if event.payload.is_delete and not allow_soft_delete:
            # No document content needed — SyncManager will issue a delete
            logger.debug("Tombstone delete event for doc_id=%s, skipping document body building", doc_id)
            return BuildResult(doc_id=doc_id, op=op, document=None)

        page_content, row_metadata = self.projection_policy.project(event)

        system_meta: dict[str, Any] = {
            "_table": event.table_name,
            "_schema": event.schema_name,
            "_op": op,
            "_doc_id": doc_id,
        }
        if event.payload.is_delete:
            system_meta["_is_deleted"] = True

        if event.payload.ts_ms is not None:
            system_meta["_ts_ms"] = event.payload.ts_ms

        # Merge: user row metadata → extra_metadata overrides → system metadata
        metadata = {**row_metadata, **self.extra_metadata, **system_meta}

        # Sanitize metadata for vector store compatibility
        metadata = self.sanitizer(metadata)

        document = Document(
            page_content=page_content,
            metadata=metadata,
            id=doc_id,
        )

        logger.info("Successfully built Document for doc_id=%s (page_content_len=%d)", doc_id, len(page_content))
        return BuildResult(doc_id=doc_id, op=op, document=document)
