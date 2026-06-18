"""Synchronization manager coordinating event propagation to vector store adapters."""

from __future__ import annotations

import logging
import queue
import random
import time

from pydebeziumai.adapters.base import VectorStoreAdapter
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.transformation.document_builder import DocumentBuilder

logger = logging.getLogger(__name__)


class DeadLetterQueue:
    """Thread-safe Dead Letter Queue (DLQ) to hold failed events."""

    def __init__(self, max_size: int = 1000) -> None:
        """Initialises the DeadLetterQueue.

        Args:
            max_size: Maximum number of events to hold in the queue.
                      A max_size <= 0 means infinite size.
        """
        self._queue: queue.Queue[tuple[DebeziumEventModel, Exception]] = queue.Queue(maxsize=max_size)

    def put(self, event: DebeziumEventModel, exception: Exception) -> None:
        """Add a failed event and its causing exception to the DLQ.

        If the queue is full, the event is dropped and a warning is logged.

        Args:
            event: The DebeziumEventModel that failed to sync.
            exception: The Exception raised during synchronization.
        """
        try:
            self._queue.put((event, exception), block=False)
        except queue.Full:
            logger.warning(
                "Dead Letter Queue is full (max_size=%d). Dropping failed event: %s",
                self._queue.maxsize,
                event.key,
            )

    def get(self, block: bool = True, timeout: float | None = None) -> tuple[DebeziumEventModel, Exception]:
        """Retrieve a failed event and exception from the DLQ.

        Args:
            block: Whether to block until an item is available.
            timeout: Timeout in seconds if blocking.

        Returns:
            A tuple of (DebeziumEventModel, Exception).
        """
        return self._queue.get(block=block, timeout=timeout)

    def size(self) -> int:
        """Return the number of events in the DLQ."""
        return self._queue.qsize()

    def is_empty(self) -> bool:
        """Check if the DLQ is empty."""
        return self._queue.empty()


class RetryConfig:
    """Configuration for exponential backoff retries with jitter."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_delay: float = 1.0,
        backoff_factor: float = 2.0,
        jitter: bool = True,
    ) -> None:
        """Initialises RetryConfig.

        Args:
            max_retries: Maximum number of retry attempts before failure.
            initial_delay: Baseline delay in seconds before the first retry.
            backoff_factor: Multiplier for backoff calculation.
            jitter: If True, applies random noise to delay.
        """
        self.max_retries = max_retries
        self.initial_delay = initial_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter


class SyncManager:
    """Coordinates database-to-vector synchronization.

    Converts DebeziumEventModels using a DocumentBuilder and propagates
    updates/deletes to a VectorStoreAdapter.
    """

    def __init__(
        self,
        document_builder: DocumentBuilder,
        vector_store_adapter: VectorStoreAdapter,
        soft_delete: bool = False,
        retry_config: RetryConfig | None = None,
        dlq: DeadLetterQueue | None = None,
    ) -> None:
        """Initialises the SyncManager.

        Args:
            document_builder: Builder to map Debezium events to LangChain Documents.
            vector_store_adapter: Destination vector store backend.
            soft_delete: If True, delete operations update metadata with _is_deleted=True
                         instead of hard-deleting the document.
            retry_config: Settings for transient error retries.
            dlq: Optional DeadLetterQueue to capture failed events.
        """
        self.document_builder = document_builder
        self.vector_store_adapter = vector_store_adapter
        self.soft_delete = soft_delete
        self.retry_config = retry_config or RetryConfig()
        self.dlq = dlq or DeadLetterQueue()

    def sync(self, event: DebeziumEventModel) -> None:
        """Synchronise a Debezium change event to the vector store.

        If synchronization fails after all retry attempts, the event is redirected
        to the DeadLetterQueue (DLQ).

        Args:
            event: The parsed, canonical Debezium event.
        """
        try:
            self._sync_with_retry(event)
        except Exception as exc:
            logger.error("Sync failed for event %s. Redirecting to DLQ: %s", event.key, exc)
            self.dlq.put(event, exc)

    def _sync_with_retry(self, event: DebeziumEventModel) -> None:
        """Attempt to synchronize an event using the retry policy.

        Args:
            event: The DebeziumEventModel to synchronize.
        """
        retries = 0
        while True:
            try:
                self._execute_sync(event)
                return
            except Exception as exc:
                retries += 1
                if retries > self.retry_config.max_retries:
                    raise exc

                delay = self.retry_config.initial_delay * (self.retry_config.backoff_factor ** (retries - 1))
                if self.retry_config.jitter:
                    delay *= random.uniform(0.5, 1.5)

                logger.warning("Sync attempt %d failed: %s. Retrying in %.2fs...", retries, exc, delay)
                time.sleep(delay)

    def _execute_sync(self, event: DebeziumEventModel) -> None:
        """Perform the synchronization operation based on CDC operation type.

        Args:
            event: The DebeziumEventModel to synchronize.
        """
        doc_id = self.document_builder.id_strategy.generate(event)
        op = event.payload.op

        if op in ("c", "r"):
            build_result = self.document_builder.build(event)
            if build_result.document is None:
                raise ValueError(f"DocumentBuilder built a None document for create/read event: {event}")
            self.vector_store_adapter.upsert(build_result.document)

        elif op == "u":
            build_result = self.document_builder.build(event)
            if build_result.document is None:
                raise ValueError(f"DocumentBuilder built a None document for update event: {event}")

            self.vector_store_adapter.delete(doc_id)
            self.vector_store_adapter.upsert(build_result.document)

        elif op == "d":
            if self.soft_delete:
                build_result = self.document_builder.build(event, allow_soft_delete=True)
                if build_result.document is None:
                    raise ValueError(f"DocumentBuilder built a None document for soft-delete event: {event}")
                self.vector_store_adapter.upsert(build_result.document)
            else:
                self.vector_store_adapter.delete(doc_id)
        else:
            raise ValueError(f"Unsupported operation type: {op}")
