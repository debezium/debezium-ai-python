# Real-Time RAG Chatbot Demonstration

This example demonstrates how **PyDebeziumAI** uses Change Data Capture (CDC) to synchronize PostgreSQL database transactions directly to a Chroma vector store in real-time, allowing an AI agent built with LangGraph to immediately query the most up-to-date data.

---

## Architecture Flow

1. **Transaction**: A write operation (INSERT, UPDATE, DELETE) happens in PostgreSQL.
2. **CDC Stream**: Debezium captures the transaction from the PostgreSQL Write-Ahead Log (WAL) and publishes it as a change event.
3. **Ingestion**: PyDebeziumAI's `JsonIngestionHandler` consumes the event payload.
4. **Transformation**: `DocumentBuilder` translates the database row into a standard LangChain `Document` using custom projection templates and stable vector IDs (`table:id`).
5. **Syncing**: `SyncManager` performs idempotent vector store modifications (upsert/delete) on ChromaDB.
6. **Querying**: The LangGraph chatbot utilizes the `create_retriever_tool` to query the live vector database.

---

## Setup & Running Guide

### 1. Prerequisites

Make sure you have Docker and Python 3.10+ installed. Install the package dependencies in your Python environment:

```bash
pip install -e ".[dev]"
```

### 2. Download Debezium Embedded JARs

PyDebeziumAI's embedded engine mode requires the Debezium core and connector JAR files. Download and configure them by running:

```bash
python tools/setup_jars.py --connector postgres
```

### 3. Spin up PostgreSQL Database

Start the PostgreSQL database service using Docker Compose. The container is configured with logical replication enabled (`wal_level=logical`) and automatically seeds mock inventory data:

```bash
docker compose -f examples/rag_chatbot/docker-compose.yml up -d
```

### 4. Start the Sync Daemon

Run the background worker script that listens to PostgreSQL WAL transactions and updates the Chroma vector index in real-time:

```bash
python examples/rag_chatbot/stream_sync.py
```

### 5. Run the Chatbot

In a separate terminal window, start the interactive chatbot console. The chatbot supports three execution modes:
1. **OpenAI Mode**: Set the `OPENAI_API_KEY` environment variable to run a full LangGraph agent.
2. **Local Ollama Mode**: If you have a local Ollama instance running, the chatbot will automatically detect it, let you choose a model (e.g. `llama3.2` or `smollm:135m`), and query it natively.
3. **Mock Mode (Fallback)**: If no LLM is configured, it will simulate a model with direct retrieval outputs.

```bash
# Optional: Set OpenAI key
export OPENAI_API_KEY="your-openai-api-key"

# Optional: Run a local Ollama model (e.g. llama3.2)
# ollama run llama3.2

python examples/rag_chatbot/chatbot.py
```

> [!IMPORTANT]
> **LSN Timeline Desync**: If you recreate the PostgreSQL database container (which resets the WAL timeline), make sure to delete `examples/rag_chatbot/offsets.dat` before restarting the sync daemon to prevent Debezium from throwing an LSN desync exception.

---

## Demonstrating Real-Time RAG Synchronization & Pipeline Steps

To show you exactly how the data flows, the chatbot prints the intermediate **RAG Step** outputs (including search queries, retrieved documents, and full database metadata) directly in the console:

1. **Ask the Chatbot**: In the chatbot terminal, query a product:
   ```text
   You > What is the price of the office chair?

   [RAG Step] Searching Vector DB for: 'office chair'...
   [RAG Step] Retrieved 3 matching document(s) from Vector DB:
     --- Document 1 ---
     [Page Content]
       Product: Ergonomic Office Chair
       Category: Furniture
       Description: Breathable mesh chair with lumbar support and adjustable armrests.
       Price: $249.50
     [Metadata]
       {'_table': 'items', '_op': 'r', 'category': 'Furniture', 'id': 2, 'price': 249.50}
   --------------------------------------------------

   Agent > The price of the Ergonomic Office Chair is $249.50.
   ```

2. **Modify the Database**: In another terminal, connect to the PostgreSQL database and update the price:
   ```bash
   docker exec -it debezium-postgres psql -U postgres -d testdb -c "UPDATE items SET price = 199.00 WHERE id = 2;"
   ```

3. **Verify in the Sync logs**: The sync daemon will print a CDC event log:
   ```text
   2026-06-17 18:03:51 [INFO] stream_sync: Received CDC event: op=u, table=items, key={"id": 2}
   ```

4. **Ask the Chatbot Again**: Query the chatbot again, and watch the updated price show up instantly along with the Debezium metadata (`_op: 'u'` indicating an update event):
   ```text
   You > What is the price of the office chair?

   [RAG Step] Searching Vector DB for: 'office chair'...
   [RAG Step] Retrieved 3 matching document(s) from Vector DB:
     --- Document 1 ---
     [Page Content]
       Product: Ergonomic Office Chair
       Category: Furniture
       Description: Breathable mesh chair with lumbar support and adjustable armrests.
       Price: $199.0
     [Metadata]
       {'_table': 'items', '_op': 'u', 'category': 'Furniture', 'id': 2, 'price': 199.0}
   --------------------------------------------------

   Agent > The price of the Ergonomic Office Chair is now $199.0.
   ```

