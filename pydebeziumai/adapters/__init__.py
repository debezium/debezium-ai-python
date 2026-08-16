"""Vector store adapters for PyDebeziumAI."""

from __future__ import annotations

import importlib
from typing import Any

from pydebeziumai.adapters.base import VectorStoreAdapter as VectorStoreAdapter

_MODULE_LOOKUP = {
    "ChromaAdapter": "pydebeziumai.adapters.chroma",
    "MilvusAdapter": "pydebeziumai.adapters.milvus",
    "PGVectorAdapter": "pydebeziumai.adapters.pgvector",
}


def __getattr__(name: str) -> Any:
    """Lazily import adapter classes to avoid eager dependency loading."""
    if name in _MODULE_LOOKUP:
        module = importlib.import_module(_MODULE_LOOKUP[name])
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """Expose available attributes including lazy-loaded adapter classes."""
    return sorted(list(_MODULE_LOOKUP.keys()) + ["VectorStoreAdapter"])


__all__ = [
    "ChromaAdapter",
    "MilvusAdapter",
    "PGVectorAdapter",
    "VectorStoreAdapter",
]
