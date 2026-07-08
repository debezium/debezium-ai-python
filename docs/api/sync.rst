Synchronization Layer
=====================

The Synchronization Layer orchestrates the continuous delivery of database event payloads into target vector databases. It handles batch processing, operation compaction, retries, and error routing.

Module Summary
--------------

.. autosummary::
   :nosignatures:

   ~pydebeziumai.sync.manager.SyncManager
   ~pydebeziumai.sync.manager.DeadLetterQueue
   ~pydebeziumai.sync.manager.RetryConfig

API Reference
-------------

.. automodule:: pydebeziumai.sync.manager
   :members:
   :show-inheritance:
