"""Shared pytest fixtures for PyDebeziumAI test suite."""

from __future__ import annotations

import pytest

from pydebeziumai.models.event import DebeziumEventModel

# ── Canonical event fixtures ──────────────────────────────────────────────────


@pytest.fixture
def insert_event() -> DebeziumEventModel:
    return DebeziumEventModel.from_dict(
        destination="myserver.public.products",
        key='{"id": 1}',
        payload={
            "before": None,
            "after": {"id": 1, "name": "Widget A", "price": 9.99, "category": "tools"},
            "op": "c",
            "ts_ms": 1_700_000_000_000,
        },
    )


@pytest.fixture
def update_event() -> DebeziumEventModel:
    return DebeziumEventModel.from_dict(
        destination="myserver.public.products",
        key='{"id": 1}',
        payload={
            "before": {"id": 1, "name": "Widget A", "price": 9.99, "category": "tools"},
            "after": {"id": 1, "name": "Widget A Pro", "price": 14.99, "category": "tools"},
            "op": "u",
            "ts_ms": 1_700_000_001_000,
        },
    )


@pytest.fixture
def delete_event() -> DebeziumEventModel:
    return DebeziumEventModel.from_dict(
        destination="myserver.public.products",
        key='{"id": 1}',
        payload={
            "before": {"id": 1, "name": "Widget A Pro", "price": 14.99, "category": "tools"},
            "after": None,
            "op": "d",
            "ts_ms": 1_700_000_002_000,
        },
    )


@pytest.fixture
def snapshot_event() -> DebeziumEventModel:
    return DebeziumEventModel.from_dict(
        destination="myserver.public.products",
        key='{"id": 42}',
        payload={
            "before": None,
            "after": {"id": 42, "name": "Gadget Z", "price": 99.99, "category": "electronics"},
            "op": "r",
            "ts_ms": 1_700_000_003_000,
        },
    )
