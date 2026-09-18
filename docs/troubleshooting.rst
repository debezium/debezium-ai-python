Troubleshooting Guide
=====================

This guide covers common setup, connection, and runtime issues encountered when running ``pydebeziumai``.

Database Connection Refused & Authentication Failures
------------------------------------------------------

**Symptom:**
Connector raises ``FATAL: password authentication failed for user "postgres"`` or connection refusal when initializing ``LiveContext`` or ``SyncManager``.

**Common Causes & Solutions:**
1. **Port Collisions:** A pre-existing PostgreSQL or MySQL service running natively on the host machine may be bound to default ports (``5432`` / ``3306``), intercepting connection attempts before they reach your Dockerized database.

   * *Fix:* Check running services on your host machine (``netstat -ano`` or ``lsof -i :5432``) or map the Docker container to an alternate host port (e.g. ``5433:5432``) and update ``database.port`` in your connector configuration.

2. **Replication Permissions:** PostgreSQL CDC requires ``REPLICATION`` user privileges and ``wal_level=logical`` in ``postgresql.conf``.

   * *Fix:* Verify your database configuration contains:
     ::

        wal_level = logical
        max_wal_senders = 10
        max_replication_slots = 10

JVM & Java Environment Setup
-----------------------------

**Symptom:**
``JPype`` raises ``JVMNotFoundException`` or fails to start the Java Virtual Machine.

**Solutions:**
Ensure Java 17+ is installed and set ``JAVA_HOME`` explicitly before running your Python process:

.. code-block:: bash

   # Linux
   export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64

   # macOS
   export JAVA_HOME=$(/usr/libexec/java_home -v17)

   # Windows
   set JAVA_HOME=C:\Program Files\Java\jdk-17

Run the setup helper script to ensure all Debezium engine JAR dependencies are extracted into place:

.. code-block:: bash

   python tools/setup_jars.py

Offset Flush Intervals & Event Replay
--------------------------------------

**Symptom:**
On application restart, previously processed database records are re-emitted by Debezium.

**Explanation:**
Debezium checkpoints WAL positions to disk based on ``offset.flush.interval.ms`` (default 5000ms). If an application crashes before a flush window completes, un-checkpointed WAL events will be replayed upon restart.

**Safety:**
``pydebeziumai`` guarantees idempotency across all vector store adapters by keying document IDs directly from primary keys (e.g. ``TablePkIdStrategy``). Replayed events perform idempotent upserts, preventing vector duplication.
