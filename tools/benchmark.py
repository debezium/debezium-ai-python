import argparse
import time

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from pydebeziumai.adapters.chroma import ChromaAdapter


class FakeEmbeddings(Embeddings):
    """Simple fake embeddings model for benchmarking."""

    def __init__(self, size: int = 384) -> None:
        self.size = size

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # Simulate slight computational overhead of model embeddings
        time.sleep(len(texts) * 0.001)
        return [[0.1] * self.size for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1] * self.size


def run_benchmark(num_records: int, batch_size: int) -> None:
    print("=" * 60)
    print("                PyDebeziumAI BENCHMARK RUNNER")
    print("=" * 60)
    print(f"Total Records  : {num_records}")
    print(f"Batch Size     : {batch_size}")

    # Initialize Chroma In-Memory adapter
    embeddings = FakeEmbeddings()
    adapter = ChromaAdapter(
        collection_name="benchmark_collection",
        embeddings=embeddings,
    )

    # Generate synthetic documents
    docs = [
        Document(
            page_content=f"Product name: Item-{i}\nCategory: Category-{i % 5}\nPrice: {10.0 + i}",
            metadata={"id": i, "category": f"Category-{i % 5}"},
            id=f"benchmark_collection:{i}",
        )
        for i in range(num_records)
    ]

    # --- 1. Sequential Benchmark ---
    print("\n--- Running Sequential Sync Benchmark ---")
    start_time = time.time()
    latencies = []

    for doc in docs:
        op_start = time.time()
        adapter.upsert(doc)
        latencies.append(time.time() - op_start)

    seq_duration = time.time() - start_time
    seq_throughput = num_records / seq_duration
    seq_avg_latency_ms = (sum(latencies) / len(latencies)) * 1000

    print(f"Sequential Duration   : {seq_duration:.3f} seconds")
    print(f"Sequential Throughput : {seq_throughput:.2f} records/sec")
    print(f"Average Upsert Latency: {seq_avg_latency_ms:.2f} ms")

    # Clear Chroma collection for fresh batch run
    for doc in docs:
        if doc.id is not None:
            adapter.delete(doc.id)

    # --- 2. Batched Benchmark ---
    print("\n--- Running Batched Sync Benchmark ---")
    start_time = time.time()
    batch_latencies = []

    # Partition into batches
    batches = [docs[i : i + batch_size] for i in range(0, len(docs), batch_size)]

    for batch in batches:
        op_start = time.time()
        adapter.upsert_batch(batch)
        batch_latencies.append(time.time() - op_start)

    batch_duration = time.time() - start_time
    batch_throughput = num_records / batch_duration
    batch_avg_latency_ms = (sum(batch_latencies) / len(batch_latencies)) * 1000

    print(f"Batched Duration      : {batch_duration:.3f} seconds")
    print(f"Batched Throughput    : {batch_throughput:.2f} records/sec")
    print(f"Average Batch Latency : {batch_avg_latency_ms:.2f} ms")
    print("-" * 60)
    print(f"Speedup Factor        : {batch_throughput / seq_throughput:.2f}x")
    print("=" * 60)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PyDebeziumAI vector adapter benchmarks.")
    parser.add_argument("--num-records", type=int, default=100, help="Number of records to sync")
    parser.add_argument("--batch-size", type=int, default=20, help="Batch size for bulk sync")
    args = parser.parse_args()

    run_benchmark(args.num_records, args.batch_size)
