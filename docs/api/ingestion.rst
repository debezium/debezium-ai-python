Ingestion Layer
===============

The Ingestion Layer is responsible for capturing Debezium change data events from various input streams (Kafka Connect, JSON files, etc.) and converting them into normalized Python models.

Module Summary
--------------

.. autosummary::
   :nosignatures:

   ~pydebeziumai.ingestion.base.BaseIngestionHandler
   ~pydebeziumai.ingestion.json_handler.JsonIngestionHandler
   ~pydebeziumai.ingestion.connect_handler.ConnectIngestionHandler

API Reference
-------------

.. automodule:: pydebeziumai.ingestion.base
   :members:
   :show-inheritance:

.. automodule:: pydebeziumai.ingestion.json_handler
   :members:
   :show-inheritance:

.. automodule:: pydebeziumai.ingestion.connect_handler
   :members:
   :show-inheritance:
