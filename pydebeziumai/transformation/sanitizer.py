"""Metadata sanitization utilities for vector database compatibility."""

from __future__ import annotations

import decimal
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

logger = logging.getLogger(__name__)


def sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    """Coerce metadata values to types Chroma/PGVector/Milvus can store.

    Chroma accepts: str, int, float, bool.
    This converts bytes→hex str, Decimal→float, date/datetime→isoformat,
    None→"null", and everything else→str.
    """
    clean: dict[str, Any] = {}
    for k, v in meta.items():
        if v is None:
            clean[k] = "null"
        elif isinstance(v, (bool, int, float, str)):
            clean[k] = v
        elif isinstance(v, decimal.Decimal):
            clean[k] = float(v)
        elif isinstance(v, (bytes, bytearray)):
            clean[k] = bytes(v).hex()
        elif isinstance(v, (datetime, date, time)):
            clean[k] = v.isoformat()
        elif isinstance(v, timedelta):
            clean[k] = v.total_seconds()
        elif isinstance(v, (dict, list, set, tuple)):
            clean[k] = str(v)
        else:
            clean[k] = str(v)
    return clean
