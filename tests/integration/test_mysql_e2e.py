"""End-to-End integration test for Debezium MySQL ➔ Milvus CDC replication."""

import contextlib
import os
import time
import uuid
from pathlib import Path

import pytest

try:
    import pymysql
    from pymilvus import connections

    from pydebeziumai.adapters.milvus import MilvusAdapter
except ImportError:
    pytest.skip("pymysql or pymilvus not installed, skipping MySQL CDC integration tests", allow_module_level=True)

from langchain_core.embeddings import FakeEmbeddings

from pydebeziumai.ingestion.json_handler import JsonIngestionHandler
from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.sync.manager import DeadLetterQueue, SyncManager
from pydebeziumai.transformation.document_builder import DocumentBuilder
from pydebeziumai.transformation.id_strategy import TablePkIdStrategy
from pydebeziumai.transformation.projection_policy import ProjectionPolicy, TableProjectionPolicy


@pytest.mark.integration
def test_mysql_to_milvus_cdc_e2e(tmp_path: Path) -> None:
    # 1. Verify MySQL connection
    mysql_host = os.getenv("MYSQL_HOST", "localhost")
    mysql_port = int(os.getenv("MYSQL_PORT", "3306"))
    mysql_user = os.getenv("MYSQL_USER", "debezium")
    mysql_password = os.getenv("MYSQL_PASSWORD", "dbzpassword")
    mysql_db = os.getenv("MYSQL_DB", "inventory_db")

    try:
        conn = pymysql.connect(
            host=mysql_host,
            port=mysql_port,
            user=mysql_user,
            password=mysql_password,
            database=mysql_db,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
    except Exception as e:
        pytest.skip(f"MySQL container not available on {mysql_host}:{mysql_port}: {e}")

    # 2. Setup isolated Milvus SQLite DB
    with contextlib.suppress(Exception):
        connections.disconnect("default")

    milvus_db = str(tmp_path / f"milvus_e2e_{uuid.uuid4().hex[:6]}.db")
    adapter = MilvusAdapter(
        collection_name="e2e_products",
        embeddings=FakeEmbeddings(size=384),
        connection_uri=milvus_db,
    )

    # 3. Setup SyncManager
    policy = ProjectionPolicy(
        default=TableProjectionPolicy(
            content_template="Product: $name\nCategory: $category\nDescription: $description\nPrice: $$$price\nStock: $stock_count available",
            metadata_fields=["id", "name", "price", "category", "stock_count"],
        )
    )
    builder = DocumentBuilder(
        id_strategy=TablePkIdStrategy(pk_fields=["id"]),
        projection_policy=policy,
    )
    sync_manager = SyncManager(
        vector_store_adapter=adapter,
        document_builder=builder,
        dlq=DeadLetterQueue(),
    )

    # 4. Ingest CDC events
    events_captured = []

    def on_event(event: DebeziumEventModel) -> None:
        events_captured.append(event)
        sync_manager.sync(event)

    schema_file = str(tmp_path / "schema.dat")
    offsets_file = str(tmp_path / "offsets.dat")

    properties = {
        "name": f"mysql-e2e-{uuid.uuid4().hex[:4]}",
        "connector.class": "io.debezium.connector.mysql.MySqlConnector",
        "database.hostname": mysql_host,
        "database.port": str(mysql_port),
        "database.user": mysql_user,
        "database.password": mysql_password,
        "database.server.id": str(180000 + int(time.time()) % 10000),
        "topic.prefix": f"e2e_topic_{uuid.uuid4().hex[:4]}",
        "table.include.list": "inventory_db.products",
        "snapshot.mode": "initial",
        "schema.history.internal": "io.debezium.storage.file.history.FileSchemaHistory",
        "schema.history.internal.file.filename": schema_file,
        "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
        "offset.storage.file.filename": offsets_file,
        "offset.flush.interval.ms": "1000",
    }

    handler = JsonIngestionHandler()
    handler.add_event_callback(on_event)
    engine = handler.build_engine(properties)

    import threading

    engine_thread = threading.Thread(target=engine.run, daemon=True)
    engine_thread.start()

    # Wait for snapshot
    time.sleep(5)

    # 5. Insert new product
    test_product_name = f"Wireless Mechanical Keyboard {uuid.uuid4().hex[:4]}"
    with conn.cursor() as cursor:
        cursor.execute(
            "INSERT INTO products (name, description, price, category, stock_count) "
            "VALUES (%s, 'Ultra low latency wireless keyboard', 149.99, 'Electronics', 30)",
            (test_product_name,),
        )
        assert cursor.lastrowid is not None, "Failed to retrieve lastrowid from MySQL"

    # Wait for CDC stream event
    time.sleep(4)

    # 6. Verify vector retrieval in Milvus
    retriever = adapter.as_retriever(search_kwargs={"k": 10})
    results = retriever.invoke("keyboard")

    assert len(results) > 0, "Milvus failed to retrieve documents after CDC replication"
    assert any(test_product_name in doc.page_content for doc in results), (
        f"Expected {test_product_name} in retrieved documents, got: {[d.page_content for d in results]}"
    )

    engine.close()
    conn.close()
