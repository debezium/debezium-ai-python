"""Unit tests for ID strategies."""

from __future__ import annotations

from typing import Any

import pytest

from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.transformation.id_strategy import (
    CompositeIdStrategy,
    CustomIdStrategy,
    TablePkIdStrategy,
    resolve_id_strategy,
)


def _make_event(
    destination: str, key: str | None, op: str = "c", row: dict[str, Any] | None = None
) -> DebeziumEventModel:
    return DebeziumEventModel.from_dict(
        destination=destination,
        key=key,
        payload={"op": op, "after": row or {}, "before": None},
    )


class TestTablePkIdStrategy:
    def test_basic_id(self) -> None:
        event = _make_event("srv.public.orders", '{"id": 42}')
        strategy = TablePkIdStrategy()
        assert strategy.generate(event) == "public.orders:42"

    def test_composite_key_in_json(self) -> None:
        event = _make_event("srv.public.items", '{"sku": "A", "wh": "B"}')
        strategy = TablePkIdStrategy()
        doc_id = strategy.generate(event)
        assert doc_id == "public.items:A|B"

    def test_pk_fields_fallback(self) -> None:
        event = _make_event(
            "srv.public.users",
            None,
            row={"email": "x@y.com", "tenant": "acme"},
        )
        strategy = TablePkIdStrategy(pk_fields=["email", "tenant"])
        doc_id = strategy.generate(event)
        assert doc_id == "public.users:x@y.com|acme"

    def test_no_primary_key_raises(self) -> None:
        event = _make_event("s.t.items", None, row={"k": "v"})
        strategy = TablePkIdStrategy()
        with pytest.raises(ValueError, match="No primary key found"):
            strategy.generate(event)

    def test_single_segment_destination(self) -> None:
        event = _make_event("orders", '{"id": 1}')
        strategy = TablePkIdStrategy()
        assert strategy.generate(event) == "orders:1"


class TestCompositeIdStrategy:
    def test_produces_hash(self) -> None:
        event = _make_event(
            "srv.public.items",
            None,
            row={"sku": "SKU-001", "wh": "WH-A"},
        )
        strategy = CompositeIdStrategy(pk_fields=["sku", "wh"])
        doc_id = strategy.generate(event)
        assert doc_id.startswith("public.items:")
        hash_part = doc_id.split(":")[1]
        assert len(hash_part) == 20

    def test_deterministic(self) -> None:
        event = _make_event(
            "s.t.x",
            None,
            row={"a": 1, "b": 2},
        )
        strategy = CompositeIdStrategy(pk_fields=["a", "b"])
        assert strategy.generate(event) == strategy.generate(event)

    def test_requires_pk_fields(self) -> None:
        with pytest.raises(ValueError, match="requires at least one pk_field"):
            CompositeIdStrategy(pk_fields=[])


class TestCustomIdStrategy:
    def test_uses_callable(self) -> None:
        strategy = CustomIdStrategy(fn=lambda e: f"custom:{e.table_name}")
        event = _make_event("srv.public.things", None)
        assert strategy.generate(event) == "custom:things"


class TestResolveIdStrategy:
    def test_resolve_table_pk_by_name(self) -> None:
        strategy = resolve_id_strategy("table_pk")
        assert isinstance(strategy, TablePkIdStrategy)

    def test_resolve_composite_by_name(self) -> None:
        strategy = resolve_id_strategy("composite", pk_fields=["id", "tenant"])
        assert isinstance(strategy, CompositeIdStrategy)

    def test_returns_instance_unchanged(self) -> None:
        original = TablePkIdStrategy()
        assert resolve_id_strategy(original) is original

    def test_unknown_name_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown id_strategy"):
            resolve_id_strategy("bogus")
