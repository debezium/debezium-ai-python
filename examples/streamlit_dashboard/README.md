# Real-Time Streamlit Live Visual Dashboard (MySQL ➔ Milvus)

This example demonstrates an interactive, real-time **Change Data Capture (CDC) and Vector Retrieval Dashboard** powered by **PyDebeziumAI**, **MySQL 8.0**, and **Milvus**.

It showcases how operational transactions committed to MySQL binary logs are streamed, transformed into LangChain documents, and indexed into Milvus vector store with sub-second latency.

---

##  Architecture

```
 +--------------------+            CDC Stream (JSON)              +-----------------------+
 |   MySQL 8.0        | ────────────────────────────────────────► |     PyDebeziumAI      |
 | (binlog_format=ROW)|   io.debezium.connector.mysql.MySqlConnector | (Ingestion & Transform)|
 +--------------------+                                           +-----------+-----------+
                                                                              |
                                                                              | MilvusAdapter
                                                                              v
 +----------------------------------------------------------------------------+----------+
 |                              Streamlit Live Dashboard                                 |
 |  [MySQL Mutation Console]    │    [Live CDC Activity Stream]   │   [Milvus Semantic Search]|
 +---------------------------------------------------------------------------------------+
```

---

##  Features

1. ** MySQL Mutation Console**:
   * Execute `INSERT`, `UPDATE`, and `DELETE` SQL queries directly on the source database from an interactive GUI.
2. ** Real-Time CDC Activity Feed**:
   * View live stream events captured from MySQL binary logs with operation badges (`c` for Insert, `u` for Update, `d` for Delete).
3. ** Milvus Semantic Search & RAG**:
   * Search the live Milvus vector database using natural language queries to verify instant context freshness.
4. ** Live Health & Metrics**:
   * Displays database connection status, total vector index size, and processed CDC event counters.

---

##  Quickstart Guide

### 1. Prerequisites

* **Docker & Docker Compose** installed.
* **Java 17+** installed (required for Debezium Embedded Engine).
* Downloaded Debezium connector JARs:
  ```bash
  python tools/setup_jars.py
  ```

---

### 2. Start MySQL Container

Launch MySQL 8.0 configured with row-based binary logging:

```bash
cd examples/streamlit_dashboard
docker compose up -d
```

Verify that MySQL is up and listening on port `3306`:
```bash
docker compose ps
```

---

### 3. Install Python Dependencies

Install the required dashboard and vector store libraries:

```bash
pip install -r requirements.txt
```

---

### 4. Launch the Streamlit Dashboard

Start the Streamlit web application. The app will automatically initialize the embedded Milvus-Lite vector store (`milvus_demo.db`) and start the CDC engine as a background thread:

```bash
streamlit run app.py
```

The interactive dashboard will open automatically in your browser at `http://localhost:8501`.

---

##  Live Demo Walkthrough

1. **Insert a Product**:
   * In the **MySQL Mutation Console**, select **Insert Product**.
   * Enter a new item (e.g. `Noise Cancelling Earbuds`, Category: `Electronics`, Price: `$149.99`).
   * Click **Execute Insert**.
   * Notice the instant `INSERT (c)` event badge appear in the **Live CDC Event Stream**.
2. **Verify Semantic Search**:
   * In the **Milvus Semantic Search** panel, search for `earbuds` or `audio`.
   * The new product is immediately retrieved with similarity scores!
3. **Update Price or Description**:
   * Select **Update Product** and change the price to `$99.99`.
   * Submit the update. Notice the `UPDATE (u)` event in the stream and run the search again to confirm the updated price.
