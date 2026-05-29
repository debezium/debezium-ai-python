"""JSON-mode ingestion handler.

Wraps pydbzengine's BasePythonChangeHandler to consume CDC events serialized
as JSON strings, parse them into canonical DebeziumEventModel instances, and
dispatch to registered callbacks.

This mode works without a JVM bridge for record schema access — the Debezium
engine serializes events to JSON before handing them to Python.
"""

from __future__ import annotations

import logging
from typing import Any

from pydebeziumai.ingestion.base import BaseIngestionHandler
from pydebeziumai.models.event import DebeziumEventModel

logger = logging.getLogger(__name__)


class JsonIngestionHandler(BaseIngestionHandler):
    """
    JSON-mode ingestion.

    Usage::

        handler = JsonIngestionHandler()
        handler.add_event_callback(sync_manager.handle_event)
        engine = handler.build_engine({
            "name": "engine",
            "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
            ...
        })
        engine.run()
    """

    def _make_handler_class(self) -> type:
        """
        Factory: create the pydbzengine handler class after the JVM is started.

        Deferred import prevents JPype from attempting Java class resolution
        at module import time (before the JVM is initialised).
        """
        from pydbzengine import BasePythonChangeHandler

        outer = self

        class _JsonHandler(BasePythonChangeHandler):  # type: ignore[misc]
            def handleJsonBatch(self, records: list[Any]) -> None:  # noqa: N802
                for record in records:
                    dest = "unknown"
                    try:
                        dest = str(record.destination()) if record.destination() else "unknown"
                        event = DebeziumEventModel.from_json_record(record)
                        outer._dispatch_event(event)
                    except Exception as exc:
                        logger.warning(
                            "Failed to parse CDC record at %r: %s",
                            dest,
                            exc,
                        )
                        outer._dispatch_error(exc, record)

        return _JsonHandler

    def build_engine(self, properties: dict[str, str]) -> Any:
        """Build and return a configured DebeziumJsonEngine."""
        from pydbzengine import DebeziumJsonEngine

        handler_cls = self._make_handler_class()
        return DebeziumJsonEngine(properties=properties, handler=handler_cls())
