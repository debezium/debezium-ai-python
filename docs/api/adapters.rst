Vector Store Adapters
=====================

The adapters layer provides concrete wrappers around different vector database clients (Chroma, PGVector, Milvus). It allows the synchronization pipeline to write to any vector store using a unified interface.

Base Interface
--------------

.. autosummary::
   :nosignatures:

   ~pydebeziumai.adapters.base.VectorStoreAdapter

.. automodule:: pydebeziumai.adapters.base
   :members:
   :show-inheritance:

Vector Database Implementations
-------------------------------

.. autosummary::
   :nosignatures:

   ~pydebeziumai.adapters.chroma.ChromaAdapter
   ~pydebeziumai.adapters.pgvector.PGVectorAdapter
   ~pydebeziumai.adapters.milvus.MilvusAdapter

.. automodule:: pydebeziumai.adapters.chroma
   :members:
   :show-inheritance:

.. automodule:: pydebeziumai.adapters.pgvector
   :members:
   :show-inheritance:

.. automodule:: pydebeziumai.adapters.milvus
   :members:
   :show-inheritance:
