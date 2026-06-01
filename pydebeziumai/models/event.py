"""Canonical Pydantic v2 event models for Debezium CDC events.

All ingestion modes (JSON + Connect) normalize to these models before
entering the transformation layer, providing a stable internal contract.

Models:
  DebeziumSchemaField   — a single field in a Debezium schema definition
  DebeziumSchemaModel   — the schema section of a Debezium JSON envelope
  DebeziumPayloadModel  — the payload section (before/after/op/ts_ms)
  DebeziumEventModel    — top-level canonical event envelope
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger(__name__)


class DebeziumSchemaField(BaseModel):
    """A single field in a Debezium schema definition."""

    field: str | None = None
    type: str | None = None
    optional: bool | None = None
    name: str | None = None
    version: int | None = None
    parameters: dict[str, Any] | None = None


class DebeziumSchemaModel(BaseModel):
    """The schema section of a Debezium JSON envelope."""

    type: str | None = None
    fields: list[DebeziumSchemaField] | None = None
    name: str | None = None
    optional: bool | None = None
    version: int | None = None


class DebeziumPayloadModel(BaseModel):
    """Normalized payload extracted from a Debezium CDC envelope."""

    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None
    op: str
    ts_ms: int | None = None
    source: dict[str, Any] | None = Field(default=None, description="Debezium source metadata block")

    @model_validator(mode="after")
    def check_op(self) -> DebeziumPayloadModel:
        valid_ops = {"c", "u", "d", "r"}
        if self.op not in valid_ops:
            raise ValueError(f"Invalid CDC operation: {self.op!r}. Must be one of {valid_ops}")
        return self

    @property
    def current_row(self) -> dict[str, Any] | None:
        """The current row state: `after` for c/u/r, `before` for d."""
        return self.after if self.op in ("c", "u", "r") else self.before

    @property
    def is_insert(self) -> bool:
        return self.op in ("c", "r")

    @property
    def is_update(self) -> bool:
        return self.op == "u"

    @property
    def is_delete(self) -> bool:
        return self.op == "d"


def _decode_json_decimal(
    payload: dict[str, Any],
    schema_block: dict[str, Any],
) -> dict[str, Any]:
    """
    Walk the Debezium JSON schema block and decode base64-encoded Decimal bytes.

    Debezium serializes NUMERIC/DECIMAL columns in JSON mode as base64 strings
    (the raw Kafka Connect Decimal bytes). This function converts those back to
    Python floats so they display correctly in content templates.

    Only modifies 'before' and 'after' sub-dicts.
    """

    _DECIMAL_NAMES = {  # noqa: N806
        "org.apache.kafka.connect.data.Decimal",
        "io.debezium.data.VariableScaleDecimal",
    }

    # Build a map of field_name → scale from the schema fields
    decimal_fields: dict[str, int] = {}
    for top_field in schema_block.get("fields", []):
        sub_schema = top_field  # e.g. the 'after' struct
        for inner_field in sub_schema.get("fields", []):
            name_val = inner_field.get("name") or ""
            field_name = inner_field.get("field", "")
            if name_val in _DECIMAL_NAMES:
                params = inner_field.get("parameters", {}) or {}
                scale = int(params.get("scale", 0))
                decimal_fields[field_name] = scale

    if not decimal_fields:
        return payload

    def _decode_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
        if not row:
            return row
        result = dict(row)
        for fname, scale in decimal_fields.items():
            raw = result.get(fname)
            if isinstance(raw, str) and raw:
                try:
                    raw_bytes = base64.b64decode(raw)
                    int_val = int.from_bytes(raw_bytes, byteorder="big", signed=True)
                    result[fname] = round(int_val / (10**scale), scale) if scale else int_val
                except Exception as e:
                    logger.warning("Failed to decode JSON decimal for field %s: %s", fname, e)
        return result

    decoded = dict(payload)
    decoded["before"] = _decode_row(payload.get("before"))
    decoded["after"] = _decode_row(payload.get("after"))
    return decoded


class DebeziumEventModel(BaseModel):
    """Top-level canonical Debezium CDC event envelope."""

    model_config = {"populate_by_name": True}

    destination: str = Field(description="Topic / table destination identifier (e.g. 'myserver.public.orders')")
    partition: int | None = None
    key: str | None = None
    event_schema: DebeziumSchemaModel | None = Field(default=None, alias="schema")
    payload: DebeziumPayloadModel

    @classmethod
    def from_json_record(cls, record: Any) -> DebeziumEventModel:
        """Parse from a pydbzengine ChangeEvent (JSON / polling mode)."""
        destination = str(record.destination()) if record.destination() else ""
        key_raw = record.key()
        key = str(key_raw) if key_raw else None

        value_str = record.value()
        if not value_str:
            raise ValueError(f"Empty CDC event value at destination {destination!r}")

        value_dict: dict[str, Any] = json.loads(str(value_str))
        # Debezium JSON envelope: top-level has 'payload' key; flat mode doesn't
        schema_block = value_dict.get("schema")
        payload_dict = value_dict.get("payload", value_dict)

        # Decode base64-encoded Decimal bytes using schema type hints
        if schema_block:
            payload_dict = _decode_json_decimal(payload_dict, schema_block)

        return cls(
            destination=destination,
            key=key,
            payload=DebeziumPayloadModel(**payload_dict),
        )

    @classmethod
    def from_dict(
        cls,
        destination: str,
        key: str | None,
        payload: dict[str, Any],
    ) -> DebeziumEventModel:
        """Build directly from a raw dict (Connect-mode extraction or testing)."""
        return cls(
            destination=destination,
            key=key,
            payload=DebeziumPayloadModel(**payload),
        )

    @classmethod
    def from_record(cls, record: Any) -> DebeziumEventModel:
        """
        Build a validated DebeziumEventModel from a DebeziumRecord.

        This is the bridge between the intermediate dataclass layer and
        the Pydantic-validated pipeline layer.

        Args:
            record: A DebeziumRecord instance (from models/datastructures.py).

        Returns:
            A validated DebeziumEventModel.
        """
        schema_data = dict(record.schema.raw) if record.schema else None
        payload_data = {
            "before": record.before,
            "after": record.after,
            "op": record.op,
            "ts_ms": record.ts_ms,
        }
        return cls(
            destination=record.destination,
            partition=record.partition,
            key=record.key,
            schema=DebeziumSchemaModel(**schema_data) if schema_data else None,
            payload=DebeziumPayloadModel(**payload_data),
        )

    @property
    def table_name(self) -> str:
        """Last dotted segment of destination, e.g. 'orders' from 'server.public.orders'."""
        parts = self.destination.split(".")
        return parts[-1] if parts else self.destination

    @property
    def schema_name(self) -> str:
        """Second-to-last segment (schema/namespace), or empty string."""
        parts = self.destination.split(".")
        return parts[-2] if len(parts) >= 2 else ""

    @property
    def namespace(self) -> str:
        """Full schema.table string."""
        s = self.schema_name
        t = self.table_name
        return f"{s}.{t}" if s else t

    def extract_primary_key(self, pk_fields: list[str] | None = None) -> str | None:
        """
        Extract the primary key string for this event.

        Priority order:
        1. Parse the JSON key field (Debezium Connect key schema).
        2. Extract from payload using ``pk_fields`` if provided.
        3. Return None if no primary key is found.
        """
        if self.key:
            try:
                key_dict = json.loads(self.key)
                if isinstance(key_dict, dict):
                    return "|".join(str(v) for v in key_dict.values())
            except (json.JSONDecodeError, TypeError):
                return self.key

        row = self.payload.current_row or {}
        if pk_fields:
            return "|".join(str(row.get(f, "")) for f in pk_fields)

        return None
