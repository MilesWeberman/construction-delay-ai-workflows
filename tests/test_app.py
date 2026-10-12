"""Render the Streamlit app headless from the cached seed (no LLM, no browser)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parent.parent / "src" / "delay_ai" / "app.py"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("DELAY_AI_NO_BROWSER_STORAGE", "1")
    return AppTest.from_file(str(APP), default_timeout=60).run()


def test_renders_seeded_state(app):
    assert not app.exception
    metrics = {m.label: m.value for m in app.metric}
    assert metrics["Expected completion"] == "01 Sep 2027"
    assert metrics["Links to confirm"] == "4"
    assert [t.label for t in app.tabs][2] == "📅 Schedule"


def test_confirming_a_link_updates_the_app(app):
    app = next(b for b in app.button if b.key == "confirm-PO-24170").click().run()
    assert not app.exception
    assert {m.label: m.value for m in app.metric}["Links to confirm"] == "3"


def test_calendar_view_renders(app):
    app.segmented_control[0].set_value("Calendar").run()
    assert not app.exception
