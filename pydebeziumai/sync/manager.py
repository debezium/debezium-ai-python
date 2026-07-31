"""Synchronization manager coordinating event propagation to vector store adapters."""

from __future__ import annotations

import logging
import queue
import random
import time
from collections.abc import Callable
from typing import Any

from langchain_core.documents import Document

from pydebeziumai.adapters.base import VectorStoreAdapter
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.transformation.document_builder import DocumentBuilder

logger = logging.getLogger(__name__)
_PERMANENT_ERRORS = (ValueError, TypeError, KeyError, AttributeError, NameError, ImportError)


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
            logger.info(
                "Event key=%s routed to Dead Letter Queue (current_size=%d) due to error: %s",
                event.key,
                self.size(),
                exception,
            )
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
        max_workers: int | None = None,
    ) -> None:
        """Initialises the SyncManager.

        Args:
            document_builder: Builder to map Debezium events to LangChain Documents.
            vector_store_adapter: Destination vector store backend.
            soft_delete: If True, delete operations update metadata with _is_deleted=True
                         instead of hard-deleting the document.
            retry_config: Settings for transient error retries.
            dlq: Optional DeadLetterQueue to capture failed events.
            max_workers: Maximum number of worker threads for parallel document building.
        """
        self.document_builder = document_builder
        self.vector_store_adapter = vector_store_adapter
        self.soft_delete = soft_delete
        self.retry_config = retry_config or RetryConfig()
        self.dlq = dlq or DeadLetterQueue()
        self._max_workers = max_workers

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

    def _sync_with_retry_wrapper(self, func: Callable[..., Any], description: str, *args: Any, **kwargs: Any) -> None:
        retries = 0
        while True:
            try:
                func(*args, **kwargs)
                return
            except _PERMANENT_ERRORS as exc:
                logger.error("Permanent error encountered during %s: %s. Bypassing retries.", description, exc)
                raise exc
            except Exception as exc:
                retries += 1
                if retries > self.retry_config.max_retries:
                    raise exc

                delay = self.retry_config.initial_delay * (self.retry_config.backoff_factor ** (retries - 1))
                if self.retry_config.jitter:
                    delay *= random.uniform(0.5, 1.5)

                logger.warning(
                    "%s attempt %d failed: %s. Retrying in %.2fs...",
                    description.capitalize(),
                    retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

    def _sync_with_retry(self, event: DebeziumEventModel) -> None:
        """Attempt to synchronize an event using the retry policy.

        Args:
            event: The DebeziumEventModel to synchronize.
        """
        self._sync_with_retry_wrapper(self._execute_sync, f"sync for event key={event.key}", event)

    def _execute_sync(self, event: DebeziumEventModel) -> None:
        """Perform the synchronization operation based on CDC operation type.

        Args:
            event: The DebeziumEventModel to synchronize.
        """
        op = event.payload.op
        if op not in ("c", "u", "d", "r"):
            logger.warning("Skipping event with unsupported operation type: %r", op)
            return

        if op in ("c", "u", "r") and event.payload.current_row is None:
            logger.warning(
                "Skipping event with empty row payload (op=%r, destination=%r)",
                op,
                event.destination,
            )
            return

        doc_id = self.document_builder.id_strategy.generate(event)

        if op in ("c", "r"):
            logger.info("Syncing insert/snapshot for doc_id=%s (destination=%s)", doc_id, event.destination)
            build_result = self.document_builder.build(event)
            if build_result.document is None:
                raise ValueError(f"DocumentBuilder built a None document for create/read event: {event}")
            self.vector_store_adapter.upsert(build_result.document)

        elif op == "u":
            logger.info("Syncing update (delete + upsert) for doc_id=%s (destination=%s)", doc_id, event.destination)
            build_result = self.document_builder.build(event)
            if build_result.document is None:
                raise ValueError(f"DocumentBuilder built a None document for update event: {event}")

            self.vector_store_adapter.delete(doc_id)
            self.vector_store_adapter.upsert(build_result.document)

        elif op == "d":
            if self.soft_delete:
                logger.info("Syncing soft-delete (upsert) for doc_id=%s (destination=%s)", doc_id, event.destination)
                build_result = self.document_builder.build(event, allow_soft_delete=True)
                if build_result.document is None:
                    raise ValueError(f"DocumentBuilder built a None document for soft-delete event: {event}")
                self.vector_store_adapter.upsert(build_result.document)
            else:
                logger.info("Syncing hard-delete for doc_id=%s (destination=%s)", doc_id, event.destination)
                self.vector_store_adapter.delete(doc_id)
        else:
            raise ValueError(f"Unsupported operation type: {op}")
        logger.debug("Successfully synced doc_id=%s (op=%s)", doc_id, op)

    def sync_batch(self, events: list[DebeziumEventModel]) -> None:
        """Synchronise a batch of Debezium change events to the vector store.

        Compacts the batch by doc_id to only apply the final state of each record.
        If the batch synchronization fails after all retry attempts, it falls back
        to sequential synchronization to isolate and route failing events to the DLQ.
        """
        if not events:
            return

        try:
            self._sync_batch_with_retry(events)
        except Exception as exc:
            logger.warning(
                "Batch sync failed. Falling back to sequential synchronization to isolate errors: %s",
                exc,
            )
            for event in events:
                self.sync(event)

    def _sync_batch_with_retry(self, events: list[DebeziumEventModel]) -> None:
        self._sync_with_retry_wrapper(self._execute_sync_batch, "batch sync", events)

    def _execute_sync_batch(self, events: list[DebeziumEventModel]) -> None:
        # Step 1: Compact by doc_id
        doc_id_to_event = {}
        for event in events:
            try:
                op = event.payload.op
                if op not in ("c", "u", "d", "r"):
                    logger.warning("Skipping event with unsupported operation type in batch: %r", op)
                    continue

                if op in ("c", "u", "r") and event.payload.current_row is None:
                    logger.warning(
                        "Skipping event with empty row payload in batch (op=%r, destination=%r)",
                        op,
                        event.destination,
                    )
                    continue

                doc_id = self.document_builder.id_strategy.generate(event)
                doc_id_to_event[doc_id] = event
            except Exception as exc:
                logger.error("Failed to generate doc_id for event %s: %s", event.key, exc)
                self.dlq.put(event, exc)

        to_delete = []
        to_upsert_events = []
        for doc_id, event in doc_id_to_event.items():
            op = event.payload.op
            if op == "d":
                if self.soft_delete:
                    to_upsert_events.append(event)
                else:
                    to_delete.append(doc_id)
            elif op == "u":
                to_delete.append(doc_id)
                to_upsert_events.append(event)
            elif op in ("c", "r"):
                to_upsert_events.append(event)

        # Step 2: Build documents in parallel
        from concurrent.futures import ThreadPoolExecutor

        def _build_doc(evt: DebeziumEventModel) -> Document | None:
            try:
                allow_soft = self.soft_delete and evt.payload.is_delete
                build_result = self.document_builder.build(evt, allow_soft_delete=allow_soft)
                return build_result.document
            except Exception as e:
                logger.error("Failed to build document for event %s: %s", evt.key, e)
                self.dlq.put(evt, e)
                return None

        if to_upsert_events:
            with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
                documents = list(executor.map(_build_doc, to_upsert_events))
            valid_documents = [doc for doc in documents if doc is not None]
        else:
            valid_documents = []

        # Step 3: Execute vector store operations
        if to_delete:
            logger.info("Executing batch delete for %d IDs", len(to_delete))
            self.vector_store_adapter.delete_batch(to_delete)

        if valid_documents:
            logger.info("Executing batch upsert for %d documents", len(valid_documents))
            self.vector_store_adapter.upsert_batch(valid_documents)
