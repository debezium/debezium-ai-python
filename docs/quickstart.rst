Quickstart Guide
================

This guide will walk you through installing ``pydebeziumai``, satisfying system prerequisites, and running a database to vector-store synchronization and retrieval pipeline.

Prerequisites
-------------

Before using ``pydebeziumai`` with the embedded Debezium engine, verify that your system meets the following requirements:

1. **Java Runtime Environment (JRE) / JDK**:
   - Debezium 3.0+ requires **Java 17 or higher**.
   - Make sure a JVM is installed and that the ``JAVA_HOME`` environment variable points to your JDK directory:

     .. code-block:: bash

        export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

2. **JPype Connection**:
   - ``pydebeziumai`` uses JPype to establish a direct in-process bridge between Python and the Java Virtual Machine. When the engine starts, JPype launches a JVM in the background.

Installation
------------

You can install the core library along with specific vector store and ingestion extras using pip:

.. code-block:: bash

   # Install the core library with Chroma vector store support
   pip install "pydebeziumai[chroma]"

   # Install with Debezium embedded engine support
   pip install "pydebeziumai[chroma,debezium]"

   # Or install all dependencies for local development
   pip install "pydebeziumai[dev]"

Download Debezium JARs
----------------------

To run the embedded Debezium connector, you need to download the required database connector JAR files. If you have cloned the repository, a helper script is provided in the repository root under the ``tools/`` folder to automate this:

.. code-block:: bash

   python3 tools/setup_jars.py

Projection Templates & Dollar-Sign Escaping
-------------------------------------------

When transforming database tables into documents, you can customize the formatting of the generated document content using a :class:`~pydebeziumai.transformation.projection_policy.TableProjectionPolicy` template.

Templates use Python's ``string.Template`` dollar-sign syntax:
- ``$column_name``: Replaced by the value of that column.
- ``$$``: Escapes a literal dollar sign.

For example, to display a price prefixed with a currency dollar sign:

.. code-block:: python

   content_template="Product: $name\nPrice: $$$price"

Here, ``$$`` renders as a literal ``$`` and ``$price`` resolves to the value of the ``price`` column, outputting ``Price: $49.99``.

Minimal Synchronization & Retrieval Example
-------------------------------------------

Below is a complete, runnable script demonstrating how to synchronize PostgreSQL WAL logical transactions into a Chroma vector store in real-time, and query it using the retrieval integration tools.

.. code-block:: python

   import os
   import time
   import threading
   from langchain_core.embeddings import FakeEmbeddings
   from pydebeziumai.adapters.chroma import ChromaAdapter
   from pydebeziumai.transformation.document_builder import DocumentBuilder
   from pydebeziumai.transformation.id_strategy import TablePkIdStrategy
   from pydebeziumai.transformation.projection_policy import ProjectionPolicy, TableProjectionPolicy
   from pydebeziumai.sync.manager import SyncManager
   from pydebeziumai.ingestion.json_handler import JsonIngestionHandler
   from pydebeziumai.retrieval.langgraph import create_retriever_tool

   # 1. Configure the Vector Adapter
   embeddings = FakeEmbeddings(size=384)
   adapter = ChromaAdapter(
       collection_name="inventory_catalog",
       embeddings=embeddings,
       persist_directory="./chroma_db",
   )

   # 2. Configure the Transformation Layer
   policy = ProjectionPolicy(
       default=TableProjectionPolicy(
           content_template="Product: $name\nCategory: $category\nPrice: $$$price",
           metadata_fields=["id", "category", "price"],
       )
   )
   builder = DocumentBuilder(
       id_strategy=TablePkIdStrategy(pk_fields=["id"]),
       projection_policy=policy,
   )

   # 3. Configure the Synchronization Manager
   from pydebeziumai.sync.manager import DeadLetterQueue
   dlq = DeadLetterQueue()
   sync_manager = SyncManager(
       vector_store_adapter=adapter,
       document_builder=builder,
       dlq=dlq,
   )

   # 4. Define Debezium Engine Properties
   properties = {
       "name": "inventory-connector",
       "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
       "database.hostname": "localhost",
       "database.port": "5432",
       "database.user": "postgres",
       "database.password": "postgrespassword",
       "database.dbname": "inventory_db",
       "topic.prefix": "inventory_server",
       "plugin.name": "pgoutput",
       "table.include.list": "public.products",
       "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
       "offset.storage.file.filename": "./offsets.dat",
       "offset.flush.interval.ms": "1000",
   }

   # 5. Build Debezium JSON-format engine with handler callback
   handler = JsonIngestionHandler()
   handler.add_event_callback(sync_manager.sync)
   engine = handler.build_engine(properties)

   # Run the Debezium engine inside a background thread so it doesn't block
   print("Starting Debezium synchronization pipeline in the background...")
   engine_thread = threading.Thread(target=engine.start, daemon=True)
   engine_thread.start()

   # Wait a few seconds for engine initialization and initial database snapshot
   time.sleep(5)

   # 6. Retrieve and Query the Synchronized Data
   # Create a standard LangChain tool to retrieve synchronized documents
   retriever_tool = create_retriever_tool(
       adapter=adapter,
       name="query_product_catalog",
       description="Search for products in our inventory by name or category.",
   )

   print("\nExecuting RAG Query...")
   # Search for a synchronized product
   query_input = "robot"
   results = retriever_tool.invoke({"query": query_input})
   print(f"Query: {query_input}\nResults:\n{results}")

   # Stop the engine
   print("Stopping Debezium engine...")
   engine.close()

