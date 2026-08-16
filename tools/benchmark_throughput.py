import json
import time
from typing import Any

from langchain_core.documents import Document

from pydebeziumai.adapters.base import VectorStoreAdapter
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.sync.manager import SyncManager
from pydebeziumai.transformation.document_builder import DocumentBuilder
from pydebeziumai.transformation.id_strategy import TablePkIdStrategy
from pydebeziumai.transformation.projection_policy import ProjectionPolicy, TableProjectionPolicy


class MockVectorStoreAdapter(VectorStoreAdapter):
    """A mock vector store adapter to isolate pipeline speed from network operations."""

    def __init__(self) -> None:
        self.upsert_count = 0
        self.delete_count = 0

    def upsert(self, document: Document) -> None:
        self.upsert_count += 1

    def upsert_batch(self, documents: list[Document]) -> None:
        self.upsert_count += len(documents)

    def delete(self, document_id: str) -> None:
        self.delete_count += 1

    def delete_batch(self, document_ids: list[str]) -> None:
        self.delete_count += len(document_ids)

    def as_retriever(self, **kwargs: Any) -> Any:
        return None


class MockChangeEvent:
    """Simulates a pydbzengine ChangeEvent."""

    def __init__(self, dest: str, key: str, val: str) -> None:
        self._dest = dest
        self._key = key
        self._val = val

    def destination(self) -> str:
        return self._dest

    def key(self) -> str:
        return self._key

    def value(self) -> str:
        return self._val


def run_benchmark(num_events: int = 10000) -> None:
    print(f"Initializing throughput benchmark with {num_events:,} events...")

    # 1. Setup transformation and synchronization layers
    policy = ProjectionPolicy(
        default=TableProjectionPolicy(
            content_template="Product: $name | Category: $category | Price: $price",
            metadata_fields=["id", "category"],
        )
    )
    builder = DocumentBuilder(
        id_strategy=TablePkIdStrategy(pk_fields=["id"]),
        projection_policy=policy,
    )
    adapter = MockVectorStoreAdapter()
    sync_manager = SyncManager(vector_store_adapter=adapter, document_builder=builder)

    # 2. Generate mock events
    events = []
    for i in range(num_events):
        record_val = {
            "payload": {
                "op": "c" if i % 2 == 0 else "u",
                "before": None if i % 2 == 0 else {"id": i, "name": f"Item {i}", "category": "General", "price": 99.99},
                "after": {"id": i, "name": f"Item {i} Updated", "category": "General", "price": 109.99},
                "source": {
                    "version": "2.5.0.Final",
                    "connector": "postgresql",
                    "name": "dbserver",
                    "ts_ms": 1600000000000,
                    "db": "inventory",
                    "schema": "public",
                    "table": "products",
                },
                "ts_ms": 1600000000000,
            }
        }
        change_event = MockChangeEvent(
            dest="dbserver.public.products", key=json.dumps({"id": i}), val=json.dumps(record_val)
        )
        event = DebeziumEventModel.from_json_record(change_event)
        if event:
            events.append(event)

    print(f"Generation complete. Successfully generated {len(events):,} valid events.")
    print("Running synchronization pipeline...")

    # 3. Benchmark loop
    start_time = time.perf_counter()
    for event in events:
        sync_manager.sync(event)
    end_time = time.perf_counter()

    duration = end_time - start_time
    throughput = len(events) / duration

    print("\nBenchmark Results:")
    print("---------------------------------")
    print(f"Total Events processed : {len(events):,}")
    print(f"Total Time taken       : {duration:.4f} seconds")
    print(f"Ingestion Throughput   : {throughput:.2f} events/second")
    print(f"Total Upserts executed : {adapter.upsert_count:,}")
    print("---------------------------------")


if __name__ == "__main__":
    run_benchmark()
