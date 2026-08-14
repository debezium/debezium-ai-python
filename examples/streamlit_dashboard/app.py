"""Interactive Streamlit Live Visual Dashboard for PyDebeziumAI (MySQL ➔ Milvus).

Architecture:
1. Thread-safe Background CDC Sync Engine Controller (`get_sync_engine_controller()`)
   - Manages Debezium embedded MySQL connector thread.
   - Listens for WAL/binlog mutations (snapshot 'r', insert 'c', update 'u', delete 'd').
   - Transforms records into LangChain Documents via DocumentBuilder & TablePkIdStrategy.
   - Syncs documents to Milvus-Lite vector store in real-time via MilvusAdapter.
   - Stores real-time events in an in-memory thread-safe queue (`self.events`).

2. Streamlit UI Layout:
   - Sidebar: Server status indicators & CDC engine toggle control.
   - Column 1: MySQL Mutation Console (Execute INSERT, UPDATE, DELETE SQL transactions).
   - Column 2: Live CDC Event Stream (@st.fragment(run_every="1s") auto-updating event stream).
   - Column 3: Milvus Semantic Search (Execute RAG vector similarity queries).
"""

from __future__ import annotations

import asyncio
import contextlib
import datetime
import hashlib as _hashlib
import json
import os
import socket as _socket
import threading
import time
from typing import Any

import jpype
import pymysql
import streamlit as st
from langchain_core.embeddings import Embeddings, FakeEmbeddings

from pydebeziumai.adapters.milvus import MilvusAdapter

# Ensure active asyncio loop for Milvus gRPC client
with contextlib.suppress(RuntimeError):
    asyncio.set_event_loop(asyncio.new_event_loop())

