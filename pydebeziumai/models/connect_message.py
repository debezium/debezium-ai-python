"""Python utilities for Debezium CDC events.

Provides:
  - ConversionConfig         : controls numeric/tz output
  - ConnectMessageExtractor  : wraps JSON-mode ChangeEvent (no JPype)
  - SourceRecordExtractor    : wraps Connect-mode SourceRecord (JPype)
  - struct_to_dict           : recursive Java Struct → Python dict
  - print_record_info        : debug utility for SourceRecord introspection
  - extract_all              : batch helper for JSON mode
  - extract_connect_all      : batch helper for Connect mode

Logical types supported
-----------------------
Kafka Connect primitives:
  org.apache.kafka.connect.data.Timestamp       → datetime (UTC)
  org.apache.kafka.connect.data.Date            → datetime.date
  org.apache.kafka.connect.data.Time            → datetime.time
  org.apache.kafka.connect.data.Decimal         → decimal.Decimal (with scale)

Debezium time types:
  io.debezium.time.Date                         → datetime.date
  io.debezium.time.Time                         → datetime.time (ms)
  io.debezium.time.MicroTime                    → datetime.time (µs)
  io.debezium.time.NanoTime                     → datetime.time (ns)
  io.debezium.time.Timestamp                    → datetime (ms, UTC)
  io.debezium.time.MicroTimestamp               → datetime (µs, UTC)
  io.debezium.time.NanoTimestamp                → datetime (ns, UTC)
  io.debezium.time.ZonedTimestamp               → datetime (tz-aware)
  io.debezium.time.ZonedTime                    → datetime.time (tz-aware)
  io.debezium.time.MicroDuration                → datetime.timedelta
  io.debezium.time.Interval                     → str (ISO-8601 interval)

Debezium data types:
  io.debezium.data.Uuid                         → uuid.UUID
  io.debezium.data.Bits                         → bytes
  io.debezium.data.Json                         → dict | str
  io.debezium.data.Enum                         → str
  io.debezium.data.EnumSet                      → set[str]
  io.debezium.data.VariableScaleDecimal         → decimal.Decimal
  io.debezium.data.geometry.Geometry            → dict (GeoJSON-like)
  io.debezium.data.geometry.Point               → dict {"x":..,"y":..,"srid":..}
  io.debezium.data.geometry.Geography           → dict (GeoJSON-like)
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

try:
    import numpy as _np

    _HAS_NUMPY = True
except ImportError:
    _np = None  # type: ignore[assignment]
    _HAS_NUMPY = False

NumericMode = Literal["native", "numpy"]

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_EPOCH_DATE = date(1970, 1, 1)


# Logical-type name constants

# Kafka Connect built-ins
_KC_TS = "org.apache.kafka.connect.data.Timestamp"
_KC_DATE = "org.apache.kafka.connect.data.Date"
_KC_TIME = "org.apache.kafka.connect.data.Time"
_KC_DEC = "org.apache.kafka.connect.data.Decimal"

# Debezium time
_DBZ_DATE = "io.debezium.time.Date"
_DBZ_TIME = "io.debezium.time.Time"
_DBZ_MICRO_TIME = "io.debezium.time.MicroTime"
_DBZ_NANO_TIME = "io.debezium.time.NanoTime"
_DBZ_TS = "io.debezium.time.Timestamp"
_DBZ_MICRO_TS = "io.debezium.time.MicroTimestamp"
_DBZ_NANO_TS = "io.debezium.time.NanoTimestamp"
_DBZ_ZONED_TS = "io.debezium.time.ZonedTimestamp"
_DBZ_ZONED_TIME = "io.debezium.time.ZonedTime"
_DBZ_MICRO_DUR = "io.debezium.time.MicroDuration"
_DBZ_INTERVAL = "io.debezium.time.Interval"

# Debezium data
_DBZ_UUID = "io.debezium.data.Uuid"
_DBZ_BITS = "io.debezium.data.Bits"
_DBZ_JSON = "io.debezium.data.Json"
_DBZ_ENUM = "io.debezium.data.Enum"
_DBZ_ENUMSET = "io.debezium.data.EnumSet"
_DBZ_VAR_DEC = "io.debezium.data.VariableScaleDecimal"

# Geometry
_DBZ_GEO = "io.debezium.data.geometry.Geometry"
_DBZ_POINT = "io.debezium.data.geometry.Point"
_DBZ_GEOGRAPHY = "io.debezium.data.geometry.Geography"


# ConversionConfig


@dataclass
class ConversionConfig:
    """Controls how Debezium Connect schema types are converted to Python.

    Attributes:
        numeric_mode: ``"native"`` → int / float / Decimal;
                      ``"numpy"``  → numpy.int64 / numpy.float64 (requires numpy).
        tz_aware:     Return timezone-aware datetimes when True (default).
    """

    numeric_mode: NumericMode = "native"
    tz_aware: bool = True


# Internal helpers — time conversion


def _ms_to_time(ms: int) -> time:
    td = timedelta(milliseconds=ms)
    total_s = int(td.total_seconds())
    h, rem = divmod(total_s, 3600)
    m, s = divmod(rem, 60)
    us = td.microseconds
    return time(h % 24, m, s, us)


def _us_to_time(us: int) -> time:
    return _ms_to_time(us // 1_000)


def _ns_to_time(ns: int) -> time:
    return _ms_to_time(ns // 1_000_000)


def _ms_to_datetime(ms: int, tz_aware: bool) -> datetime:
    dt = _EPOCH + timedelta(milliseconds=ms)
    return dt if tz_aware else dt.replace(tzinfo=None)


def _us_to_datetime(us: int, tz_aware: bool) -> datetime:
    dt = _EPOCH + timedelta(microseconds=us)
    return dt if tz_aware else dt.replace(tzinfo=None)


def _ns_to_datetime(ns: int, tz_aware: bool) -> datetime:
    dt = _EPOCH + timedelta(microseconds=ns // 1_000)
    return dt if tz_aware else dt.replace(tzinfo=None)


def _days_to_date(days: int) -> date:
    return _EPOCH_DATE + timedelta(days=days)


# Decimal helpers


def _bytes_to_decimal(raw: bytes, scale: int = 0) -> Decimal:
    int_val = int.from_bytes(raw, byteorder="big", signed=True)
    if scale == 0:
        return Decimal(int_val)
    return Decimal(int_val) / Decimal(10**scale)


def _get_decimal_scale(schema: Any) -> int:
    """Extract 'scale' parameter from Kafka Connect Decimal schema."""
    try:
        params = schema.parameters()
        if params and params.get("scale"):
            return int(str(params.get("scale")))
    except Exception:
        pass
    return 0


# Geometry helpers


def _parse_geometry(struct: Any) -> dict[str, Any]:
    """Parse io.debezium.data.geometry.* Struct to a plain dict."""
    try:
        wkb = bytes(struct.get("wkb")) if struct.get("wkb") is not None else None
        srid = int(struct.get("srid")) if struct.get("srid") is not None else None
        return {"wkb": wkb.hex() if wkb else None, "srid": srid, "_type": "geometry"}
    except Exception:
        return {"_type": "geometry", "raw": str(struct)}


def _parse_point(struct: Any) -> dict[str, Any]:
    """Parse io.debezium.data.geometry.Point Struct."""
    try:
        x = float(struct.get("x")) if struct.get("x") is not None else None
        y = float(struct.get("y")) if struct.get("y") is not None else None
        srid = int(struct.get("srid")) if struct.get("srid") is not None else None
        return {"x": x, "y": y, "srid": srid, "_type": "point"}
    except Exception:
        return {"_type": "point", "raw": str(struct)}


def _parse_variable_scale_decimal(struct: Any) -> Decimal:
    """Parse io.debezium.data.VariableScaleDecimal Struct."""
    try:
        scale = int(struct.get("scale"))
        raw_bytes = bytes(struct.get("value"))
        return _bytes_to_decimal(raw_bytes, scale)
    except Exception:
        return Decimal(str(struct))


# Core logical-type coercion


def _coerce_logical(
    schema_name: str,
    schema: Any,
    value: Any,
    cfg: ConversionConfig,
) -> Any:
    """Map a Kafka Connect / Debezium logical type to a Python native value."""

    if schema_name in (_KC_TS, _DBZ_TS):
        return _ms_to_datetime(int(value), cfg.tz_aware)

    if schema_name == _DBZ_MICRO_TS:
        return _us_to_datetime(int(value), cfg.tz_aware)

    if schema_name == _DBZ_NANO_TS:
        return _ns_to_datetime(int(value), cfg.tz_aware)

    if schema_name == _DBZ_ZONED_TS:
        raw = str(value)
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return raw

    if schema_name in (_KC_DATE, _DBZ_DATE):
        return _days_to_date(int(value))

    if schema_name in (_KC_TIME, _DBZ_TIME):
        return _ms_to_time(int(value))

    if schema_name == _DBZ_MICRO_TIME:
        return _us_to_time(int(value))

    if schema_name == _DBZ_NANO_TIME:
        return _ns_to_time(int(value))

    if schema_name == _DBZ_ZONED_TIME:
        try:
            return time.fromisoformat(str(value))
        except ValueError:
            return str(value)

    if schema_name == _DBZ_MICRO_DUR:
        return timedelta(microseconds=int(value))

    if schema_name == _DBZ_INTERVAL:
        return str(value)  # ISO-8601 interval string

    if schema_name == _KC_DEC:
        raw_bytes = bytes(value) if not isinstance(value, (bytes, bytearray)) else bytes(value)
        scale = _get_decimal_scale(schema)
        return _bytes_to_decimal(raw_bytes, scale)

    if schema_name == _DBZ_VAR_DEC:
        return _parse_variable_scale_decimal(value)

    if schema_name == _DBZ_UUID:
        try:
            return uuid.UUID(str(value))
        except ValueError:
            return str(value)

    if schema_name == _DBZ_BITS:
        try:
            return bytes(value)
        except Exception:
            return value

    if schema_name == _DBZ_JSON:
        sv = str(value)
        try:
            return json.loads(sv)
        except Exception:
            return sv

    if schema_name == _DBZ_ENUM:
        return str(value)

    if schema_name == _DBZ_ENUMSET:
        sv = str(value)
        if not sv or sv == "{}":
            return set()
        return set(sv.strip("{}").split(","))

    if schema_name in (_DBZ_GEO, _DBZ_GEOGRAPHY):
        return _parse_geometry(value)

    if schema_name == _DBZ_POINT:
        return _parse_point(value)

    return None  # sentinel: no matching logical type


# Recursive value converter


def _convert_value(value: Any, schema: Any, cfg: ConversionConfig) -> Any:
    """Recursively convert a JPype Connect value to a Python native value."""
    if value is None:
        return None

    schema_type: str = str(schema.type().name())
    schema_name: str = str(schema.name()) if schema.name() else ""

    # Check logical type first (overrides primitive handling)
    if schema_name:
        result = _coerce_logical(schema_name, schema, value, cfg)
        if result is not None:
            return result

    if schema_type == "STRUCT":
        # VariableScaleDecimal and geometry are STRUCTs with a logical name
        if schema_name == _DBZ_VAR_DEC:
            return _parse_variable_scale_decimal(value)
        if schema_name in (_DBZ_GEO, _DBZ_GEOGRAPHY):
            return _parse_geometry(value)
        if schema_name == _DBZ_POINT:
            return _parse_point(value)
        return struct_to_dict(value, schema, cfg)

    if schema_type == "MAP":
        return {
            _convert_value(k, schema.keySchema(), cfg): _convert_value(v, schema.valueSchema(), cfg)
            for k, v in value.items()
        }

    if schema_type == "ARRAY":
        return [_convert_value(item, schema.valueSchema(), cfg) for item in value]

    if schema_type == "BYTES":
        raw = bytes(value) if not isinstance(value, (bytes, bytearray)) else bytes(value)
        return raw

    if schema_type in ("INT8", "INT16", "INT32", "INT64"):
        iv = int(value)
        if cfg.numeric_mode == "numpy" and _HAS_NUMPY:
            return _np.int64(iv)
        return iv

    if schema_type in ("FLOAT32", "FLOAT64"):
        fv = float(value)
        if cfg.numeric_mode == "numpy" and _HAS_NUMPY:
            return _np.float64(fv)
        return fv

    if schema_type == "BOOLEAN":
        return bool(value)

    if schema_type == "STRING":
        return str(value)

    return str(value)  # fallback


# Public: struct_to_dict


def struct_to_dict(
    struct: Any,
    schema: Any,
    cfg: ConversionConfig | None = None,
    topic_class_map: Mapping[str, type[Any]] | None = None,
    topic: str = "",
) -> Any:
    """
    Convert a JPype Kafka Connect Struct to a Python dict.

    Optionally maps the result to a typed dataclass via ``topic_class_map``.

    Args:
        struct: JPype Struct object from a Debezium SourceRecord.
        schema: The Kafka Connect Schema for this struct.
        cfg: Conversion configuration (defaults to native mode, tz_aware=True).
        topic_class_map: Maps topic/table names to Python classes.
            Keys can be full topic (``"server.public.orders"``),
            schema-qualified (``"public.orders"``), or bare table (``"orders"``).
        topic: Topic name for class-map lookup.

    Returns:
        A plain Python dict, or an instance of the mapped class if a match found.
    """
    _cfg = cfg or ConversionConfig()
    result: dict[str, Any] = {}

    for f in schema.fields():
        field_name = str(f.name())
        try:
            field_value = struct.get(f)
        except Exception:
            field_value = None
        result[field_name] = _convert_value(field_value, f.schema(), _cfg)

    for k, v in result.items():
        if isinstance(v, (bytes, bytearray)):
            result[k] = v.hex()

    if topic_class_map and topic:
        parts = topic.split(".")
        keys_to_try = [topic] + ([".".join(parts[-2:]), parts[-1]] if len(parts) >= 2 else [parts[-1]])
        for key in keys_to_try:
            if key in topic_class_map:
                try:
                    return topic_class_map[key](**result)
                except Exception:
                    break  # fall through to plain dict

    return result


# ConnectMessageExtractor  — JSON / polling mode


class ConnectMessageExtractor:
    """
    Wraps a raw Java ChangeEvent (JSON / polling mode) and extracts its fields.

    No JPype SourceRecord access — parses the JSON string produced by
    the Debezium engine's JSON serializer.

    Usage::

        extractor = ConnectMessageExtractor(java_change_event)
        print(extractor.destination, extractor.op, extractor.after)
    """

    def __init__(self, java_record: Any) -> None:
        self._record = java_record
        self._payload: dict[str, Any] | None = None
        self._schema_raw: dict[str, Any] | None = None
        self._parse()

    def _parse(self) -> None:
        dest = self._record.destination()
        self._destination = str(dest) if dest else ""

        part = self._record.kafkaPartition() if hasattr(self._record, "kafkaPartition") else None
        self._partition = int(part) if part is not None else None

        raw_key = self._record.key()
        self._raw_key = str(raw_key) if raw_key else None

        raw_val = self._record.value()
        if not raw_val:
            self._payload = {}
            return

        val_dict: dict[str, Any] = json.loads(str(raw_val))
        self._schema_raw = val_dict.get("schema")
        self._payload = val_dict.get("payload", val_dict)

    @property
    def destination(self) -> str:
        return self._destination

    @property
    def partition(self) -> int | None:
        return self._partition

    @property
    def raw_key(self) -> str | None:
        return self._raw_key

    @property
    def schema(self) -> dict[str, Any] | None:
        return self._schema_raw

    @property
    def op(self) -> str | None:
        return (self._payload or {}).get("op")

    @property
    def before(self) -> dict[str, Any] | None:
        return (self._payload or {}).get("before")

    @property
    def after(self) -> dict[str, Any] | None:
        return (self._payload or {}).get("after")

    @property
    def ts_ms(self) -> int | None:
        v = (self._payload or {}).get("ts_ms")
        return int(v) if v is not None else None

    @property
    def source(self) -> dict[str, Any] | None:
        return (self._payload or {}).get("source")


# SourceRecordExtractor  — Connect mode


class SourceRecordExtractor:
    """
    Wraps a raw Java SourceRecord (Connect mode) and converts it to Python.

    Zero JSON serialization overhead — uses ``struct_to_dict`` internally.

    Args:
        source_record: Raw Java SourceRecord from ``handleConnectBatch``.
        conversion_config: Optional ConversionConfig.
        topic_class_map: Optional dict mapping topic/table names to Python classes
            for typed ``after_typed`` / ``before_typed`` access.

    Usage::

        extractor = SourceRecordExtractor(
            source_record,
            conversion_config=ConversionConfig(numeric_mode="numpy"),
            topic_class_map={"inventory.customers": Customer},
        )
        print(extractor.destination)
        print(extractor.after)        # plain dict
        print(extractor.after_typed)  # Customer instance (if mapped)
    """

    def __init__(
        self,
        source_record: Any,
        conversion_config: ConversionConfig | None = None,
        topic_class_map: Mapping[str, type[Any]] | None = None,
    ) -> None:
        self._record = source_record
        self._cfg = conversion_config or ConversionConfig()
        self._topic_class_map = topic_class_map or {}
        self._extracted = False
        self._destination: str = ""
        self._partition: int | None = None
        self._key_dict: dict[str, Any] | None = None
        self._before: dict[str, Any] | None = None
        self._after: dict[str, Any] | None = None
        self._op: str | None = None
        self._ts_ms: int | None = None
        self._extract()

    def _extract(self) -> None:
        rec = self._record

        topic = rec.topic()
        self._destination = str(topic) if topic else ""

        part = rec.kafkaPartition()
        self._partition = int(part) if part is not None else None

        # Key
        key_schema = rec.keySchema()
        key_val = rec.key()
        if key_schema and key_val is not None:
            self._key_dict = struct_to_dict(key_val, key_schema, self._cfg)

        # Value
        val_schema = rec.valueSchema()
        val = rec.value()
        if val_schema and val is not None:
            row = struct_to_dict(
                val,
                val_schema,
                self._cfg,
                topic_class_map=None,  # raw dict first
                topic=self._destination,
            )
            self._op = row.get("op")
            ts = row.get("ts_ms")
            self._ts_ms = int(ts) if ts is not None else None
            self._before = row.get("before")
            self._after = row.get("after")

        self._extracted = True

    @property
    def destination(self) -> str:
        return self._destination

    @property
    def partition(self) -> int | None:
        return self._partition

    @property
    def key_dict(self) -> dict[str, Any] | None:
        return self._key_dict

    @property
    def op(self) -> str | None:
        return self._op

    @property
    def ts_ms(self) -> int | None:
        return self._ts_ms

    @property
    def before(self) -> dict[str, Any] | None:
        return self._before

    @property
    def after(self) -> dict[str, Any] | None:
        return self._after

    def _apply_class_map(self, d: dict[str, Any] | None) -> Any:
        if not d or not self._topic_class_map:
            return d
        parts = self._destination.split(".")
        keys = [self._destination] + ([".".join(parts[-2:]), parts[-1]] if len(parts) >= 2 else [parts[-1]])
        for key in keys:
            if key in self._topic_class_map:
                try:
                    return self._topic_class_map[key](**d)
                except Exception:
                    break
        return d

    @property
    def after_typed(self) -> Any:
        """``after`` as a typed class instance if topic_class_map matches."""
        return self._apply_class_map(self._after)

    @property
    def before_typed(self) -> Any:
        """``before`` as a typed class instance if topic_class_map matches."""
        return self._apply_class_map(self._before)

    @property
    def raw_key(self) -> str | None:
        """JSON string of key_dict for compatibility with DebeziumEventModel."""
        if self._key_dict is None:
            return None
        return json.dumps(self._key_dict)


# Batch helpers


def extract_all(
    records: list[Any],
    conversion_config: ConversionConfig | None = None,
) -> list[ConnectMessageExtractor]:
    """Wrap a batch of JSON-mode ChangeEvent records."""
    return [ConnectMessageExtractor(r) for r in records]


def extract_connect_all(
    records: list[Any],
    conversion_config: ConversionConfig | None = None,
    topic_class_map: Mapping[str, type[Any]] | None = None,
) -> list[SourceRecordExtractor]:
    """Wrap a batch of Connect-mode SourceRecord objects."""
    return [
        SourceRecordExtractor(r, conversion_config=conversion_config, topic_class_map=topic_class_map) for r in records
    ]


# Debug utility


def print_record_info(source_record: Any) -> None:
    """Print a human-readable summary of a raw Java SourceRecord for debugging."""
    try:
        print(f"  topic        : {source_record.topic()}")
        print(f"  partition    : {source_record.kafkaPartition()}")
        print(f"  key schema   : {source_record.keySchema()}")
        print(f"  value schema : {source_record.valueSchema()}")
        ks = source_record.keySchema()
        if ks:
            print(f"  key fields   : {[str(f.name()) for f in ks.fields()]}")
        vs = source_record.valueSchema()
        if vs:
            print(f"  value fields : {[str(f.name()) for f in vs.fields()]}")
    except Exception as exc:
        print(f"  [print_record_info error: {exc}]")
