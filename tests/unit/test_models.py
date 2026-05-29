"""Unit tests for canonical event models (DebeziumEventModel, DebeziumPayloadModel)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from pydebeziumai.models.event import DebeziumEventModel, DebeziumPayloadModel


class TestDebeziumPayloadModel:
    def test_valid_ops_accepted(self) -> None:
        for op in ("c", "u", "d", "r"):
            p = DebeziumPayloadModel(op=op)
            assert p.op == op

    def test_invalid_op_raises(self) -> None:
        with pytest.raises(ValidationError, match="Invalid CDC operation"):
            DebeziumPayloadModel(op="x")

    def test_current_row_insert(self) -> None:
        payload = DebeziumPayloadModel(
            after={"id": 1, "name": "foo"},
            op="c",
        )
        assert payload.current_row == {"id": 1, "name": "foo"}

    def test_current_row_delete(self) -> None:
        payload = DebeziumPayloadModel(
            before={"id": 1, "name": "foo"},
            op="d",
        )
        assert payload.current_row == {"id": 1, "name": "foo"}

    def test_current_row_update_returns_after(self) -> None:
        payload = DebeziumPayloadModel(
            before={"id": 1, "name": "old"},
            after={"id": 1, "name": "new"},
            op="u",
        )
        assert payload.current_row == {"id": 1, "name": "new"}

    def test_is_insert(self) -> None:
        assert DebeziumPayloadModel(op="c").is_insert
        assert DebeziumPayloadModel(op="r").is_insert
        assert not DebeziumPayloadModel(op="u").is_insert

    def test_is_update(self) -> None:
        assert DebeziumPayloadModel(op="u").is_update

    def test_is_delete(self) -> None:
        assert DebeziumPayloadModel(op="d").is_delete


class TestDebeziumEventModel:
    def test_from_dict_basic(self) -> None:
        event = DebeziumEventModel.from_dict(
            destination="srv.public.orders",
            key='{"id": 99}',
            payload={"op": "c", "after": {"id": 99, "total": 150.0}},
        )
        assert event.table_name == "orders"
        assert event.schema_name == "public"
        assert event.namespace == "public.orders"

    def test_table_name_single_segment(self) -> None:
        event = DebeziumEventModel.from_dict("orders", None, {"op": "c"})
        assert event.table_name == "orders"
        assert event.schema_name == ""
        assert event.namespace == "orders"

    def test_extract_pk_from_key(self) -> None:
        event = DebeziumEventModel.from_dict(
            "srv.public.products",
            '{"id": 42}',
            {"op": "c", "after": {"id": 42, "name": "X"}},
        )
        assert event.extract_primary_key() == "42"

    def test_extract_pk_from_fields(self) -> None:
        event = DebeziumEventModel.from_dict(
            "srv.public.items",
            None,
            {"op": "c", "after": {"sku": "ABC-001", "warehouse": "WH-A"}},
        )
        pk = event.extract_primary_key(pk_fields=["sku", "warehouse"])
        assert pk == "ABC-001|WH-A"

    def test_extract_pk_fallback_hash(self) -> None:
        event = DebeziumEventModel.from_dict(
            "srv.public.items",
            None,
            {"op": "c", "after": {"sku": "X", "qty": 5}},
        )
        # No key, no pk_fields → deterministic hash
        pk = event.extract_primary_key()
        assert len(pk) == 16  # 16-char hex hash
        # Same event always produces same hash
        assert pk == event.extract_primary_key()

    def test_from_json_record(self) -> None:
        """Test from_json_record using a mock ChangeEvent."""

        class MockRecord:
            def destination(self) -> str | None:
                return "srv.public.orders"

            def key(self) -> str | None:
                return '{"id": 7}'

            def value(self) -> str | None:
                return json.dumps(
                    {
                        "payload": {
                            "op": "c",
                            "after": {"id": 7, "amount": 200},
                            "ts_ms": 12345,
                        }
                    }
                )

        event = DebeziumEventModel.from_json_record(MockRecord())
        assert event.table_name == "orders"
        assert event.payload.op == "c"
        assert event.payload.ts_ms == 12345

    def test_from_json_record_flat_envelope(self) -> None:
        """Flat (no payload wrapper) JSON mode."""

        class MockRecord:
            def destination(self) -> str | None:
                return "srv.public.users"

            def key(self) -> str | None:
                return None

            def value(self) -> str | None:
                return json.dumps(
                    {
                        "op": "d",
                        "before": {"id": 1, "email": "a@b.com"},
                        "after": None,
                    }
                )

        event = DebeziumEventModel.from_json_record(MockRecord())
        assert event.payload.op == "d"
        assert event.payload.before == {"id": 1, "email": "a@b.com"}

    def test_empty_value_raises(self) -> None:
        class MockRecord:
            def destination(self) -> str | None:
                return "test"

            def key(self) -> str | None:
                return None

            def value(self) -> str | None:
                return None

        with pytest.raises(ValueError, match="Empty CDC event value"):
            DebeziumEventModel.from_json_record(MockRecord())
