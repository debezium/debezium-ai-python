# Reactive LangGraph Agent Example

This directory contains a complete, functional demonstration of a **Reactive LangGraph Agent** that uses Change Data Capture (CDC) to keep its contextual knowledge synchronized in real-time as the primary database updates.

Unlike static RAG systems, the agent here reacts instantly when catalog items are purchased, sold out, or changed, ensuring LLM decisions are based on the latest physical catalog state.

---

## 🛠️ Requirements

- **Docker**: For running PostgreSQL.
- **Python Dependencies**:
  - `psycopg` (installed via `pyproject.toml` extra `pgvector` or developer environment)
  - `langchain` and related ecosystem libraries (or `FakeEmbeddings` fallback automatically handled)

---

## 🚀 How to Run

### 1. Download Debezium Jars
Before running the sync pipeline, ensure you have downloaded the required Debezium embedded database jars:
```bash
python3 tools/setup_jars.py
```

### 2. Start PostgreSQL logical replication container
Spin up the pre-configured Postgres container containing the initial seed database:
```bash
docker compose -f examples/reactive_agent/docker-compose.yml up -d
```

### 3. Run the automated demo
The automated demo script will boot Debezium in a background thread, monitor the sync state, ask the agent a question, execute a DB update setting stock quantity to 0, wait for propagation, and ask the agent the same question again:
```bash
python3 examples/reactive_agent/demo.py
```

### 4. Clean up
After the demo runs, shut down and clean up the database containers:
```bash
docker compose -f examples/reactive_agent/docker-compose.yml down -v
```

---

## 🔍 How it Works

1. **CDC Event Propagation**: When the database is updated (via `UPDATE products SET quantity = 0`), Debezium captures the WAL log record and converts it to a standard event format.
2. **Idempotent Ingestion**: `SyncManager` consumes the event, deletes the outdated vector representation, and writes a fresh document containing the new status `Quantity: 0`.
3. **Agent Reactivity**: The agent invokes its `query_inventory` retriever tool to look up details. When it accesses the latest vector representation, it reads the updated quantity, preventing it from offering out-of-stock products to the user.
