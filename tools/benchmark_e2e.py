"""End-to-end CDC benchmark: real Postgres -> real Debezium embedded engine -> real
SyncManager -> real vector store adapter.

Scope, and how this differs from the other two benchmark tools in this directory:

  tools/benchmark.py            Vector-store-only. Times ChromaAdapter.upsert()
                                 directly. Does not exercise ingestion, SyncManager,
                                 or DocumentBuilder at all.

  tools/benchmark_throughput.py Pipeline-only. Times SyncManager + DocumentBuilder
                                 against a no-op MockVectorStoreAdapter, explicitly
                                 to isolate pipeline code from network/JVM overhead.
                                 Reports very high numbers (tens of thousands of
                                 events/sec) because it excludes the two most
                                 expensive real-world costs: the Debezium JVM engine
                                 and actual vector-store I/O.

  tools/benchmark_e2e.py (this) Full path. Times wall-clock from "row committed in
                                 Postgres" to "document upserted into the vector
                                 store", through the real Debezium embedded engine
                                 (JVM, via pydbzengine) and a real adapter. This is
                                 the number that corresponds to a deployed system's
                                 actual latency and throughput -- use this one when
                                 evaluating whether the library meets a real
                                 throughput/latency target, not the other two.

Requirements:
  - A reachable Postgres instance with `wal_level=logical` already set, and a user
    with REPLICATION privileges. This script creates/reuses a single benchmark
    table, a replication slot, and a publication; use --cleanup (default: on) to
    drop them after the run so repeated runs start from a clean state.
  - `pip install pydebeziumai[debezium,chroma]` (or swap the adapter construction
    below for pgvector/milvus).

This uses langchain_core's fake in-memory embeddings by default (real embedding
cost is close to zero and not representative of a real provider). Pass
--real-embeddings to use a local sentence-transformers model instead, if installed,
for a more realistic number -- embedding cost is frequently the dominant factor in
production and is easy to underestimate by benchmarking with fakes only.
"""

from __future__ import annotations

import argparse
import statistics
import sys
import threading
import time

from langchain_core.embeddings import Embeddings

try:
    import psycopg
except ImportError:
    print(
        "ERROR: psycopg is required for this benchmark. Install it with:\n  pip install 'psycopg[binary]'",
        file=sys.stderr,
    )
    raise

try:
    from pydebeziumai.ingestion.json_handler import JsonIngestionHandler
except ImportError:
    print(
        "ERROR: pydbzengine is required for this benchmark (it runs the real\n"
        "Debezium embedded engine). Install it with:\n"
        "  pip install pydebeziumai[debezium]\n"
        "A JVM (Java 11+) must also be available on PATH.",
        file=sys.stderr,
    )
    raise

from pydebeziumai.adapters.chroma import ChromaAdapter
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.sync.manager import SyncManager
from pydebeziumai.transformation.document_builder import DocumentBuilder
from pydebeziumai.transformation.id_strategy import TablePkIdStrategy
from pydebeziumai.transformation.projection_policy import ProjectionPolicy, TableProjectionPolicy


def build_embeddings(real: bool) -> Embeddings:
    if not real:

        class FakeEmbeddings(Embeddings):
            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [[0.1] * 384 for _ in texts]

            def embed_query(self, text: str) -> list[float]:
                return [0.1] * 384

        return FakeEmbeddings()

    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        print(
            "ERROR: --real-embeddings requires langchain-huggingface + "
            "sentence-transformers.\n  pip install pydebeziumai[local-embeddings]",
            file=sys.stderr,
        )
        raise
    return HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2")


def clear_stale_offsets(offset_file: str) -> None:
    """Remove any leftover offset-storage file from a previous run.

    Without this, a fresh replication slot (created because the previous run's
    slot was dropped during cleanup, or because this is the very first run after
    an unclean shutdown) combined with a stale offset file pointing at an LSN that
    no longer exists causes the connector to fail outright on startup with
    "Last recorded offset is no longer available on the server" -- and since that
    happens before any events are produced, the run just hangs until
    --timeout-seconds expires with zero events matched.
    """
    import contextlib
    import os

    with contextlib.suppress(FileNotFoundError):
        os.remove(offset_file)


