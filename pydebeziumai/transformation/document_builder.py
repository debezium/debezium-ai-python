"""Document builder — converts CDC events into LangChain Documents.

This is the bridge between the ingestion/canonical layer and the
synchronization/vector-store layer. Each CDC event produces a
(Document, doc_id, op) BuildResult that the SyncManager consumes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.transformation.id_strategy import IdStrategy, TablePkIdStrategy
from pydebeziumai.transformation.projection_policy import ProjectionPolicy


@dataclass
class BuildResult:
    """Output of DocumentBuilder.build() for a single CDC event."""

    doc_id: str
    """Stable, deterministic document ID for vector store operations."""

    op: str
    """CDC operation: 'c' (create), 'u' (update), 'd' (delete), 'r' (read/snapshot)."""

    document: Document | None = None
    """The LangChain Document (None for delete operations)."""

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
    ) -> None:
        self.id_strategy = id_strategy or TablePkIdStrategy()
        self.projection_policy = projection_policy or ProjectionPolicy.default_policy()
        self.extra_metadata = extra_metadata or {}

    def build(self, event: DebeziumEventModel) -> BuildResult:
        """Build a BuildResult from a canonical CDC event."""
        doc_id = self.id_strategy.generate(event)
        op = event.payload.op

        if event.payload.is_delete:
            # No document content needed — SyncManager will issue a delete
            return BuildResult(doc_id=doc_id, op=op, document=None)

        page_content, row_metadata = self.projection_policy.project(event)

        system_meta: dict[str, Any] = {
            "_table": event.table_name,
            "_schema": event.schema_name,
            "_op": op,
            "_doc_id": doc_id,
        }
        if event.payload.ts_ms is not None:
            system_meta["_ts_ms"] = event.payload.ts_ms

        # Merge: user row metadata → extra_metadata overrides → system metadata
        metadata = {**row_metadata, **self.extra_metadata, **system_meta}

        # Sanitize metadata for vector store compatibility
        metadata = self._sanitize_metadata(metadata)

        document = Document(
            page_content=page_content,
            metadata=metadata,
            id=doc_id,
        )

        return BuildResult(doc_id=doc_id, op=op, document=document)

    @staticmethod
    def _sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
        """
        Coerce metadata values to types Chroma/PGVector/Milvus can store.

        Chroma accepts: str, int, float, bool.
        This converts bytes→hex str, Decimal→float, date/datetime→isoformat,
        None→"null", and everything else→str.
        """
        import decimal
        from datetime import date, datetime, time, timedelta

        clean: dict[str, Any] = {}
        for k, v in meta.items():
            if v is None:
                clean[k] = "null"
            elif isinstance(v, (bool, int, float, str)):
                clean[k] = v
            elif isinstance(v, decimal.Decimal):
                clean[k] = float(v)
            elif isinstance(v, (bytes, bytearray)):
                # Debezium NUMERIC in JSON mode arrives as raw bytes
                try:
                    # Try interpreting as big-endian signed int (Kafka Decimal)
                    int_val = int.from_bytes(bytes(v), byteorder="big", signed=True)
                    clean[k] = float(int_val)
                except Exception:
                    clean[k] = bytes(v).hex()
            elif isinstance(v, (datetime, date, time)):
                clean[k] = v.isoformat()
            elif isinstance(v, timedelta):
                clean[k] = v.total_seconds()
            elif isinstance(v, (dict, list, set, tuple)):
                clean[k] = str(v)
            else:
                clean[k] = str(v)
        return clean
