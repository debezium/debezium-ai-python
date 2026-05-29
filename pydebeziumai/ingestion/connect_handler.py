"""Connect-mode ingestion handler.

Uses JPype + ``io.debezium.embedded.Connect`` format to access Debezium
SourceRecord objects directly, avoiding the JSON serialization round-trip.

Wires the PR #400 ``SourceRecordExtractor`` into the PyDebeziumAI pipeline:

    Java SourceRecord
        → SourceRecordExtractor   (struct_to_dict, full type conversion)
            → DebeziumRecord
                → DebeziumEventModel
                    → SyncManager callbacks
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from pydebeziumai.ingestion.base import BaseIngestionHandler
from pydebeziumai.models.connect_message import ConversionConfig, SourceRecordExtractor
from pydebeziumai.models.datastructures import DebeziumRecord
from pydebeziumai.models.event import DebeziumEventModel

logger = logging.getLogger(__name__)


class ConnectIngestionHandler(BaseIngestionHandler):
    """
    Connect-mode (JPype + io.debezium.embedded.Connect) ingestion handler.

    Matches the architecture from PR #400's ``debezium_connect.py`` +
    ``BaseConnectChangeHandler``, integrated into the PyDebeziumAI pipeline.

    Args:
        conversion_config: Controls type conversion (numeric_mode, tz_aware).
        topic_class_map: Maps topic names to Python classes for typed access.

    Usage::

        handler = ConnectIngestionHandler(
            conversion_config=ConversionConfig(numeric_mode="native"),
        )
        handler.add_event_callback(sync_manager.handle_event)
        engine = handler.build_engine(debezium_props)
        engine.run()
    """

    def __init__(
        self,
        conversion_config: ConversionConfig | None = None,
        topic_class_map: Mapping[str, type[Any]] | None = None,
    ) -> None:
        super().__init__()
        self._cfg = conversion_config or ConversionConfig()
        self._topic_class_map = topic_class_map or {}

    def _process_source_record(self, source_record: Any) -> None:
        """Convert one SourceRecord → DebeziumRecord → DebeziumEventModel → dispatch."""
        extractor = SourceRecordExtractor(
            source_record,
            conversion_config=self._cfg,
            topic_class_map=self._topic_class_map or None,
        )
        record = DebeziumRecord(
            destination=extractor.destination,
            op=extractor.op or "r",
            before=extractor.before,
            after=extractor.after,
            ts_ms=extractor.ts_ms,
            key=extractor.raw_key,
            partition=extractor.partition,
        )
        event = DebeziumEventModel.from_record(record)
        self._dispatch_event(event)

    def _make_consumer_class(self) -> type:
        """
        Factory: create a JPype ChangeConsumer after JVM starts.

        Matches PR #400's ``_create_connect_consumer()`` factory pattern.
        Deferred import ensures Java classes are not resolved at import time.
        """
        import traceback

        import jpype

        outer = self

        @jpype.JImplements("io.debezium.engine.DebeziumEngine$ChangeConsumer")
        class _ConnectConsumer:
            @jpype.JOverride  # type: ignore[untyped-decorator]
            def handleBatch(self, records: Any, committer: Any) -> None:  # noqa: N802
                for record in records:
                    try:
                        outer._process_source_record(record)
                    except Exception as exc:
                        logger.warning(
                            "Connect-mode record error: %s\n%s",
                            exc,
                            traceback.format_exc(),
                        )
                        outer._dispatch_error(exc, record)
                    finally:
                        committer.markProcessed(record)
                committer.markBatchFinished()

            @jpype.JOverride  # type: ignore[untyped-decorator]
            def supportsTombstoneEvents(self) -> bool:  # noqa: N802
                return True

        return _ConnectConsumer

    def build_engine(self, properties: dict[str, str]) -> Any:
        """
        Build a Connect-format DebeziumEngine via JPype.

        Uses ``io.debezium.embedded.Connect`` format (Debezium 3.0+), which
        passes raw SourceRecord objects instead of JSON strings — matching the
        PR #400 ``DebeziumConnectEngine`` implementation.
        """
        import jpype
        from pydbzengine._jvm import DebeziumEngine, Properties

        # Load Connect format class (requires Debezium 3.0+ JARs)
        try:
            ConnectFormat = jpype.JClass("io.debezium.embedded.Connect")  # noqa: N806
            logger.info("Loaded io.debezium.embedded.Connect format")
        except Exception as exc:
            raise RuntimeError(
                f"Connect format unavailable: {exc}. Run 'python tools/setup_jars.py' to install Debezium 3.0+ JARs."
            ) from exc

        props = Properties()
        for k, v in properties.items():
            props.setProperty(str(k), str(v))

        consumer = self._make_consumer_class()()
        return DebeziumEngine.create(ConnectFormat).using(props).notifying(consumer).build()
