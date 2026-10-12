"""Render the Streamlit app headless from the cached seed (no LLM, no browser)."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).parent.parent / "src" / "delay_ai" / "app.py"


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("DELAY_AI_NO_BROWSER_STORAGE", "1")
    return AppTest.from_file(str(APP), default_timeout=60).run()


def test_renders_seeded_state_on_one_page(app):
    assert not app.exception
    assert app.title[0].value == "Riverside Court schedule"
    assert "Completion **01 Sep 2027**" in app.markdown[0].value
    assert {s.value for s in app.subheader} == {"✨ AI assistant", "Inbox", "Materials"}
    assert len(app.tabs) == 0
    assert any(m.value.startswith("⚠️ **Structural steel") for m in app.markdown)


def test_confirming_a_link_removes_it_from_decisions(app):
    assert any(b.key == "confirm-PO-24170" for b in app.button)
    app = next(b for b in app.button if b.key == "confirm-PO-24170").click().run()
    assert not app.exception
    assert not any(b.key == "confirm-PO-24170" for b in app.button)
