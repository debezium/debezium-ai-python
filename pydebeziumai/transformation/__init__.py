"""Transformation layer — CDC events → LangChain Documents."""

from pydebeziumai.transformation.document_builder import BuildResult, DocumentBuilder
from pydebeziumai.transformation.id_strategy import (
    CompositeIdStrategy,
    CustomIdStrategy,
    IdStrategy,
    TablePkIdStrategy,
    resolve_id_strategy,
)
from pydebeziumai.transformation.projection_policy import ProjectionPolicy, TableProjectionPolicy

__all__ = [
    "IdStrategy",
    "TablePkIdStrategy",
    "CompositeIdStrategy",
    "CustomIdStrategy",
    "resolve_id_strategy",
    "ProjectionPolicy",
    "TableProjectionPolicy",
    "DocumentBuilder",
    "BuildResult",
]
