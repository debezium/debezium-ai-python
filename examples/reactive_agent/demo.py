"""Automated demonstration of a reactive LangGraph agent."""

from __future__ import annotations

import os
import shutil
import sys
import time

# Add parent directory to path so we can import stream_sync and agent
sys.path.append(os.path.dirname(__file__))

import contextlib

try:
    import psycopg

    PSYCOPG_INSTALLED = True
except ImportError:
    psycopg = None  # type: ignore[assignment]
    PSYCOPG_INSTALLED = False

from agent import get_agent
from stream_sync import get_sync_manager, start_debezium_engine


def main() -> None:
    print("=" * 60)
    print("      PyDebeziumAI: Reactive LangGraph Agent Demo")
    print("=" * 60)

    persist_dir = os.path.join(os.path.dirname(__file__), "chroma_db")

    # 1. Clean up old Chroma db/offsets to start fresh
    if os.path.exists(persist_dir):
        print("Cleaning up old Chroma database directory...")
        shutil.rmtree(persist_dir)

    offset_file = os.path.join(os.path.dirname(__file__), "offsets.dat")
    if os.path.exists(offset_file):
        os.remove(offset_file)

    # 2. Debezium Properties configuration
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_password = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
    db_name = os.getenv("POSTGRES_DB", "inventory_db")

    # 3. Reset database state for prod_002 (Smart Water Bottle) to ensure demo starts in-stock
    if PSYCOPG_INSTALLED and psycopg is not None:
        try:
            with (
                psycopg.connect(
                    host=db_host,
                    port=int(db_port),
                    user=db_user,
                    password=db_password,
                    dbname=db_name,
                ) as conn,
                conn.cursor() as cur,
            ):
                cur.execute("UPDATE products SET quantity = 5 WHERE id = 'prod_002';")
                conn.commit()
        except Exception as e:
            print(f"Warning: Failed to reset database quantity: {e}")
    else:
        print("Warning: psycopg not installed, skipping database reset.")

    properties = {
        "name": "inventory-reactive-connector",
        "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
        "database.hostname": db_host,
        "database.port": db_port,
        "database.user": db_user,
        "database.password": db_password,
        "database.dbname": db_name,
        "topic.prefix": "reactiveserver",
        "plugin.name": "pgoutput",
        "table.include.list": "public.products",
        "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
        "offset.storage.file.filename": offset_file,
        "offset.flush.interval.ms": "1000",
    }

    # 3. Start Debezium Sync In Background
    print("\nStarting Debezium CDC sync engine in background...")
    engine, thread = start_debezium_engine(properties, persist_dir, background=True)

    # 4. Wait for initial database snapshot to sync to vector store
    print("\nWaiting for initial database snapshot to sync to Chroma...")
    synced = False
    for _ in range(15):
        try:
            sync_manager = get_sync_manager(persist_dir)
            retriever = sync_manager.vector_store_adapter.as_retriever(search_kwargs={"k": 5})
            results = retriever.invoke("Smart Water Bottle")
            if results:
                synced = True
                print("Snapshot successfully synced!")
                break
        except Exception:
            pass
        time.sleep(1)

    if not synced:
        print("Error: Database snapshot sync timed out.")
        engine.close()
        sys.exit(1)

    # 5. Initialize the Agent
    print("\nInitializing reactive AI support assistant agent...")
    query_agent, agent_mode = get_agent(persist_dir)
    print(f"Loaded agent in mode: {agent_mode}")

    query = "Is the Smart Water Bottle in stock, and what is its price?"

    # 6. First Query
    print("\n" + "-" * 50)
    print(f"Query 1: '{query}'")
    print("-" * 50)
    try:
        # Retrieve and print RAG context
        sync_manager = get_sync_manager(persist_dir)
        retriever = sync_manager.vector_store_adapter.as_retriever(search_kwargs={"k": 2})
        context_docs = retriever.invoke(query)
        print("--- [RAG Context Retrieved] ---")
        for idx, doc in enumerate(context_docs):
            print(f"Document {idx + 1}:\n{doc.page_content}\nMetadata: {doc.metadata}")
        print("------------------------------\n")

        response1 = query_agent(query)
        print(f"Agent Response:\n{response1}")
    except Exception as e:
        print(f"Error querying agent: {e}")
        engine.close()
        sys.exit(1)

    # 7. Execute Database Update: Set Quantity to 0 (Smart Water Bottle sells out)
    print("\n" + "=" * 50)
    print("[Database Event] Modifying 'Smart Water Bottle' quantity to 0 (Out of Stock)...")
    print("=" * 50)
    if not PSYCOPG_INSTALLED or psycopg is None:
        print(
            "Error: psycopg is not installed. Please run `pip install 'pydebeziumai[pgvector]'` to run this pgvector demo."
        )
        engine.close()
        sys.exit(1)

    try:
        with (
            psycopg.connect(
                host=db_host,
                port=int(db_port),
                user=db_user,
                password=db_password,
                dbname=db_name,
            ) as conn,
            conn.cursor() as cur,
        ):
            cur.execute("UPDATE products SET quantity = 0 WHERE id = 'prod_002';")
            conn.commit()
        print("SQL UPDATE executed successfully.")
    except Exception as e:
        print(f"Failed to update database: {e}")
        engine.close()
        sys.exit(1)

    # 8. Wait for CDC propagation
    print("Waiting 3 seconds for CDC WAL capture and vector store synchronization...")
    time.sleep(3)

    # 9. Second Query (Ask the same question again)
    print("\n" + "-" * 50)
    print(f"Query 2: '{query}'")
    print("-" * 50)
    try:
        # Retrieve and print RAG context
        sync_manager = get_sync_manager(persist_dir)
        retriever = sync_manager.vector_store_adapter.as_retriever(search_kwargs={"k": 2})
        context_docs = retriever.invoke(query)
        print("--- [RAG Context Retrieved] ---")
        for idx, doc in enumerate(context_docs):
            print(f"Document {idx + 1}:\n{doc.page_content}\nMetadata: {doc.metadata}")
        print("------------------------------\n")

        response2 = query_agent(query)
        print(f"Agent Response:\n{response2}")
    except Exception as e:
        print(f"Error querying agent: {e}")
        engine.close()
        sys.exit(1)

    # 10. Tear down and close Debezium cleanly
    print("\nClosing Debezium CDC sync engine...")
    with contextlib.suppress(Exception):
        engine.close()
    print("\nDemo completed successfully!")


if __name__ == "__main__":
    main()
