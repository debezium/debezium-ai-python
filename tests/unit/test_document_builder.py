"""Unit tests for DocumentBuilder and ProjectionPolicy."""

from __future__ import annotations

from langchain_core.documents import Document

from pydebeziumai.models.event import DebeziumEventModel
from pydebeziumai.transformation.document_builder import BuildResult, DocumentBuilder
from pydebeziumai.transformation.projection_policy import (
    ProjectionPolicy,
    TableProjectionPolicy,
)


class TestProjectionPolicy:
    def test_default_includes_all_fields(self) -> None:
        policy = TableProjectionPolicy()
        row = {"id": 1, "name": "Widget", "price": 9.99}
        content, metadata = policy.project_row(row)
        assert "name: Widget" in content
        assert "price: 9.99" in content
        assert metadata["id"] == 1

    def test_include_fields(self) -> None:
        policy = TableProjectionPolicy(include_fields=["name", "price"])
        row = {"id": 1, "name": "Widget", "price": 9.99, "secret": "hidden"}
        content, metadata = policy.project_row(row)
        assert "name: Widget" in content
        assert "secret" not in content

    def test_exclude_fields(self) -> None:
        policy = TableProjectionPolicy(exclude_fields=["password_hash", "blob"])
        row = {"id": 1, "name": "User", "password_hash": "abc", "blob": b"data"}
        content, _ = policy.project_row(row)
        assert "password_hash" not in content
        assert "blob" not in content
        assert "name: User" in content

    def test_content_template(self) -> None:
        policy = TableProjectionPolicy(
            content_template="{name} — ${price}",
            include_fields=["name", "price"],
        )
        row = {"id": 1, "name": "Widget", "price": 9.99}
        content, _ = policy.project_row(row)
        assert content == "Widget — $9.99"

    def test_content_template_missing_key_graceful(self) -> None:
        policy = TableProjectionPolicy(
            content_template="{name} — {missing_field}",
        )
        row = {"name": "Widget"}
        content, _ = policy.project_row(row)
        assert "template error" in content
        assert "Widget" in content

    def test_metadata_fields_subset(self) -> None:
        policy = TableProjectionPolicy(metadata_fields=["id", "category"])
        row = {"id": 1, "name": "Widget", "category": "tools", "internal": "x"}
        _, metadata = policy.project_row(row)
        assert set(metadata.keys()) == {"id", "category"}

    def test_none_coerced_in_metadata(self) -> None:
        policy = TableProjectionPolicy()
        row = {"id": 1, "nullable": None}
        _, metadata = policy.project_row(row)
        assert metadata["nullable"] is None

    def test_per_table_override(self) -> None:
        override = TableProjectionPolicy(
            content_template="{title}",
            include_fields=["title"],
        )
        top_policy = ProjectionPolicy(overrides={"articles": override})

        from pydebeziumai.models.event import DebeziumEventModel

        event = DebeziumEventModel.from_dict(
            "srv.public.articles",
            '{"id": 1}',
            {"op": "c", "after": {"id": 1, "title": "Hello World", "body": "..."}},
        )
        content, _ = top_policy.project(event)
        assert content == "Hello World"


class TestDocumentBuilder:
    def test_build_insert_returns_document(
        self, insert_event: DebeziumEventModel, document_builder: DocumentBuilder
    ) -> None:
        result = document_builder.build(insert_event)
        assert isinstance(result, BuildResult)
        assert result.document is not None
        assert isinstance(result.document, Document)
        assert not result.is_delete

    def test_build_delete_returns_no_document(
        self, delete_event: DebeziumEventModel, document_builder: DocumentBuilder
    ) -> None:
        result = document_builder.build(delete_event)
        assert result.is_delete
        assert result.document is None

    def test_doc_id_is_stable_across_ops(
        self, insert_event: DebeziumEventModel, update_event: DebeziumEventModel, document_builder: DocumentBuilder
    ) -> None:
        r_insert = document_builder.build(insert_event)
        r_update = document_builder.build(update_event)
        assert r_insert.doc_id == r_update.doc_id

    def test_system_metadata_injected(
        self, insert_event: DebeziumEventModel, document_builder: DocumentBuilder
    ) -> None:
        result = document_builder.build(insert_event)
        assert result.document is not None
        meta = result.document.metadata
        assert meta["_table"] == "products"
        assert meta["_schema"] == "public"
        assert meta["_op"] == "c"
        assert meta["_ts_ms"] == 1_700_000_000_000

    def test_extra_metadata_merged(self, insert_event: DebeziumEventModel) -> None:
        builder = DocumentBuilder(extra_metadata={"tenant": "acme", "env": "prod"})
        result = builder.build(insert_event)
        assert result.document is not None
        assert result.document.metadata["tenant"] == "acme"
        assert result.document.metadata["env"] == "prod"

    def test_doc_id_set_on_document(self, insert_event: DebeziumEventModel, document_builder: DocumentBuilder) -> None:
        result = document_builder.build(insert_event)
        assert result.document is not None
        assert result.document.id == result.doc_id

    def test_snapshot_event_treated_as_insert(
        self, snapshot_event: DebeziumEventModel, document_builder: DocumentBuilder
    ) -> None:
        result = document_builder.build(snapshot_event)
        assert not result.is_delete
        assert result.op == "r"
        assert result.document is not None

    def test_page_content_non_empty_for_inserts(
        self, insert_event: DebeziumEventModel, document_builder: DocumentBuilder
    ) -> None:
        result = document_builder.build(insert_event)
        assert result.document is not None
        assert result.document.page_content.strip() != ""
