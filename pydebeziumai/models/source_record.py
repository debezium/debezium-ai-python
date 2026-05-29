"""Backwards-compatibility shim — re-exports from connect_message.py.

The original source_record.py is superseded by connect_message.py (PR #400).
This file is kept so that any existing imports of
``from pydebeziumai.models.source_record import ...`` continue to work.
"""

from pydebeziumai.models.connect_message import (  # noqa: F401
    ConversionConfig,
    SourceRecordExtractor,
    print_record_info,
    struct_to_dict,
)
