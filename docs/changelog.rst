Changelog
=========

All notable changes to the ``pydebeziumai`` library will be documented in this file.

Version 0.1.0 (TBD)
-------------------

*Initial Pre-release*

* **Core Engine**: Implemented Pydantic event serialization and ingestion handlers for JSON stream inputs (``JsonIngestionHandler``) and JPype JVM-based logical replication records (``ConnectIngestionHandler``).
* **Transformation Layer**: Introduced ``DocumentBuilder`` supporting custom ``IdStrategy`` keys and ``ProjectionPolicy`` column projections to map database writes into standard LangChain Document objects.
* **Synchronization Layer**: Implemented ``SyncManager`` supporting exponential retry backoff, hard deletes, soft delete tag updates, and thread-safe dead-letter queueing (``DeadLetterQueue``).
* **Retrieval Integrations**: Added support for standard LangChain retrievers (``create_retriever_tool``) and LangGraph reactive retriever nodes (``create_retriever_node``).
* **Adapters**: Operational support for three vector database adapters: Chroma, PGVector, and Milvus.
