"""Read a supplier email or team chat message: rules first, the LLM for the rest."""

import calendar
import re
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from delay_ai.llm import complete_structured
from delay_ai.models import Email, Material

PO_PATTERN = re.compile(r"\bPO-\d+\b")
MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}
NUMERIC_DATE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
WRITTEN_DATE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(" + "|".join(MONTHS) + r")\s+(\d{4})\b", re.IGNORECASE
)


class RuleFacts(BaseModel):
    """What plain pattern matching finds in the email."""

    po_numbers: list[str]
    dates: list[date]  # only dates written in full, with a year


def apply_rules(email: Email) -> RuleFacts:
    text = f"{email.subject}\n{email.body}"
    found = [(int(d), int(m), int(y)) for d, m, y in NUMERIC_DATE.findall(text)]
    found += [(int(d), MONTHS[m.lower()], int(y)) for d, m, y in WRITTEN_DATE.findall(text)]
    dates = []
    for day, month, year in found:
        try:
            dates.append(date(year, month, day))
        except ValueError:
            pass  # e.g. 31/02/2027
    return RuleFacts(po_numbers=list(dict.fromkeys(PO_PATTERN.findall(text))), dates=dates)


EmailKind = Literal[
    "order_confirmation",  # new order(s) with planned delivery dates
    "delivery_change",  # a firm new delivery date
    "delivery_confirmation",  # delivery confirmed, date restated
    "possible_delay",  # a delay is hinted at but there is no firm date
    "not_relevant",
]


class ExtractedItem(BaseModel):
    po_number: str | None = Field(description="PO number, or null if it cannot be determined")
    description: str
    quantity: float | None
    unit: str | None
    delivery_date: date | None = Field(description="Planned (orders) or new (changes) date")


class EmailExtraction(BaseModel):
    kind: EmailKind
    supplier: str | None = Field(description="Supplier company name")
    items: list[ExtractedItem]
    reason: str | None = Field(description="Why the delivery changed, if it did")
    confidence: float = Field(description="0 to 1: how sure you are about the whole extraction")


SYSTEM_PROMPT = """You read messages about construction material deliveries for a UK
contractor: emails from suppliers, or chat messages from the contractor's own team
passing on news (e.g. "Pennine rang, steel is now 12 Jan").
Classify the message and extract every order or delivery it mentions.

Rules:
- Use only what the email says. Never invent PO numbers or dates.
- For orders, give one item per PO number.
- If an update does not quote a PO number, pick one from the known orders only when the
  email clearly refers to it; otherwise leave po_number null.
- Resolve relative dates ("next Wednesday", "16 June next year") using the date the
  email was sent.
- Dates are UK format (day/month).
- Lower your confidence when the email is vague or you had to guess."""


def extract_with_llm(email: Email, facts: RuleFacts, known: list[Material]) -> EmailExtraction:
    dates = [str(d) for d in facts.dates]
    orders = "\n".join(
        f"- {m.po_number}: {m.description}, planned delivery {m.planned_delivery}" for m in known
    )
    user = f"""Sent: {email.sent_at:%A %d %B %Y}
From: {email.sender} (via {email.channel})
Subject: {email.subject}

{email.body}

---
Known orders{" from this sender" if email.channel == "email" else ""}:
{orders or "(none)"}

Found by pattern matching:
PO numbers: {facts.po_numbers or "none"}
Full dates: {dates or "none"}"""
    return complete_structured(SYSTEM_PROMPT, user, EmailExtraction)
