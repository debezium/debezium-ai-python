"""Unit tests for metadata sanitization utility."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from pydebeziumai.transformation.sanitizer import sanitize_metadata


def test_sanitize_basic_types() -> None:
    meta = {
        "null_val": None,
        "bool_val": True,
        "int_val": 42,
        "float_val": 3.14,
        "str_val": "hello",
    }
    cleaned = sanitize_metadata(meta)
    assert cleaned["null_val"] == "null"
    assert cleaned["bool_val"] is True
    assert cleaned["int_val"] == 42
    assert cleaned["float_val"] == 3.14
    assert cleaned["str_val"] == "hello"


def test_sanitize_decimal() -> None:
    meta = {
        "dec_val": Decimal("10.99"),
    }
    cleaned = sanitize_metadata(meta)
    assert cleaned["dec_val"] == 10.99
    assert isinstance(cleaned["dec_val"], float)


def test_sanitize_bytes_and_bytearray() -> None:
    meta = {
        "bytes_val": b"hello\x00world",
        "bytearray_val": bytearray(b"test"),
    }
    cleaned = sanitize_metadata(meta)
    assert cleaned["bytes_val"] == "68656c6c6f00776f726c64"
    assert cleaned["bytearray_val"] == "74657374"


def test_sanitize_datetime_types() -> None:
    dt = datetime(2026, 8, 15, 10, 30, 0)
    d = date(2026, 8, 15)
    t = time(10, 30, 0)
    delta = timedelta(hours=2, minutes=30)

    meta = {
        "datetime_val": dt,
        "date_val": d,
        "time_val": t,
        "timedelta_val": delta,
    }
    cleaned = sanitize_metadata(meta)
    assert cleaned["datetime_val"] == dt.isoformat()
    assert cleaned["date_val"] == d.isoformat()
    assert cleaned["time_val"] == t.isoformat()
    assert cleaned["timedelta_val"] == 9000.0  # 2.5 hours in seconds


def test_sanitize_collections() -> None:
    meta = {
        "dict_val": {"a": 1},
        "list_val": [1, 2],
        "tuple_val": (3, 4),
        "set_val": {5, 6},
    }
    cleaned = sanitize_metadata(meta)
    assert cleaned["dict_val"] == "{'a': 1}"
    assert cleaned["list_val"] == "[1, 2]"
    assert cleaned["tuple_val"] == "(3, 4)"
    # Set string representation ordering can vary, so just verify it is a string
    assert isinstance(cleaned["set_val"], str)
