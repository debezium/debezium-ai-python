"""Deterministic document ID strategies for vector store synchronization.

A stable, unique document ID per logical row is the foundation of correct
CDC-to-vector-store synchronization. The same row must always produce the
same ID across insert, update, and delete events so upsert/replace semantics
work correctly.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Callable

from pydebeziumai.models.event import DebeziumEventModel


class IdStrategy(ABC):
    """Abstract ID strategy — produce a stable document ID from a CDC event."""

    @abstractmethod
    def generate(self, event: DebeziumEventModel) -> str:
        """Return a stable, unique document ID for this event's logical row."""
        ...


class TablePkIdStrategy(IdStrategy):
    """
    Default strategy: ``{schema}.{table}:{primary_key}``.

    Examples:
        - ``public.orders:42``
        - ``public.customers:john@example.com``
        - ``inventory.products:SKU-001|warehouse-A``  (composite key)

    Uses ``event.extract_primary_key(pk_fields)`` which reads from the
    Debezium JSON key field first, then falls back to payload columns.
    """

    def __init__(self, pk_fields: list[str] | None = None) -> None:
        self.pk_fields = pk_fields

    def generate(self, event: DebeziumEventModel) -> str:
        prefix = event.namespace
        pk = event.extract_primary_key(self.pk_fields)
        if pk is None:
            raise ValueError(
                f"No primary key found for event at destination {event.destination!r}. "
                f"Please define a primary key in your database or configure 'pk_fields' "
                f"to specify which columns to use as the primary key."
            )
        return f"{prefix}:{pk}"


class CompositeIdStrategy(IdStrategy):
    """
    SHA-256 hash of specified PK fields — safe for composite or binary keys.

    Produces IDs like ``public.orders:a3f2c1d4e5b6...`` (20-char hex prefix).
    """

    def __init__(self, pk_fields: list[str]) -> None:
        if not pk_fields:
            raise ValueError("CompositeIdStrategy requires at least one pk_field")
        self.pk_fields = pk_fields

    def generate(self, event: DebeziumEventModel) -> str:
        prefix = event.namespace
        row = event.payload.current_row or {}
        values = {f: row.get(f) for f in self.pk_fields}
        values_str = json.dumps(values, sort_keys=True, default=str)
        pk_hash = hashlib.sha256(values_str.encode()).hexdigest()[:20]
        return f"{prefix}:{pk_hash}"


class CustomIdStrategy(IdStrategy):
    """User-supplied callable ID strategy for full control."""

    def __init__(self, fn: Callable[[DebeziumEventModel], str]) -> None:
        self._fn = fn

    def generate(self, event: DebeziumEventModel) -> str:
        return self._fn(event)


_BUILTIN: dict[str, type[IdStrategy]] = {
    "table_pk": TablePkIdStrategy,
    "composite": CompositeIdStrategy,
}


def resolve_id_strategy(
    strategy: str | IdStrategy,
    **kwargs: object,
) -> IdStrategy:
    """
    Resolve a strategy name string or an existing IdStrategy instance.

    Args:
        strategy: ``"table_pk"``, ``"composite"``, or an IdStrategy instance.
        **kwargs: Forwarded to the strategy constructor (e.g. ``pk_fields``).

    Raises:
        ValueError: If the name is not recognised.
    """
    if isinstance(strategy, IdStrategy):
        return strategy
    if strategy in _BUILTIN:
        return _BUILTIN[strategy](**kwargs)
    raise ValueError(f"Unknown id_strategy: {strategy!r}. Choose from {list(_BUILTIN)} or pass an IdStrategy instance.")