# Page Configuration
st.set_page_config(
    page_title="PyDebeziumAI - Live CDC & Vector RAG",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom High-Contrast CSS Theme
st.markdown(
    """
    <style>
    .metric-box {
        background-color: #0f172a;
        border: 1px solid #1e293b;
        border-radius: 8px;
        padding: 12px;
        color: #f8fafc;
    }
    .badge-insert {
        background-color: #059669;
        color: #ffffff;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 0.8rem;
    }
    .badge-snapshot {
        background-color: #0284c7;
        color: #ffffff;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 0.8rem;
    }
    .badge-update {
        background-color: #2563eb;
        color: #ffffff;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 0.8rem;
    }
    .badge-delete {
        background-color: #dc2626;
        color: #ffffff;
        padding: 3px 8px;
        border-radius: 4px;
        font-weight: 700;
        font-size: 0.8rem;
    }
    .product-card {
        background-color: #0f172a;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 14px;
        margin-bottom: 10px;
        color: #f8fafc !important;
    }
    .product-card div, .product-card span, .product-card strong {
        color: #f8fafc;
    }
    .subtext-gray {
        color: #94a3b8 !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
EVENT_LOG_FILE = os.getenv("EVENT_LOG_FILE", os.path.join(DASHBOARD_DIR, "cdc_events.jsonl"))
DB_FILE = os.getenv("MILVUS_DB_FILE", os.path.join(DASHBOARD_DIR, "milvus_demo.db"))
OFFSETS_FILE = os.path.join(DASHBOARD_DIR, "offsets.dat")
SCHEMA_HISTORY_FILE = os.path.join(DASHBOARD_DIR, "schema_history.dat")

# Stable server ID based on hostname (avoids changing on every hot-reload)
_STABLE_SERVER_ID = str(184000 + int(_hashlib.md5(_socket.gethostname().encode()).hexdigest(), 16) % 10000)


def _clean_debezium_state() -> None:
    """Delete stale Debezium offset and schema history files to force a clean snapshot."""
    for f in (OFFSETS_FILE, SCHEMA_HISTORY_FILE):
        try:
            if os.path.exists(f):
                os.remove(f)
        except OSError:
            pass


# Helper Functions
def get_db_connection() -> pymysql.connections.Connection:
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "debezium"),
        password=os.getenv("MYSQL_PASSWORD", "dbzpassword"),
        database=os.getenv("MYSQL_DB", "inventory_db"),
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def fetch_all_products() -> list[dict[str, Any]]:
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM products ORDER BY id DESC")
            return cursor.fetchall()
    except Exception as e:
        st.sidebar.error(f"MySQL Error: {e}")
        return []


@st.cache_resource
def get_milvus_adapter() -> MilvusAdapter:
    with contextlib.suppress(RuntimeError):
        asyncio.set_event_loop(asyncio.new_event_loop())

    embeddings: Embeddings
    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        embeddings = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    except Exception:
        embeddings = FakeEmbeddings(size=384)

    return MilvusAdapter(
        collection_name="inventory_catalog",
        embeddings=embeddings,
        connection_uri=DB_FILE,
    )


# Thread-safe Background CDC Sync Engine Controller
class EngineController:
    def __init__(self) -> None:
        self.thread: threading.Thread | None = None
        self.engine: Any = None
        self._stop_event = threading.Event()
        self.error_msg: str | None = None
        self.events: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def add_event(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(record)

    def get_events(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(reversed(self.events[-limit:]))

    def start(self, adapter: MilvusAdapter) -> None:
        if self.running:
            return

        self._stop_event.clear()

        def worker() -> None:
            try:
                with contextlib.suppress(RuntimeError):
                    asyncio.set_event_loop(asyncio.new_event_loop())

                if jpype.isJVMStarted() and not jpype.isThreadAttachedToJVM():
                    jpype.attachThreadToJVM()

                from pydebeziumai.ingestion.json_handler import JsonIngestionHandler
                from pydebeziumai.models.event import DebeziumEventModel
                from pydebeziumai.sync.manager import DeadLetterQueue, SyncManager
                from pydebeziumai.transformation.document_builder import DocumentBuilder
                from pydebeziumai.transformation.id_strategy import TablePkIdStrategy
                from pydebeziumai.transformation.projection_policy import (
                    ProjectionPolicy,
                    TableProjectionPolicy,
                )

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

                mysql_host = os.getenv("MYSQL_HOST", "localhost")
                mysql_port = os.getenv("MYSQL_PORT", "3306")
                mysql_user = os.getenv("MYSQL_USER", "debezium")
                mysql_password = os.getenv("MYSQL_PASSWORD", "dbzpassword")

                properties = {
                    "name": "mysql-inventory-connector",
                    "connector.class": "io.debezium.connector.mysql.MySqlConnector",
                    "database.hostname": mysql_host,
                    "database.port": mysql_port,
                    "database.user": mysql_user,
                    "database.password": mysql_password,
                    "database.server.id": os.getenv("DATABASE_SERVER_ID", _STABLE_SERVER_ID),
                    "topic.prefix": "inventory_server",
                    "table.include.list": "inventory_db.products",
                    "snapshot.mode": "initial",
                    "schema.history.internal": "io.debezium.storage.file.history.FileSchemaHistory",
                    "schema.history.internal.file.filename": SCHEMA_HISTORY_FILE,
                    "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
                    "offset.storage.file.filename": OFFSETS_FILE,
                    "offset.flush.interval.ms": "1000",
                }

                def on_event(event: DebeziumEventModel) -> None:
                    record = {
                        "timestamp": datetime.datetime.now().strftime("%H:%M:%S"),
                        "op": event.payload.op,
                        "table": event.table_name or "products",
                        "key": event.key,
                        "payload": event.payload.current_row or {},
                    }
                    self.add_event(record)
                    with contextlib.suppress(Exception), open(EVENT_LOG_FILE, "a", encoding="utf-8") as f:
                        f.write(json.dumps(record) + "\n")
                        f.flush()
                    sync_manager.sync(event)

                handler = JsonIngestionHandler()
                handler.add_event_callback(on_event)
                self.engine = handler.build_engine(properties)
                self.error_msg = None
                try:
                    self.engine.run()
                except Exception as engine_err:
                    err_str = str(engine_err)
                    if "history" in err_str.lower() or "missing" in err_str.lower() or "DebeziumException" in err_str:
                        _clean_debezium_state()
                        handler2 = JsonIngestionHandler()
                        handler2.add_event_callback(on_event)
                        self.engine = handler2.build_engine(properties)
                        self.engine.run()
                    else:
                        raise
            except Exception as e:
                self.error_msg = str(e)
            finally:
                self.engine = None

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self.engine:
            with contextlib.suppress(Exception):
                self.engine.close()


@st.cache_resource
def get_sync_engine_controller() -> EngineController:
    return EngineController()


# Auto-Start Engine
controller = get_sync_engine_controller()
if not controller.running:
    with contextlib.suppress(Exception):
        adapter = get_milvus_adapter()
        controller.start(adapter)


# Sidebar Configuration
st.sidebar.title("⚡ PyDebeziumAI")
st.sidebar.caption("Real-Time MySQL ➔ Milvus CDC Pipeline")

st.sidebar.markdown("---")
st.sidebar.subheader("Replication Engine")

if controller.running:
    st.sidebar.success("🟢 CDC Engine Active & Streaming")
    if st.sidebar.button("⏹️ Stop Sync", use_container_width=True):
        controller.stop()
        st.sidebar.info("Stopped CDC replication.")
else:
    if st.sidebar.button("▶️ Start Live CDC Sync", type="primary", use_container_width=True):
        adapter = get_milvus_adapter()
        controller.start(adapter)
        st.sidebar.success("Started CDC replication thread!")

if controller.error_msg:
    st.sidebar.error(f"Replication error: {controller.error_msg}")

st.sidebar.markdown("---")
st.sidebar.subheader("Environment Status")
mysql_connected = False
try:
    conn = get_db_connection()
    conn.close()
    st.sidebar.success("🟢 MySQL 8.0 Connected (Port 3306)")
    mysql_connected = True
except Exception:
    st.sidebar.error("🔴 MySQL Not Reachable")

if os.path.exists(DB_FILE):
    st.sidebar.success("🟢 Milvus-Lite Vector DB Active")
else:
    st.sidebar.warning("🟡 Milvus Index Pending Initial Sync")

st.sidebar.markdown("---")
st.sidebar.info(
    "**How CDC Sync Works:**\n"
    "1. **Snapshot Mode (r)**: Captures initial rows from MySQL on boot.\n"
    "2. **Binlog Streaming (c, u, d)**: Streams INSERTs, UPDATEs, and DELETEs in real-time.\n"
    "3. **Milvus Sync**: Upserts and removes vector embeddings with zero-lag."
)

# Header Section
st.title("⚡ PyDebeziumAI: Live CDC & Vector RAG Dashboard")
st.caption("Demonstrating zero-lag database replication into vector storage for real-time AI context.")

# Metrics Section
products = fetch_all_products()
live_events = controller.get_events(limit=50)

col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Products (MySQL)", len(products))
with col2:
    st.metric("CDC Events Processed", len(live_events))
with col3:
    st.metric("Source Connector", "Debezium MySQL")
with col4:
    st.metric("Vector Store", "Milvus Lite")

st.markdown("---")

# Main Content Layout
col_left, col_mid, col_right = st.columns([1.1, 1.1, 1.2])

# Column 1: Mutation Console
with col_left:
    st.subheader("🛠️ MySQL Mutation Console")
    st.caption("Execute transactions directly on the source database.")

    action = st.radio("Choose Action:", ["➕ Insert Product", "✏️ Update Product", "🗑️ Delete Product"], horizontal=True)

    if action == "➕ Insert Product":
        with st.form("insert_form", clear_on_submit=True):
            name = st.text_input("Product Name", placeholder="e.g. Ultra Gaming Monitor")
            category = st.selectbox("Category", ["Electronics", "Furniture", "Fitness", "Outdoor", "Office", "Home"])
            description = st.text_area("Description", placeholder="Enter semantic product features...")
            price = st.number_input("Price ($)", min_value=1.0, value=99.99, step=5.0)
            stock = st.number_input("Stock Count", min_value=1, value=20, step=1)
            submitted = st.form_submit_button("Execute Insert (SQL)")

            if submitted:
                if not name.strip():
                    st.error("Product name cannot be empty.")
                else:
                    try:
                        conn = get_db_connection()
                        with conn.cursor() as cursor:
                            sql = "INSERT INTO products (name, description, price, category, stock_count) VALUES (%s, %s, %s, %s, %s)"
                            cursor.execute(sql, (name, description, price, category, stock))
                        st.success(f"Inserted '{name}' into MySQL! CDC event emitted.")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Insert failed: {e}")

    elif action == "✏️ Update Product":
        if not products:
            st.info("No products found in MySQL to update.")
        else:
            product_options = {f"#{p['id']} - {p['name']} (${p['price']})": p for p in products}
            selected_label = st.selectbox("Select Product to Update", list(product_options.keys()))
            selected_product = product_options[selected_label]

            with st.form("update_form"):
                new_price = st.number_input("Updated Price ($)", value=float(selected_product["price"]), step=5.0)
                new_desc = st.text_area("Updated Description", value=selected_product["description"])
                new_stock = st.number_input("Updated Stock Count", value=int(selected_product["stock_count"]), step=1)
                update_submitted = st.form_submit_button("Execute Update (SQL)")

                if update_submitted:
                    try:
                        conn = get_db_connection()
                        with conn.cursor() as cursor:
                            sql = "UPDATE products SET price = %s, description = %s, stock_count = %s WHERE id = %s"
                            cursor.execute(sql, (new_price, new_desc, new_stock, selected_product["id"]))
                        st.success(f"Updated product #{selected_product['id']}! CDC event emitted.")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Update failed: {e}")

    elif action == "🗑️ Delete Product":
        if not products:
            st.info("No products found in MySQL to delete.")
        else:
            product_options = {f"#{p['id']} - {p['name']} (${p['price']})": p for p in products}
            selected_label = st.selectbox("Select Product to Delete", list(product_options.keys()))
            selected_product = product_options[selected_label]

            with st.form("delete_form"):
                st.warning(
                    f"Are you sure you want to delete **{selected_product['name']}** (ID: {selected_product['id']})?"
                )
                delete_submitted = st.form_submit_button("Execute Delete (SQL)")

                if delete_submitted:
                    try:
                        conn = get_db_connection()
                        with conn.cursor() as cursor:
                            sql = "DELETE FROM products WHERE id = %s"
                            cursor.execute(sql, (selected_product["id"],))
                        st.success(f"Deleted product #{selected_product['id']}! CDC delete event emitted.")
                        time.sleep(0.3)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Delete failed: {e}")


# Column 2: CDC Event Stream Fragment
@st.fragment(run_every="1s")
def render_live_cdc_feed() -> None:
    st.subheader("📡 Live CDC Event Stream")
    st.caption("Real-time WAL change capture events emitted by Debezium (auto-updating).")

    events = controller.get_events(limit=50)
    if not events:
        st.info("Waiting for CDC events. Ensure Debezium engine is active in the sidebar.")
    else:
        for evt in events:
            op = evt.get("op", "")
            if op == "c":
                badge = "<span class='badge-insert'>INSERT (c)</span>"
            elif op == "r":
                badge = "<span class='badge-snapshot'>SNAPSHOT (r)</span>"
            elif op == "u":
                badge = "<span class='badge-update'>UPDATE (u)</span>"
            elif op == "d":
                badge = "<span class='badge-delete'>DELETE (d)</span>"
            else:
                badge = f"<span class='badge-update'>{op}</span>"

            payload = evt.get("payload", {})
            name = payload.get("name", "Item ID #" + str(evt.get("key", "")))
            price = payload.get("price", "N/A")
            cat = payload.get("category", "Inventory")
            ts = evt.get("timestamp", "")

            st.markdown(
                f"""
                <div class="product-card">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                        <div>{badge}</div>
                        <span class="subtext-gray" style="font-size: 0.8rem;">{ts}</span>
                    </div>
                    <div style="font-size: 1.0rem; font-weight: 600; color: #f8fafc; margin-top: 4px;">{name}</div>
                    <div class="subtext-gray" style="font-size: 0.85rem; margin-top: 4px;">Category: {cat} | Price: ${price}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )


with col_mid:
    render_live_cdc_feed()


# Column 3: Milvus Semantic Search
with col_right:
    st.subheader("🔍 Milvus Semantic Search")
    st.caption("Query the real-time vector collection to verify immediate context freshness.")

    search_query = st.text_input(
        "Semantic Search Query",
        placeholder="e.g. comfortable seating for home office, 4k television...",
    )
    top_k = st.slider("Number of Results (k)", min_value=1, max_value=5, value=3)

    if search_query:
        try:
            adapter = get_milvus_adapter()
            retriever = adapter.as_retriever(search_kwargs={"k": top_k})
            docs = retriever.invoke(search_query)

            if not docs:
                st.info("No matching documents found in the vector index.")
            else:
                st.markdown(f"**Retrieved {len(docs)} matching documents:**")
                for i, doc in enumerate(docs, 1):
                    doc_id = doc.metadata.get("id", "N/A")
                    category = doc.metadata.get("category", "General")

                    st.markdown(
                        f"""
                        <div class="product-card">
                            <div style="display: flex; justify-content: space-between; margin-bottom: 6px;">
                                <strong style="color: #38bdf8;">Result #{i} (ID: {doc_id})</strong>
                                <span style="background-color: #334155; color: #f8fafc; padding: 2px 8px; border-radius: 4px; font-size: 0.8rem; font-weight: 600;">{category}</span>
                            </div>
                            <div style="white-space: pre-wrap; font-size: 0.9rem; margin-top: 6px; color: #f8fafc;">{doc.page_content}</div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )
        except Exception as e:
            st.error(f"Vector search error: {e}")
    else:
        st.info("💡 Type a query above (e.g. 'ergonomic chair' or 'screen') to search the live vector index.")
