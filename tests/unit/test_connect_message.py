# ruff: noqa: N802
"""Unit tests for pydebeziumai/models/connect_message.py."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any

from pydebeziumai.models.connect_message import (
    ConnectMessageExtractor,
    ConversionConfig,
    SourceRecordExtractor,
    struct_to_dict,
)


class MockType:
    def __init__(self, type_name: str) -> None:
        self._type_name = type_name

    def name(self) -> str:
        return self._type_name


class MockSchema:
    def __init__(
        self,
        type_name: str,
        logical_name: str | None = None,
        fields: list[MockField] | None = None,
        parameters_dict: dict[str, str] | None = None,
    ) -> None:
        self._type_name = type_name
        self._logical_name = logical_name
        self._fields = fields or []
        self._parameters = parameters_dict or {}

    def type(self) -> MockType:
        return MockType(self._type_name)

    def name(self) -> str | None:
        return self._logical_name

    def fields(self) -> list[MockField]:
        return self._fields

    def parameters(self) -> dict[str, str]:
        return self._parameters


class MockField:
    def __init__(self, name: str, schema: MockSchema) -> None:
        self._name = name
        self._schema = schema

    def name(self) -> str:
        return self._name

    def schema(self) -> MockSchema:
        return self._schema


class MockStruct:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get(self, field: MockField) -> Any:
        if isinstance(field, str):
            return self._values.get(field)
        return self._values.get(field.name())


def test_conversion_config_defaults() -> None:
    """Verify default parameters for ConversionConfig."""
    config = ConversionConfig()
    assert config.numeric_mode == "native"
    assert config.tz_aware is True


def test_connect_message_extractor_json() -> None:
    """Verify ConnectMessageExtractor handles JSON-mode ChangeEvents."""

    class MockJavaRecord:
        def destination(self) -> str:
            return "my_destination"

        def kafkaPartition(self) -> int:
            return 2

        def key(self) -> str:
            return '{"id": 1}'

        def value(self) -> str:
            return '{"schema": {}, "payload": {"op": "c", "before": null, "after": {"name": "alice"}}}'

    extractor = ConnectMessageExtractor(MockJavaRecord())
    assert extractor.destination == "my_destination"
    assert extractor.partition == 2
    assert extractor.raw_key == '{"id": 1}'
    assert extractor.op == "c"
    assert extractor.before is None
    assert extractor.after == {"name": "alice"}


def test_struct_to_dict_type_conversions() -> None:
    """Verify struct_to_dict parses primitives and logical types correctly."""
    # 1. Schemas
    schema_date = MockSchema("INT32", "org.apache.kafka.connect.data.Date")
    schema_time = MockSchema("INT32", "org.apache.kafka.connect.data.Time")
    schema_ts = MockSchema("INT64", "org.apache.kafka.connect.data.Timestamp")
    schema_uuid = MockSchema("STRING", "io.debezium.data.Uuid")
    schema_bits = MockSchema("BYTES", "io.debezium.data.Bits")
    schema_json = MockSchema("STRING", "io.debezium.data.Json")
    schema_enum = MockSchema("STRING", "io.debezium.data.Enum")
    schema_enum_set = MockSchema("STRING", "io.debezium.data.EnumSet")
    schema_micro_dur = MockSchema("INT64", "io.debezium.time.MicroDuration")

    # Decimal schema with scale param
    schema_decimal = MockSchema(
        "BYTES",
        "org.apache.kafka.connect.data.Decimal",
        parameters_dict={"scale": "2"},
    )

    # Point schema (nested struct)
    point_fields = [
        MockField("x", MockSchema("FLOAT64")),
        MockField("y", MockSchema("FLOAT64")),
        MockField("srid", MockSchema("INT32")),
    ]
    schema_point = MockSchema("STRUCT", "io.debezium.data.geometry.Point", fields=point_fields)

    # Parent struct schema
    fields = [
        MockField("my_date", schema_date),
        MockField("my_time", schema_time),
        MockField("my_ts", schema_ts),
        MockField("my_uuid", schema_uuid),
        MockField("my_bits", schema_bits),
        MockField("my_json", schema_json),
        MockField("my_enum", schema_enum),
        MockField("my_enum_set", schema_enum_set),
        MockField("my_duration", schema_micro_dur),
        MockField("my_decimal", schema_decimal),
        MockField("my_point", schema_point),
    ]
    parent_schema = MockSchema("STRUCT", fields=fields)

    # 2. Values
    # Decimals in big-endian bytes (123.45 -> 12345 -> 0x3039)
    dec_bytes = bytes([0x30, 0x39])

    point_struct = MockStruct({"x": 10.5, "y": 20.5, "srid": 4326})

    struct_values = {
        "my_date": 19000,  # 19000 days since epoch
        "my_time": 36000000,  # 10 hours in ms
        "my_ts": 1600000000000,  # ms timestamp
        "my_uuid": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
        "my_bits": bytes([1, 2, 3]),
        "my_json": '{"a": 1}',
        "my_enum": "VAL",
        "my_enum_set": "VAL1,VAL2",
        "my_duration": 90000000,  # 90s in microsecs
        "my_decimal": dec_bytes,
        "my_point": point_struct,
    }
    parent_struct = MockStruct(struct_values)

    # 3. Conversion
    res = struct_to_dict(parent_struct, parent_schema)

    assert res["my_date"] == date(2022, 1, 8)
    assert res["my_time"] == time(10, 0, 0)
    assert isinstance(res["my_ts"], datetime)
    assert res["my_uuid"] == uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    assert res["my_bits"] == "010203"  # struct_to_dict converts bytes to hex string in results
    assert res["my_json"] == {"a": 1}
    assert res["my_enum"] == "VAL"
    assert res["my_enum_set"] == {"VAL1", "VAL2"}
    assert res["my_duration"] == timedelta(seconds=90)
    assert res["my_decimal"] == Decimal("123.45")
    assert res["my_point"]["x"] == 10.5
    assert res["my_point"]["y"] == 20.5
    assert res["my_point"]["srid"] == 4326


def test_source_record_extractor() -> None:
    """Verify SourceRecordExtractor parses values from a mock Java SourceRecord."""

    class MockSourceRecord:
        def topic(self) -> str:
            return "orders"

        def kafkaPartition(self) -> int:
            return 1

        def keySchema(self) -> MockSchema:
            fields = [MockField("id", MockSchema("INT32"))]
            return MockSchema("STRUCT", fields=fields)

        def key(self) -> MockStruct:
            return MockStruct({"id": 123})

        def valueSchema(self) -> MockSchema:
            fields = [
                MockField("op", MockSchema("STRING")),
                MockField("ts_ms", MockSchema("INT64")),
                MockField("after", MockSchema("STRUCT", fields=[MockField("name", MockSchema("STRING"))])),
            ]
            return MockSchema("STRUCT", fields=fields)

        def value(self) -> MockStruct:
            after_struct = MockStruct({"name": "bob"})
            return MockStruct({"op": "u", "ts_ms": 1600000000000, "after": after_struct})

    extractor = SourceRecordExtractor(MockSourceRecord())
    assert extractor.destination == "orders"
    assert extractor.partition == 1
    assert extractor.key_dict == {"id": 123}
    assert extractor.op == "u"
    assert extractor.ts_ms == 1600000000000
    assert extractor.after == {"name": "bob"}
