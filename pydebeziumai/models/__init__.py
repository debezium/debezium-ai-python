"""Models package — canonical types for Debezium CDC events."""

from pydebeziumai.models.connect_message import (
    ConnectMessageExtractor,
    ConversionConfig,
    SourceRecordExtractor,
    extract_all,
    extract_connect_all,
    print_record_info,
    struct_to_dict,
)
from pydebeziumai.models.datastructures import (
    DebeziumRecord,
    DebeziumSchema,
    connect_records_from_batch,
    records_from_batch,
)
from pydebeziumai.models.event import (
    DebeziumEventModel,
    DebeziumPayloadModel,
    DebeziumSchemaField,
    DebeziumSchemaModel,
)

__all__ = [
    # Pydantic models
    "DebeziumEventModel",
    "DebeziumPayloadModel",
    "DebeziumSchemaModel",
    "DebeziumSchemaField",
    # Extractors
    "ConversionConfig",
    "ConnectMessageExtractor",
    "SourceRecordExtractor",
    "struct_to_dict",
    "print_record_info",
    "extract_all",
    "extract_connect_all",
    # Data structures
    "DebeziumRecord",
    "DebeziumSchema",
    "records_from_batch",
    "connect_records_from_batch",
]
