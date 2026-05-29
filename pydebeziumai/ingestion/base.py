"""Abstract base for all PyDebeziumAI ingestion handlers.

Each concrete handler wraps a pydbzengine engine (JSON or Connect mode)
and dispatches normalized DebeziumEventModel instances to registered callbacks.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from pydebeziumai.models.event import DebeziumEventModel

logger = logging.getLogger(__name__)


class BaseIngestionHandler(ABC):
    """
    Abstract base that all ingestion handlers extend.

    Subclasses implement engine construction; this base handles callback
    registration and dispatching so the sync pipeline stays decoupled.

    Usage::

        handler = JsonIngestionHandler()
        handler.add_event_callback(sync_manager.handle_event)
        handler.add_error_callback(my_error_logger)
        engine = handler.build_engine(debezium_props)
        engine.run()
    """

    def __init__(self) -> None:
        self._event_callbacks: list[Callable[[DebeziumEventModel], None]] = []
        self._error_callbacks: list[Callable[[Exception, Any], None]] = []

    # ── Registration ──────────────────────────────────────────────────────────

    def add_event_callback(self, cb: Callable[[DebeziumEventModel], None]) -> None:
        """Register a callback that receives each normalized DebeziumEventModel."""
        self._event_callbacks.append(cb)

    def add_error_callback(self, cb: Callable[[Exception, Any], None]) -> None:
        """Register a callback for parse/dispatch errors (receives exc + raw record)."""
        self._error_callbacks.append(cb)

    # ── Dispatching ───────────────────────────────────────────────────────────

    def _dispatch_event(self, event: DebeziumEventModel) -> None:
        """Dispatch a normalized event to all registered callbacks."""
        for cb in self._event_callbacks:
            try:
                cb(event)
            except Exception as exc:
                logger.error("Event callback raised an exception: %s", exc, exc_info=True)

    def _dispatch_error(self, exc: Exception, record: Any = None) -> None:
        """Dispatch a parse/normalization error to all registered error callbacks."""
        for cb in self._error_callbacks:
            try:
                cb(exc, record)
            except Exception as inner:
                logger.error("Error callback raised an exception: %s", inner, exc_info=True)

    # ── To be implemented by subclasses ───────────────────────────────────────

    @abstractmethod
    def build_engine(self, properties: dict[str, str]) -> Any:
        """Build and return a configured pydbzengine engine instance."""
        raise NotImplementedError
