System Architecture
===================

PyDebeziumAI is structured around a modular, layered architecture designed to process Change Data Capture (CDC) events emitted by databases in real-time, transform them into semantic vector representations, and synchronize them into vector databases.

Overview
--------

The diagram below represents the logical propagation of transaction write-ahead log (WAL) events through PyDebeziumAI layers:

.. code-block:: text

   +-------------------------------------------------------+
   |  [External Source Database]                           |
   |  PostgreSQL / MySQL (writes WAL transaction logs)    |
   +---------------------------+---------------------------+
                               | WAL Logical Replication
                               v
   ================== PyDebeziumAI Boundaries =============
   |                                                       |
   |   +-----------------------------------------------+   |
   |   | Embedded Debezium Engine                      |   |
   |   | (Runs inside PyDebeziumAI Java/JVM process,   |   |
   |   |  captures replication stream events)          |   |
   |   +-----------------------+-----------------------+   |
   |                           |
   |                           v [Ingestion Layer]
   |   +-----------------------------------------------+   |
   |   | Ingestion Handlers                            |   |
   |   | (Extracts events into DebeziumEventModel)     |   |
   |   +-----------------------+-----------------------+   |
   |                           |
   |                           v [Transformation Layer]
   |   +-----------------------------------------------+   |
   |   | Document Builder                              |   |
   |   | (Computes stable IDs & projects columns)      |   |
   |   +-----------------------+-----------------------+   |
   |                           |
   |                           v [Synchronization Layer]
   |   +-----------------------------------------------+   |
   |   | Synchronization Manager                       |   |
   |   | (Coordinates batch upserts and DLQ routing)   |   |
   |   +-----------------------+-----------------------+   |
   |                           |
   |                           v [Adapters Layer]
   |   +-----------------------------------------------+   |
   |   | Vector Store Adapters                         |   |
   |   | (Chroma, PGVector, Milvus client wrappers)    |   |
   |   +-----------------------+-----------------------+   |
   |                           |
   =========================================================
                               | HTTP / TCP connection
                               v
   +---------------------------+---------------------------+
   |  [External Destination Vector Store]                  |
   |  Chroma / PGVector / Milvus / etc.                    |
   +-------------------------------------------------------+

Architectural Components
------------------------

1. Ingestion Layer
^^^^^^^^^^^^^^^^^^

The Ingestion Layer is responsible for capturing events produced by the Debezium engine. It supports two stream formats:

* **JSON format** (:class:`~pydebeziumai.ingestion.json_handler.JsonIngestionHandler`): Reads JSON strings produced by the standard Debezium engine format.
* **Connect format** (:class:`~pydebeziumai.ingestion.connect_handler.ConnectIngestionHandler`): Interacts directly with JVM ``SourceRecord`` structures using JPype (Debezium 3.0+ format) to eliminate JSON serialization overhead.

Both handlers normalize input payloads into a typed, canonical :class:`~pydebeziumai.models.event.DebeziumEventModel` containing structured metadata (operation type, destination table, primary key columns, and fields).

2. Transformation Layer
^^^^^^^^^^^^^^^^^^^^^^^

This layer parses database row changes into a standard LangChain :class:`~langchain_core.documents.Document`:

* **IdStrategy** (:class:`~pydebeziumai.transformation.id_strategy.IdStrategy`): Computes a unique, deterministic document ID (e.g., ``table:primary_key``) to guarantee updates map to the same vector index element.
* **ProjectionPolicy** (:class:`~pydebeziumai.transformation.projection_policy.ProjectionPolicy`): Defines how columns should be structured. It includes template string projections (e.g. mapping column name and description to page content) and defines which database fields should be mapped as metadata attributes.
* **Sanitizer** (:func:`~pydebeziumai.transformation.sanitizer.sanitize_metadata`): Cleans up formatting and metadata keys to be compatible with vector database requirements.

3. Synchronization Layer
^^^^^^^^^^^^^^^^^^^^^^^^

Managed by the :class:`~pydebeziumai.sync.manager.SyncManager`, this layer handles writing records to the target vector store:

* **Create/Update**: Maps to an idempotent vector upsert using the deterministic stable ID.
* **Delete**: Executes a hard delete (removing the document vector) or falls back to a soft-delete metadata tag update.
* **RetryConfig** (:class:`~pydebeziumai.sync.manager.RetryConfig`): Handles transient network/connection drops to vector backends using exponential backoff.
* **DeadLetterQueue** (:class:`~pydebeziumai.sync.manager.DeadLetterQueue`): Isolates unprocessable records to prevent pipeline blockages.

4. Retrieval Layer
^^^^^^^^^^^^^^^^^^

Exposes retriever tools compatible with LangChain agents and LangGraph reactive nodes, enabling real-time semantic RAG query execution against the synchronized vector collection using :func:`~pydebeziumai.retrieval.langgraph.create_retriever_tool` and :func:`~pydebeziumai.retrieval.langgraph.create_retriever_node`.
