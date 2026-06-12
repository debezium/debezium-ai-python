"""Ingestion layer — receive CDC events from pydbzengine and normalize them."""

from pydebeziumai.ingestion.base import BaseIngestionHandler
from pydebeziumai.ingestion.connect_handler import ConnectIngestionHandler
from pydebeziumai.ingestion.json_handler import JsonIngestionHandler

__all__ = ["BaseIngestionHandler", "JsonIngestionHandler", "ConnectIngestionHandler"]
