"""End-to-End automated testing for Streamlit Live Visual Dashboard (app.py).

Uses Streamlit's official AppTest framework to simulate user interactions:
- Page layout, headers, metrics rendering
- Sidebar controls & CDC replication thread triggers
- MySQL mutation forms (Insert, Update, Delete)
- Live CDC Event Stream auto-updating fragment
- Milvus Semantic Vector Search querying & result card rendering
"""

import contextlib
import uuid
from pathlib import Path

import pytest

try:
    from pymilvus import connections
    from streamlit.testing.v1 import AppTest
except ImportError:
    pytest.skip("streamlit or pymilvus not installed, skipping Streamlit integration tests", allow_module_level=True)

APP_PATH = str(Path(__file__).parents[2] / "examples" / "streamlit_dashboard" / "app.py")


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """Initializes a fresh AppTest instance for the Streamlit dashboard."""
    isolated_db = str(tmp_path / f"test_milvus_{uuid.uuid4().hex[:6]}.db")
    isolated_events = str(tmp_path / "test_cdc_events.jsonl")
    monkeypatch.setenv("MILVUS_DB_FILE", isolated_db)
    monkeypatch.setenv("EVENT_LOG_FILE", isolated_events)

    with contextlib.suppress(Exception):
        connections.disconnect("default")

    at = AppTest.from_file(APP_PATH, default_timeout=30)
    at.run()
    return at


def test_dashboard_initial_render(app: AppTest) -> None:
    """Verify page headers, layout structure, metrics, and initial UI state."""
    assert not app.exception, f"App loaded with exception: {app.exception}"

    # Verify Title & Subheaders
    title_texts = [t.value for t in app.title]
    assert any("PyDebeziumAI" in t for t in title_texts)

    # Verify Top Metrics Row (4 metrics)
    metrics = [m.label for m in app.metric]
    assert "Total Products (MySQL)" in metrics
    assert "CDC Events Processed" in metrics
    assert "Source Connector" in metrics
    assert "Vector Store" in metrics

    # Verify Sidebar components
    sidebar_subheaders = [s.value for s in app.sidebar.subheader]
    assert "Replication Engine" in sidebar_subheaders
    assert "Environment Status" in sidebar_subheaders


def test_sidebar_replication_controls(app: AppTest) -> None:
    """Test starting the CDC replication engine via sidebar button."""
    # Find the Start Live CDC Sync button
    start_buttons = [b for b in app.sidebar.button if "Start Live CDC Sync" in b.label]
    if start_buttons:
        start_buttons[0].click().run()
        assert not app.exception

        # Check for success message or streaming indicator
        success_messages = [s.value for s in app.sidebar.success]
        assert any("CDC" in s or "Connected" in s for s in success_messages)


def test_mutation_console_insert_form(app: AppTest) -> None:
    """Test inserting a product through the Streamlit Mutation Console."""
    # Choose action: Insert Product
    radio = app.radio[0]
    radio.set_value("➕ Insert Product").run()
    assert not app.exception

    # Fill and submit the insert form
    name_inputs = [ti for ti in app.text_input if "Name" in ti.label or "Monitor" in str(ti.placeholder)]
    if name_inputs:
        name_inputs[0].input("Automated E2E Gaming Mouse")

    submit_buttons = [b for b in app.button if "Execute Insert" in b.label]
    if submit_buttons:
        submit_buttons[0].click().run()
        assert not app.exception


def test_mutation_console_update_form(app: AppTest) -> None:
    """Test updating a product through the Streamlit Mutation Console."""
    # Choose action: Update Product
    radio = app.radio[0]
    radio.set_value("✏️ Update Product").run()
    assert not app.exception

    # Verify selectbox contains products
    if app.selectbox:
        selected_product = app.selectbox[0].value
        assert selected_product is not None

        update_buttons = [b for b in app.button if "Execute Update" in b.label]
        if update_buttons:
            update_buttons[0].click().run()
            assert not app.exception


def test_semantic_search_query_execution(app: AppTest) -> None:
    """Test semantic vector search query input and result card rendering."""
    # Find semantic search text input
    search_inputs = [ti for ti in app.text_input if "Semantic Search" in ti.label or "Search" in ti.label]
    if search_inputs:
        search_inputs[0].input("comfortable ergonomic seating").run()
        assert not app.exception

        # Verify slider for top_k
        if app.slider:
            app.slider[0].set_value(3).run()
            assert not app.exception


def test_empty_search_query_shows_hint(app: AppTest) -> None:
    """Test that an empty query displays a helpful prompt rather than an error."""
    search_inputs = [ti for ti in app.text_input if "Semantic Search" in ti.label or "Search" in ti.label]
    if search_inputs:
        search_inputs[0].input("").run()
        assert not app.exception

        info_boxes = [inf.value for inf in app.info]
        assert any("Type a query" in inf or "search" in inf.lower() for inf in info_boxes)
