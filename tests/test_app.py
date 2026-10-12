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


def test_confirm_all_links(app):
    app = next(b for b in app.button if b.key == "confirm-all").click().run()
    assert not app.exception
    assert not any(b.key and b.key.startswith("confirm-") for b in app.button)


def test_materials_show_supplier_confirmation(app):
    materials = app.dataframe[1].value
    row = materials[materials["PO"] == "PO-24150"].iloc[0]
    assert row["Status"] == "✅ Confirmed by supplier"
