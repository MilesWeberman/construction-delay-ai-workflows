from datetime import UTC, date, datetime

from delay_ai import extraction
from delay_ai.extraction import EmailExtraction, apply_rules, extract_with_llm
from delay_ai.models import Email, Material


def email(body, subject="Delivery"):
    return Email(
        message_id="m1",
        sender="orders@supplier.example",
        subject=subject,
        sent_at=datetime(2026, 10, 12, 9, tzinfo=UTC),
        body=body,
    )


def test_rules_find_po_numbers_once_in_order():
    facts = apply_rules(email("PO-2 then PO-1 and PO-2 again", subject="Re: PO-1"))
    assert facts.po_numbers == ["PO-1", "PO-2"]


def test_rules_find_numeric_and_written_dates():
    facts = apply_rules(email("by 19/05/2027, or Tuesday 12th January 2027, or 3 March 2027"))
    assert facts.dates == [date(2027, 5, 19), date(2027, 1, 12), date(2027, 3, 3)]


def test_rules_skip_dates_without_year_and_invalid_dates():
    facts = apply_rules(email("not 16/06, not 23rd June, not 31/02/2027"))
    assert facts.dates == []


def test_llm_prompt_includes_rule_findings_and_known_orders(monkeypatch):
    captured = {}

    def fake_complete(system, user, schema):
        captured["user"] = user
        return EmailExtraction(
            kind="not_relevant", supplier=None, items=[], reason=None, confidence=1
        )

    monkeypatch.setattr(extraction, "complete_structured", fake_complete)
    known = Material(
        po_number="PO-9",
        description="Kitchen units",
        supplier="Calder",
        supplier_email="orders@supplier.example",
        planned_delivery=date(2027, 6, 16),
    )
    e = email("PO-9 moves to 19/05/2027")
    extract_with_llm(e, apply_rules(e), [known])

    assert "PO-9: Kitchen units, planned delivery 2027-06-16" in captured["user"]
    assert "['PO-9']" in captured["user"]
    assert "2027-05-19" in captured["user"]