Production Deployment Guidance
------------------------------

When deploying ``pydebeziumai`` in a production environment:

1. **Threading & Blocking Semantics**:
   - The ``engine.start()`` execution blocks the calling thread. Always run the engine in a background worker thread or a standalone process (like a system daemon).
   - Secure shutdowns by calling ``engine.close()`` inside exit handlers (such as Python's ``atexit`` or signal handlers).

2. **Handling the Dead Letter Queue (DLQ)**:
   - Configure a :class:`~pydebeziumai.sync.manager.DeadLetterQueue` inside the :class:`~pydebeziumai.sync.manager.SyncManager` to catch transform or network upsert failures.
   - Periodically drain the DLQ or export it to logs to resolve data inconsistencies:

     .. code-block:: python

        if not sync_manager.dlq.is_empty():
            failed_event, error = sync_manager.dlq.get()
            print(f"Error handling event {failed_event.key} at {failed_event.destination}: {error}")


Database Agnostic Architecture
------------------------------

While this guide focuses on PostgreSQL and MySQL as source databases (due to their popularity in transactional applications), the underlying `pydebeziumai` engine is database-agnostic. Because it is built directly on top of Debezium's unified embedded engine architecture, you can synchronize changes from any Debezium-supported database (such as MongoDB, Oracle, or SQL Server) by providing the corresponding Debezium database connector classes and defining a matching primary key extraction strategy.

Debezium Database Connector Configs
-----------------------------------

Depending on your source database, specify the correct properties for the Debezium engine.

PostgreSQL Connector Properties
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Below are standard properties to stream changes from a PostgreSQL instance:

.. code-block:: python

   properties = {
       "name": "inventory-postgres-connector",
       "connector.class": "io.debezium.connector.postgresql.PostgresConnector",
       "database.hostname": "localhost",
       "database.port": "5432",
       "database.user": "postgres",
       "database.password": "postgrespassword",
       "database.dbname": "inventory_db",
       "topic.prefix": "inventory_server",
       "plugin.name": "pgoutput",
       "table.include.list": "public.products",
       "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
       "offset.storage.file.filename": "./offsets.dat",
   }

MySQL Connector Properties
^^^^^^^^^^^^^^^^^^^^^^^^^^

Below are standard properties to stream changes from a MySQL instance:

.. code-block:: python

   properties = {
       "name": "inventory-mysql-connector",
       "connector.class": "io.debezium.connector.mysql.MySqlConnector",
       "database.hostname": "localhost",
       "database.port": "3306",
       "database.user": "debezium",
       "database.password": "dbzpassword",
       "database.server.id": "184054",  # Required unique ID for MySQL replica
       "database.server.name": "inventory_server",
       "topic.prefix": "inventory_server",
       "table.include.list": "inventory_db.products",
       "schema.history.internal.kafka.bootstrap.servers": "localhost:9092",
       "schema.history.internal.file.filename": "./schema_history.dat",
       "offset.storage": "org.apache.kafka.connect.storage.FileOffsetBackingStore",
       "offset.storage.file.filename": "./offsets.dat",
   }
