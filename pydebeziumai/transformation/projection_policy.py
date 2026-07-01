"""Field projection and content-template policies for document building.

A ProjectionPolicy controls:
  - Which row fields become the ``page_content`` of a LangChain Document.
  - Which fields appear in LangChain ``metadata`` (for filtered retrieval).
  - Optional pre-compiled ``string.Template`` content templates
    (e.g. ``"$name — $description"``).
  - Per-table overrides so different tables have different rendering rules.
"""

from __future__ import annotations

import logging
import string
from dataclasses import dataclass, field
from typing import Any

from pydebeziumai.models.event import DebeziumEventModel

logger = logging.getLogger(__name__)


def _coerce_metadata_value(v: Any) -> Any:
    """Ensure a metadata value is JSON-serialisable (str/int/float/bool/None)."""
    if v is None or isinstance(v, (bool, int, float, str)):
        return v
    # datetime, date, timedelta, Decimal → str
    return str(v)


@dataclass
class TableProjectionPolicy:
    """
    Field-level projection configuration for a single table.

    Attributes:
        include_fields: If set, only these fields enter the content block.
        exclude_fields: Fields excluded (binary blobs, secrets, etc.).
            Applies only when include_fields is not specified.
        metadata_fields: Fields copied into Document.metadata; None = all.
        content_template: Optional ``string.Template`` pattern.
            Uses ``$variable`` or ``${variable}`` syntax.
            Example: ``"$product_name — price: $price"``
    """

    include_fields: list[str] | None = None
    exclude_fields: list[str] = field(default_factory=list)
    metadata_fields: list[str] | None = None
    content_template: str | None = None

    def __post_init__(self) -> None:
        """Pre-compile the content template for performance."""
        self._compiled_template: string.Template | None = None
        if self.content_template is not None:
            self._compiled_template = string.Template(self.content_template)

    def project_row(self, row: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """
        Project a row dict into ``(page_content, metadata)``.

        Returns:
            A tuple of the page_content string and a metadata dict.
        """
        if self.include_fields is not None:
            content_fields = {k: v for k, v in row.items() if k in self.include_fields}
        else:
            content_fields = {k: v for k, v in row.items() if k not in self.exclude_fields}

        if self._compiled_template is not None:
            try:
                substituted = self._compiled_template.substitute(
                    {k: ("" if v is None else v) for k, v in content_fields.items()}
                )
                page_content = substituted
            except (KeyError, ValueError) as exc:
                # Graceful fallback so we never drop an event
                logger.warning("Failed to format content template: %s. Falling back to default content.", exc)
                page_content = _default_content(content_fields) + f" [template error: {exc}]"
        else:
            page_content = _default_content(content_fields)

        if self.metadata_fields is not None:
            raw_meta = {k: v for k, v in row.items() if k in self.metadata_fields}
        else:
            raw_meta = dict(row)

        metadata = {k: _coerce_metadata_value(v) for k, v in raw_meta.items()}
        return page_content, metadata


def _default_content(fields: dict[str, Any]) -> str:
    """Render a human-readable ``field: value`` string from selected fields."""
    parts = []
    for k, v in fields.items():
        parts.append(f"{k}: {'' if v is None else v}")
    return "\n".join(parts) if parts else "(empty row)"


class ProjectionPolicy:
    """
    Top-level projection policy with optional per-table overrides.

    Usage::

        policy = ProjectionPolicy(
            default=TableProjectionPolicy(
                exclude_fields=["password_hash", "avatar_blob"],
            ),
            overrides={
                "products": TableProjectionPolicy(
                    content_template="$name — $description — $$${price}",
                    metadata_fields=["id", "category", "price"],
                )
            },
        )

        page_content, metadata = policy.project(event)
    """

    def __init__(
        self,
        default: TableProjectionPolicy | None = None,
        overrides: dict[str, TableProjectionPolicy] | None = None,
    ) -> None:
        self.default = default or TableProjectionPolicy()
        self.overrides = overrides or {}

    def project(self, event: DebeziumEventModel) -> tuple[str, dict[str, Any]]:
        """
        Project the current row of a CDC event into (page_content, metadata).

        Returns empty content string for delete events (no `after` row).
        """
        table = event.table_name
        is_override = table in self.overrides
        policy = self.overrides.get(table, self.default)
        logger.debug("Projecting fields for table=%r using %s policy", table, "override" if is_override else "default")
        row = event.payload.current_row or {}
        return policy.project_row(row)

    @classmethod
    def default_policy(cls) -> ProjectionPolicy:
        """Return a sensible default policy (all fields, no template)."""
        return cls()
