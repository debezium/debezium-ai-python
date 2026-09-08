Compatibility Matrix
====================

Below is the list of supported dependency and system versions for ``pydebeziumai``:

.. list-table:: Supported Infrastructure & Vector Stores
   :widths: 40 60
   :header-rows: 1

   * - Component
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


Supported Embedding Models & Providers
--------------------------------------

``pydebeziumai`` integrates seamlessly with LangChain's ``Embeddings`` interface (``langchain_core.embeddings.Embeddings``). Any embedding provider or model that inherits from this base class can be used to generate vector embeddings during change data capture.

.. list-table:: Supported Embedding Providers & Packages
   :widths: 30 35 35
   :header-rows: 1

   * - Provider / Ecosystem
     - LangChain Integration Package
     - Popular Supported Models
   * - **OpenAI**
     - ``langchain-openai``
     - ``text-embedding-3-small``, ``text-embedding-3-large``, ``text-embedding-ada-002``
   * - **HuggingFace / Local**
     - ``langchain-huggingface``
     - ``all-MiniLM-L6-v2``, ``BAAI/bge-small-en-v1.5``, ``sentence-transformers``
   * - **Ollama (Local LLM)**
     - ``langchain-ollama``
     - ``nomic-embed-text``, ``mxbai-embed-large``
   * - **Cohere**
     - ``langchain-cohere``
     - ``embed-english-v3.0``, ``embed-multilingual-v3.0``
   * - **Google Vertex AI**
     - ``langchain-google-vertexai``
     - ``text-embedding-004``
   * - **AWS Bedrock**
     - ``langchain-aws``
     - Amazon Titan Embeddings (``amazon.titan-embed-text-v2:0``)
   * - **FastEmbed (Local ONNX)**
     - ``langchain-community``
     - FastEmbed ONNX models (``BAAI/bge-small-en-v1.5``)
   * - **Custom Providers**
     - Any ``langchain_core`` subclass
     - Custom embedding implementations subclassing ``Embeddings``

Example Configuration
~~~~~~~~~~~~~~~~~~~~~

Passing an embedding model provider to a vector store adapter:

.. code-block:: python

   # Using OpenAI Embeddings
   from langchain_openai import OpenAIEmbeddings
   from pydebeziumai.adapters.chroma import ChromaAdapter

   adapter = ChromaAdapter(
       collection_name="products",
       embeddings=OpenAIEmbeddings(model="text-embedding-3-small")
   )

   # Using Local Offline HuggingFace Embeddings (no API key needed)
   from langchain_huggingface import HuggingFaceEmbeddings

   local_adapter = ChromaAdapter(
       collection_name="products",
       embeddings=HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
   )
