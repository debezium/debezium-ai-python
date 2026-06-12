from typing import Any
from unittest.mock import Mock

import pytest
from pydbzengine._jvm import Properties  # noqa: F401

from pydebeziumai.ingestion.base import BaseIngestionHandler
from pydebeziumai.ingestion.connect_handler import ConnectIngestionHandler
from pydebeziumai.ingestion.json_handler import JsonIngestionHandler
from pydebeziumai.models.event import DebeziumEventModel


class DummyIngestionHandler(BaseIngestionHandler):
    def build_engine(self, properties: dict[str, str]) -> Any:
        return None


def test_dispatch_event_propagates_without_error_callbacks() -> None:
    handler = DummyIngestionHandler()

    def failing_callback(event: DebeziumEventModel) -> None:
        raise ValueError("Callback failed")

    handler.add_event_callback(failing_callback)

    event = Mock(spec=DebeziumEventModel)
    with pytest.raises(ValueError, match="Callback failed"):
        handler._dispatch_event(event)


def test_dispatch_event_swallows_with_error_callbacks() -> None:
    handler = DummyIngestionHandler()

    def failing_callback(event: DebeziumEventModel) -> None:
        raise ValueError("Callback failed")

    errors = []

    def error_callback(exc: Exception, record: Any) -> None:
        errors.append(exc)

    handler.add_event_callback(failing_callback)
    handler.add_error_callback(error_callback)

    event = Mock(spec=DebeziumEventModel)

    # Should not raise exception
    handler._dispatch_event(event)
    assert len(errors) == 1
    assert isinstance(errors[0], ValueError)


def test_json_handler_propagates_exception_without_error_callbacks() -> None:
    handler = JsonIngestionHandler()
    handler_cls = handler._make_handler_class()
    json_handler_inst = handler_cls()

    # None cannot be parsed, raising exception
    with pytest.raises(AttributeError):
        json_handler_inst.handleJsonBatch([None])


def test_json_handler_calls_error_callback_and_swallows() -> None:
    handler = JsonIngestionHandler()
    errors = []
    handler.add_error_callback(lambda exc, rec: errors.append(exc))

    handler_cls = handler._make_handler_class()
    json_handler_inst = handler_cls()

    # Should call the error callback and not raise
    json_handler_inst.handleJsonBatch([None])
    assert len(errors) == 1


def test_connect_handler_propagates_exception_without_error_callbacks() -> None:
    handler = ConnectIngestionHandler()
    consumer_cls = handler._make_consumer_class()
    consumer_inst = consumer_cls()

    mock_committer = Mock()

    # None cannot be parsed, raising exception in _process_source_record
    with pytest.raises(AttributeError):
        consumer_inst.handleBatch([None], mock_committer)

    # Committer should NOT be marked processed
    mock_committer.markProcessed.assert_not_called()


def test_connect_handler_calls_error_callback_and_swallows() -> None:
    handler = ConnectIngestionHandler()
    errors = []
    handler.add_error_callback(lambda exc, rec: errors.append(exc))

    consumer_cls = handler._make_consumer_class()
    consumer_inst = consumer_cls()

    mock_committer = Mock()

    # Should call the error callback, not raise, and mark processed
    consumer_inst.handleBatch([None], mock_committer)
    assert len(errors) == 1
    mock_committer.markProcessed.assert_called_once_with(None)
    mock_committer.markBatchFinished.assert_called_once()
