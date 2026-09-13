# PyDebeziumAI

> Real-time CDC Integration for LangChain & LangGraph using Debezium

[![CI](https://github.com/debezium/debezium-ai-python/actions/workflows/ci.yml/badge.svg)](https://github.com/debezium/debezium-ai-python/actions)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE.txt)

PyDebeziumAI bridges **Debezium CDC streams** with **LangChain** and **LangGraph**, keeping your vector store automatically in sync with relational database changes — in real time.

## Environment & Prerequisites

PyDebeziumAI requires Java 17+ for running the embedded Debezium JVM engine. Set your `JAVA_HOME` environment variable for your operating system:

```bash
# Linux
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

# macOS
export JAVA_HOME=$(/usr/libexec/java_home -v17)

# Windows (PowerShell / Command Prompt)
set JAVA_HOME=C:\Program Files\Java\jdk-17
```

Download Debezium engine dependencies using the cross-platform setup script:

```bash
python tools/setup_jars.py
```

## Why PyDebeziumAI?

Most RAG pipelines go stale because they rely on periodic batch reloads. PyDebeziumAI uses Debezium's Change Data Capture to push every `INSERT`, `UPDATE`, and `DELETE` into your vector store the moment it happens.

```
PostgreSQL ──► Debezium CDC ──► PyDebeziumAI ──► Chroma / PGVector / Milvus ──► LangChain RAG
```

## Quick Start

```bash
# Install with Chroma + local sentence-transformers embeddings
pip install 'pydebeziumai[chroma,local-embeddings,debezium]'
```

```python
from pydebeziumai import LiveContext

rag = LiveContext(
    debezium_config={
        "name": "my-pg-connector",
        "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
        "database.hostname": "localhost",
        "database.port": "5432",
        "database.user": "postgres",
        "database.password": "postgrespassword",
        "database.dbname": "mydb",
        "database.server.name": "myserver",
        "topic.prefix": "myserver",
        "table.include.list": "public.products",
        "plugin.name": "pgoutput",
        "snapshot.mode": "initial",
    },
    vector_store="chroma",
    embedding_model="local",  # uses sentence-transformers, no API key needed
    id_strategy="table_pk",
)

# Start real-time sync in the background
rag.start()
retriever = rag.as_retriever(search_kwargs={"k": 5})

# Use it in any LangChain chain
docs = retriever.invoke("What products are available under $50?")
```



### Offset Checkpoint Replay Behavior
On application restart, events processed since the last `offset.flush.interval.ms` (default 5000ms) checkpoint may be redelivered by the Debezium engine. PyDebeziumAI handles this safely because all writes are idempotent upserts keyed by primary-key document IDs.

## Features

- **Real-time sync** — Push-based WAL capture with low-latency delivery (typically ~280–500ms total vector indexing wall-clock time depending on embedding model & vector DB)
- **Deterministic IDs** — same row always maps to same document ID (correct upsert/delete semantics)
- **Pluggable backends** — Chroma, PGVector, Milvus (more coming)
- **Local embeddings** — works offline with `sentence-transformers`, no API key needed
- **LangGraph support** — reactive CDC-aware agent nodes
- **Schema evolution** — additive columns and nullable changes handled gracefully
- **Retry + DLQ** — exponential backoff and dead-letter queue for reliability
- **Connect mode** — JPype-native SourceRecord for lower latency (no JSON round-trip)

## Architecture

```
┌─────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Debezium   │───►│ IngestionHandler │───►│  DocumentBuilder │
│  (via       │    │  (JSON / Connect)│    │  (Projection     │
│  pydbzengine│    └──────────────────┘    │   Policy + ID)   │
└─────────────┘                            └────────┬─────────┘
                                                    │
                    ┌──────────────────┐    ┌───────▼─────────┐
                    │ LangChain /      │◄───│   SyncManager   │
                    │ LangGraph        │    │  (upsert/delete │
                    │ Retriever        │    │   + retry/DLQ)  │
                    └──────────────────┘    └───────┬─────────┘
                                                    │
                                           ┌────────▼─────────┐
                                           │  VectorStore     │
                                           │  Adapter         │
                                           │ (Chroma/PGVector │
                                           │  /Milvus)        │
                                           └──────────────────┘
```

## Installation

| Extra | Description |
|-------|-------------|
| `chroma` | Chroma vector store backend |
| `pgvector` | PostgreSQL PGVector backend |
| `milvus` | Milvus vector store backend |
| `local-embeddings` | sentence-transformers (no API key) |
| `openai` | OpenAI embeddings |
| `langgraph` | LangGraph node support |
| `debezium` | pydbzengine JVM bridge |
| `dev` | All dev/test dependencies |

## Contributing

Please see [CONVENTIONS.md](CONVENTIONS.md) for coding styles, formatting, type check guidelines, and commit sign-off requirements.

## License

Apache 2.0 — see [LICENSE.txt](LICENSE.txt)