def setup_table(dsn: str, table: str, num_records: int) -> None:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute(f"DROP TABLE IF EXISTS {table};")
        cur.execute(
            f"""
            CREATE TABLE {table} (
                id serial PRIMARY KEY,
                name text,
                category text,
                price numeric
            );
            """
        )
        cur.execute(f"ALTER TABLE {table} REPLICA IDENTITY FULL;")


def cleanup(dsn: str, table: str, slot_name: str, publication_name: str) -> None:
    try:
        with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute(f"DROP TABLE IF EXISTS {table};")
            cur.execute(
                "SELECT pg_drop_replication_slot(slot_name) FROM pg_replication_slots WHERE slot_name = %s;",
                (slot_name,),
            )
            cur.execute(f"DROP PUBLICATION IF EXISTS {publication_name};")
    except Exception as exc:  # best-effort cleanup, don't fail the run over it
        print(f"WARNING: cleanup step failed (non-fatal): {exc}", file=sys.stderr)


def run(args: argparse.Namespace) -> None:
    dsn = f"host={args.host} port={args.port} dbname={args.dbname} user={args.user} password={args.password}"
    table = args.table
    slot_name = args.slot_name
    publication_name = f"{slot_name}_pub"

    print("=" * 65)
    print("PyDebeziumAI END-TO-END BENCHMARK (real Postgres + real Debezium)")
    print("=" * 65)
    print(f"Records          : {args.num_records}")
    print(f"Embeddings       : {'real (sentence-transformers)' if args.real_embeddings else 'fake (in-memory)'}")
    print(f"poll.interval.ms : {args.poll_interval_ms}")
    print("Target           : p95 < 2000ms, throughput >= 150 events/sec\n")

    offset_file = f"/tmp/{slot_name}_offsets.dat"
    print("Setting up benchmark table...")
    setup_table(dsn, table, args.num_records)
    clear_stale_offsets(offset_file)

    embeddings = build_embeddings(args.real_embeddings)
    adapter = ChromaAdapter(collection_name="benchmark_e2e", embeddings=embeddings)
    builder = DocumentBuilder(
        id_strategy=TablePkIdStrategy(pk_fields=["id"]),
        projection_policy=ProjectionPolicy(
            default=TableProjectionPolicy(
                content_template="Product: $name | Category: $category | Price: $price",
                metadata_fields=["id", "category", "price"],
            )
        ),
    )
    sync_manager = SyncManager(document_builder=builder, vector_store_adapter=adapter)

    insert_times: dict[int, float] = {}
    sync_times: dict[int, float] = {}
    done_event = threading.Event()
    lock = threading.Lock()

    def on_event(event: DebeziumEventModel) -> None:
        row = event.payload.after or event.payload.before or {}
        row_id = row.get("id")
        sync_manager.sync(event)
        with lock:
            if row_id is not None:
                sync_times[row_id] = time.time()
                if len(sync_times) >= args.num_records:
                    done_event.set()

    def on_error(exc: BaseException, record: object) -> None:
        print(f"[ingestion error] {exc}", file=sys.stderr)

    handler = JsonIngestionHandler()
    handler.add_event_callback(on_event)
    handler.add_error_callback(on_error)

    props = {
        "name": f"{slot_name}-connector",
        "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
        "database.hostname": args.host,
        "database.port": str(args.port),
        "database.user": args.user,
        "database.password": args.password,
        "database.dbname": args.dbname,
        "topic.prefix": slot_name,
        "table.include.list": f"public.{table}",
        "plugin.name": "pgoutput",
        "slot.name": slot_name,
        "publication.name": publication_name,
        "snapshot.mode": "no_data",
        "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
        "offset.storage.file.filename": offset_file,
        "offset.flush.interval.ms": "500",
        "poll.interval.ms": str(args.poll_interval_ms),
    }

    engine = handler.build_engine(props)
    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()

    print(f"Waiting {args.warmup_seconds}s for the engine to establish its replication slot...")
    time.sleep(args.warmup_seconds)

    print(f"Inserting {args.num_records} rows...")
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        for i in range(args.num_records):
            t0 = time.time()
            cur.execute(
                f"INSERT INTO {table} (name, category, price) VALUES (%s, %s, %s) RETURNING id",
                (f"Item-{i}", f"Category-{i % 5}", 10.0 + i),
            )
            fetched = cur.fetchone()
            assert fetched is not None, "INSERT ... RETURNING id did not return a row"
            row_id = fetched[0]
            insert_times[row_id] = t0

    print("Inserts committed. Waiting for CDC events to flow through...")
    done_event.wait(timeout=args.timeout_seconds)
    time.sleep(1)

    try:
        engine.close()
        engine_thread.join(timeout=5)
    except Exception:
        pass

    matched = set(insert_times) & set(sync_times)
    print(f"\nMatched {len(matched)}/{args.num_records} events end-to-end.")

    if args.cleanup:
        print("Cleaning up (table, replication slot, publication)...")
        cleanup(dsn, table, slot_name, publication_name)

    if not matched:
        print("No events matched -- pipeline did not deliver events within the timeout window.")
        sys.exit(1)

    latencies_ms = sorted((sync_times[i] - insert_times[i]) * 1000 for i in matched)
    p50 = statistics.median(latencies_ms)
    p95 = latencies_ms[int(len(latencies_ms) * 0.95) - 1] if len(latencies_ms) > 1 else latencies_ms[0]
    p99 = latencies_ms[int(len(latencies_ms) * 0.99) - 1] if len(latencies_ms) > 1 else latencies_ms[0]
    span = max(sync_times[i] for i in matched) - min(insert_times[i] for i in matched)
    throughput = len(matched) / span if span > 0 else float("inf")

    print("\n--- Results (Postgres commit -> vector store upsert) ---")
    print(f"p50 latency : {p50:.1f} ms")
    print(f"p95 latency : {p95:.1f} ms")
    print(f"p99 latency : {p99:.1f} ms")
    print(f"max latency : {max(latencies_ms):.1f} ms")
    print(f"min latency : {min(latencies_ms):.1f} ms")
    print(f"throughput  : {throughput:.2f} events/sec (over full capture window)")
    print("-" * 65)
    print(f"p95 {'PASSES' if p95 < 2000 else 'FAILS'} the <2s target")
    print(f"throughput {'PASSES' if throughput >= 150 else 'FAILS'} the >=150/sec target")

    # The embedded JVM (via JPype) can leave background threads/pools that don't
    # release control back to Python on their own even after engine.close(). Force
    # a clean exit here rather than letting the interpreter hang after results are
    # already printed.
    sys.stdout.flush()
    import os

    os._exit(0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--dbname", default="benchdb")
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--password", default="postgres")
    parser.add_argument("--table", default="benchmark_products")
    parser.add_argument("--slot-name", default="pydebeziumai_bench_slot")
    parser.add_argument("--num-records", type=int, default=200)
    parser.add_argument(
        "--poll-interval-ms",
        type=int,
        default=500,
        help="Debezium poll.interval.ms (default matches Debezium's own default)",
    )
    parser.add_argument(
        "--warmup-seconds",
        type=int,
        default=8,
        help="Time to let the engine establish its replication slot before inserting",
    )
    parser.add_argument("--timeout-seconds", type=int, default=90, help="Max time to wait for all events to arrive")
    parser.add_argument(
        "--real-embeddings",
        action="store_true",
        help="Use a local sentence-transformers model instead of fake embeddings",
    )
    parser.add_argument(
        "--no-cleanup",
        dest="cleanup",
        action="store_false",
        help="Skip dropping the table/slot/publication after the run",
    )
    args = parser.parse_args()
    run(args)


if __name__ == "__main__":
    main()
