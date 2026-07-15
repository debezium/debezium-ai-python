"""Unit tests for the SyncManager."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever

from pydebeziumai.adapters.base import VectorStoreAdapter
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.sync.manager import DeadLetterQueue, RetryConfig, SyncManager
from pydebeziumai.transformation.document_builder import DocumentBuilder


class FakeVectorStoreAdapter(VectorStoreAdapter):
    """A simple mock/fake implementation of VectorStoreAdapter for testing."""

    def __init__(self) -> None:
        self.upserts: list[Document] = []
        self.deletes: list[str] = []
        self.should_fail = False
        self.failure_count = 0
        self.max_failures = 0

    def upsert(self, document: Document) -> None:
        if self.should_fail and self.failure_count < self.max_failures:
            self.failure_count += 1
            raise ConnectionError("Simulated transient connection failure")
        self.upserts.append(document)

    def upsert_batch(self, documents: list[Document]) -> None:
        if self.should_fail and self.failure_count < self.max_failures:
            self.failure_count += 1
            raise ConnectionError("Simulated transient connection failure")
        self.upserts.extend(documents)

    def delete(self, doc_id: str) -> None:
        if self.should_fail and self.failure_count < self.max_failures:
            self.failure_count += 1
            raise ConnectionError("Simulated transient connection failure")
        self.deletes.append(doc_id)

    def delete_batch(self, doc_ids: list[str]) -> None:
        if self.should_fail and self.failure_count < self.max_failures:
            self.failure_count += 1
            raise ConnectionError("Simulated transient connection failure")
        self.deletes.extend(doc_ids)

    def as_retriever(self, **kwargs: object) -> BaseRetriever:
        raise NotImplementedError("Not needed for sync tests")


def test_sync_insert_and_snapshot(
    insert_event: DebeziumEventModel,
    snapshot_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        soft_delete=False,
    )

    # Sync insert event
    manager.sync(insert_event)
    assert len(adapter.upserts) == 1
    assert adapter.upserts[0].id == "public.products:1"
    assert adapter.upserts[0].page_content == "id: 1\nname: Widget A\nprice: 9.99\ncategory: tools"
    assert adapter.upserts[0].metadata["_op"] == "c"
    assert adapter.upserts[0].metadata["_table"] == "products"

    # Sync snapshot event
    manager.sync(snapshot_event)
    assert len(adapter.upserts) == 2
    assert adapter.upserts[1].id == "public.products:42"
    assert adapter.upserts[1].metadata["_op"] == "r"


def test_sync_update(
    update_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        soft_delete=False,
    )

    # Sync update event (should delete then upsert)
    manager.sync(update_event)
    assert len(adapter.deletes) == 1
    assert adapter.deletes[0] == "public.products:1"
    assert len(adapter.upserts) == 1
    assert adapter.upserts[0].id == "public.products:1"
    assert adapter.upserts[0].metadata["_op"] == "u"
    assert adapter.upserts[0].page_content == "id: 1\nname: Widget A Pro\nprice: 14.99\ncategory: tools"


def test_sync_delete_hard(
    delete_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        soft_delete=False,
    )

    # Sync delete event (should delete)
    manager.sync(delete_event)
    assert len(adapter.deletes) == 1
    assert adapter.deletes[0] == "public.products:1"
    assert len(adapter.upserts) == 0


def test_sync_delete_soft(
    delete_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        soft_delete=True,
    )

    # Sync delete event with soft delete (should upsert with _is_deleted=True)
    manager.sync(delete_event)
    assert len(adapter.deletes) == 0
    assert len(adapter.upserts) == 1
    assert adapter.upserts[0].id == "public.products:1"
    assert adapter.upserts[0].metadata["_is_deleted"] is True
    assert adapter.upserts[0].metadata["_op"] == "d"
    # Content should be based on the 'before' block
    assert adapter.upserts[0].page_content == "id: 1\nname: Widget A Pro\nprice: 14.99\ncategory: tools"


@patch("time.sleep", return_value=None)
def test_sync_retry_success(
    mock_sleep: MagicMock,
    insert_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    adapter.should_fail = True
    adapter.max_failures = 2  # Fail twice, succeed on 3rd attempt (retries = 2)

    retry_config = RetryConfig(max_retries=3, initial_delay=0.1, backoff_factor=2.0)
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        retry_config=retry_config,
    )

    manager.sync(insert_event)
    assert len(adapter.upserts) == 1
    assert adapter.failure_count == 2
    assert mock_sleep.call_count == 2


@patch("time.sleep", return_value=None)
def test_sync_retry_failure_to_dlq(
    mock_sleep: MagicMock,
    insert_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    adapter.should_fail = True
    adapter.max_failures = 5  # Exceeds max_retries of 2 (3 attempts total)

    retry_config = RetryConfig(max_retries=2, initial_delay=0.1, backoff_factor=2.0)
    dlq = DeadLetterQueue()
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        retry_config=retry_config,
        dlq=dlq,
    )

    manager.sync(insert_event)
    assert len(adapter.upserts) == 0
    assert adapter.failure_count == 3  # Initial + 2 retries
    assert mock_sleep.call_count == 2

    assert dlq.size() == 1
    assert not dlq.is_empty()
    failed_event, exc = dlq.get()
    assert failed_event == insert_event
    assert isinstance(exc, ConnectionError)


def test_dlq_max_size_limit(insert_event: DebeziumEventModel) -> None:
    dlq = DeadLetterQueue(max_size=2)
    exc = ValueError("Test exception")

    dlq.put(insert_event, exc)
    dlq.put(insert_event, exc)
    assert dlq.size() == 2

    # Third put should exceed max_size, drop the event, and log a warning without raising Exception
    dlq.put(insert_event, exc)
    assert dlq.size() == 2


def test_sync_batch_compaction(
    insert_event: DebeziumEventModel,
    update_event: DebeziumEventModel,
    delete_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        soft_delete=False,
    )

    # 1. Compaction: Insert followed by Update followed by Delete on same doc_id
    # All target "public.products:1". Compacted result should be just a single Delete.
    manager.sync_batch([insert_event, update_event, delete_event])
    assert len(adapter.upserts) == 0
    assert len(adapter.deletes) == 1
    assert adapter.deletes[0] == "public.products:1"

    # Reset adapter
    adapter.deletes.clear()
    adapter.upserts.clear()

    # 2. Compaction: Insert followed by Update on same doc_id
    # Compacted result should be a single Delete (from Update's replace rule) and single Upsert of Update.
    manager.sync_batch([insert_event, update_event])
    assert len(adapter.deletes) == 1
    assert adapter.deletes[0] == "public.products:1"
    assert len(adapter.upserts) == 1
    assert adapter.upserts[0].id == "public.products:1"
    assert adapter.upserts[0].metadata["_op"] == "u"


def test_sync_batch_error_fallback(
    insert_event: DebeziumEventModel,
    snapshot_event: DebeziumEventModel,
    document_builder: DocumentBuilder,
) -> None:
    adapter = FakeVectorStoreAdapter()
    dlq = DeadLetterQueue()
    manager = SyncManager(
        document_builder=document_builder,
        vector_store_adapter=adapter,
        dlq=dlq,
    )

    # Set up failure on bulk upsert (FakeVectorStoreAdapter throws on upsert/upsert_batch if configured)
    adapter.should_fail = True
    adapter.max_failures = 10  # Exceeds standard retry threshold to force fallback

    # Run sync_batch: since bulk fail is persistent, it should fall back to sequential sync.
    # But wait, sequential sync will also fail unless we can isolate the failure.
    # Let's test that fallback to sync(event) occurs when batch fails.
    with patch.object(manager, "sync") as mock_sync:
        manager.sync_batch([insert_event, snapshot_event])
        assert mock_sync.call_count == 2
        mock_sync.assert_any_call(insert_event)
        mock_sync.assert_any_call(snapshot_event)
