"""Background daemon that syncs PostgreSQL changes to Chroma DB in real-time."""

from __future__ import annotations

import logging
import os
import sys
import threading
from typing import Any

from langchain_core.embeddings import Embeddings, FakeEmbeddings

from pydebeziumai.adapters.chroma import ChromaAdapter
from pydebeziumai.ingestion.json_handler import JsonIngestionHandler
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.sync.manager import SyncManager
from pydebeziumai.transformation.document_builder import DocumentBuilder
from pydebeziumai.transformation.id_strategy import TablePkIdStrategy
from pydebeziumai.transformation.projection_policy import ProjectionPolicy, TableProjectionPolicy

# Configure Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("stream_sync")


def get_sync_manager(persist_dir: str) -> SyncManager:
    # 1. Initialize Embeddings
    embeddings: Embeddings
    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        logger.info("Initializing HuggingFaceEmbeddings (all-MiniLM-L6-v2)...")
        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    except ImportError:
        logger.warning("langchain-huggingface not installed. Falling back to FakeEmbeddings.")
        embeddings = FakeEmbeddings(size=384)

    # 2. Configure Chroma Adapter
    logger.info(f"Configuring ChromaAdapter with persistent directory: {persist_dir}")
    adapter = ChromaAdapter(
        collection_name="reactive_catalog",
        embeddings=embeddings,
        persist_directory=persist_dir,
    )

    # 3. Setup Transformation Layer
    policy = ProjectionPolicy(
        default=TableProjectionPolicy(
            content_template="Product: $name\nCategory: $category\nPrice: $$$price\nQuantity: $quantity",
            metadata_fields=["id", "price", "category", "quantity"],
        )
    )
    builder = DocumentBuilder(
        id_strategy=TablePkIdStrategy(pk_fields=["id"]),
        projection_policy=policy,
    )

    # 4. Setup SyncManager
    return SyncManager(
        vector_store_adapter=adapter,
        document_builder=builder,
    )


def start_debezium_engine(properties: dict[str, str], persist_dir: str, background: bool = False) -> Any:
    sync_manager = get_sync_manager(persist_dir)

    def handle_and_log(event: DebeziumEventModel) -> None:
        logger.info(f"Received CDC event: op={event.payload.op}, table={event.table_name}, key={event.key}")
        sync_manager.sync(event)

    handler = JsonIngestionHandler()
    handler.add_event_callback(handle_and_log)

    try:
        engine = handler.build_engine(properties)
    except Exception as e:
        logger.error(
            f"Failed to build Debezium Engine: {e}. "
            "Make sure you ran 'python tools/setup_jars.py' to download Debezium JARs first."
        )
        sys.exit(1)

    if background:
        logger.info("Starting Embedded Debezium in background thread...")
        thread = threading.Thread(target=engine.run, daemon=True)
        thread.start()
        return engine, thread
    else:
        logger.info("Starting Embedded Debezium logical replication loop. Press Ctrl+C to stop.")
        try:
            engine.run()
        except KeyboardInterrupt:
            logger.info("Shutting down Debezium engine gracefully...")
        except Exception as e:
            logger.error(f"Unexpected error in replication loop: {e}")
            sys.exit(1)
        return None, None


def main() -> None:
    persist_dir = os.path.join(os.path.dirname(__file__), "chroma_db")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")
    db_user = os.getenv("POSTGRES_USER", "postgres")
    db_password = os.getenv("POSTGRES_PASSWORD", "postgrespassword")
    db_name = os.getenv("POSTGRES_DB", "inventory_db")

    properties = {
        "name": "inventory-sync-connector",
        "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
        "database.hostname": db_host,
        "database.port": db_port,
        "database.user": db_user,
        "database.password": db_password,
        "database.dbname": db_name,
        "topic.prefix": "myserver",
        "plugin.name": "pgoutput",
        "table.include.list": "public.products",
        "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
        "offset.storage.file.filename": os.path.join(os.path.dirname(__file__), "offsets.dat"),
        "offset.flush.interval.ms": "5000",
    }

    start_debezium_engine(properties, persist_dir, background=False)


if __name__ == "__main__":
    main()
