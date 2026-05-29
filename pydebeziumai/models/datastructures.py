"""
datastructures.py

Pure Python data structures representing a Debezium CDC event.

These are built from ConnectMessageExtractor (JSON mode) or
SourceRecordExtractor (Connect mode) and serve as the intermediate
layer between raw Java objects and Pydantic models.

Flow:
    Java ChangeEvent (JPype)
        → ConnectMessageExtractor  (connect_message.py)
            → DebeziumRecord        (this file)
                → DebeziumEventModel (models/event.py)
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from pydebeziumai.models.connect_message import (
    ConnectMessageExtractor,
    ConversionConfig,
    SourceRecordExtractor,
)


@dataclass
class DebeziumSchema:
    """
    Lightweight wrapper around the raw Debezium schema dict.

    Populated from the JSON ``schema`` block when available (JSON mode).
    Not populated in Connect mode (schema is consumed by struct_to_dict).
    """

    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def type(self) -> str | None:
        return self.raw.get("type")

    @property
    def fields(self) -> list[dict[str, Any]]:
        return self.raw.get("fields", [])

    @property
    def name(self) -> str | None:
        return self.raw.get("name")

    def __repr__(self) -> str:
        return f"DebeziumSchema(name={self.name!r}, type={self.type!r})"


@dataclass
class DebeziumRecord:
    """
    Python-native intermediate representation of a single Debezium CDC event.

    Fields:
        destination: Topic / table identifier.
        op: Operation type: 'c'=create, 'u'=update, 'd'=delete, 'r'=read/snapshot.
        before: Row state before the change (None for inserts/reads).
        after: Row state after the change (None for deletes).
        ts_ms: Debezium capture timestamp in milliseconds since epoch.
        key: The record key (JSON string).
        partition: Kafka partition (if applicable).
        schema: The Debezium schema envelope (JSON mode only).
    """

    destination: str
    op: str
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    ts_ms: int | None
    key: str | None = None
    partition: int | None = None
    schema: DebeziumSchema | None = None

    # ── Factories ─────────────────────────────────────────────────────────

    @classmethod
    def from_extractor(cls, extractor: ConnectMessageExtractor) -> DebeziumRecord:
        """Build a DebeziumRecord from a JSON-mode ConnectMessageExtractor."""
        schema = DebeziumSchema(raw=extractor.schema) if extractor.schema else None
        return cls(
            destination=extractor.destination,
            op=extractor.op or "r",
            before=extractor.before,
            after=extractor.after,
            ts_ms=extractor.ts_ms,
            key=extractor.raw_key,
            partition=extractor.partition,
            schema=schema,
        )

    @classmethod
    def from_java_record(cls, java_record: Any) -> DebeziumRecord:
        """Build directly from a raw Java ChangeEvent (JSON mode)."""
        return cls.from_extractor(ConnectMessageExtractor(java_record))

    @classmethod
    def from_source_record(
        cls,
        source_record: Any,
        conversion_config: ConversionConfig | None = None,
        topic_class_map: Mapping[str, type[Any]] | None = None,
    ) -> DebeziumRecord:
        """
        Build from a raw Java SourceRecord (Connect mode).

        No JSON serialization/deserialization — uses struct_to_dict internally.
        """
        extractor = SourceRecordExtractor(
            source_record,
            conversion_config=conversion_config,
            topic_class_map=topic_class_map,
        )
        return cls(
            destination=extractor.destination,
            op=extractor.op or "r",
            before=extractor.before,
            after=extractor.after,
            ts_ms=extractor.ts_ms,
            key=extractor.raw_key,
            partition=extractor.partition,
            schema=None,  # schema consumed by struct_to_dict in Connect mode
        )

    # ── Convenience predicates ────────────────────────────────────────────

    def is_create(self) -> bool:
        return self.op == "c"

    def is_update(self) -> bool:
        return self.op == "u"

    def is_delete(self) -> bool:
        return self.op == "d"

    def is_snapshot(self) -> bool:
        return self.op == "r"

    def get_current_state(self) -> dict[str, Any] | None:
        """Returns the most recent state: ``after`` for c/u/r, ``before`` for d."""
        return self.before if self.is_delete() else self.after

    def __repr__(self) -> str:
        return f"DebeziumRecord(destination={self.destination!r}, op={self.op!r}, after={self.after!r})"


# ── Batch helpers ─────────────────────────────────────────────────────────────


def records_from_batch(java_records: list[Any]) -> list[DebeziumRecord]:
    """Convert a batch of JSON-mode Java ChangeEvent objects to DebeziumRecords."""
    return [DebeziumRecord.from_java_record(r) for r in java_records]


def connect_records_from_batch(
    source_records: list[Any],
    conversion_config: ConversionConfig | None = None,
    topic_class_map: Mapping[str, type[Any]] | None = None,
) -> list[DebeziumRecord]:
    """Convert a batch of Connect-mode Java SourceRecord objects to DebeziumRecords."""
    return [DebeziumRecord.from_source_record(r, conversion_config, topic_class_map) for r in source_records]
