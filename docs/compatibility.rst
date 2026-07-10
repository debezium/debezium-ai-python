Compatibility Matrix
====================

Below is the list of supported dependency and system versions for ``pydebeziumai``:

.. list-table:: Supported Versions
   :widths: 40 60
   :header-rows: 1

   * - Dependency
     - Supported Versions
   * - Python
     - 3.10, 3.11, 3.12
   * - Debezium Engine
     - 3.0+ (requires Java 17+)
   * - PostgreSQL (Source)
     - 15, 16, 17
   * - MySQL (Source)
     - 8.0, 8.4 (LTS)
   * - Chroma (Vector DB)
     - chromadb >= 0.5
   * - PGVector (Vector DB)
     - PostgreSQL >= 15 with pgvector extension >= 0.5
   * - Milvus (Vector DB)
     - pymilvus < 2.6.0, milvus-lite >= 2.4.0
