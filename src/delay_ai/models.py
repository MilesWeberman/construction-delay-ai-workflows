"""Core domain models: the project, its schedule, materials, contacts and emails."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel


class Project(BaseModel):
    name: str
    location: str
    start_date: date


class Activity(BaseModel):
    """A schedule activity. Durations are in working days (Mon-Fri)."""

    id: str
    name: str
    trade: str
    duration_days: int
    predecessors: list[str] = []


class Material(BaseModel):
    """An ordered material, built from supplier emails. One material per PO in the pilot."""

    po_number: str
    description: str
    supplier: str
    supplier_email: str
    quantity: float | None = None
    unit: str | None = None
    planned_delivery: date
    activity_id: str | None = None  # the activity that needs it, once linked


class Contact(BaseModel):
    """Someone to notify when a plan changes."""

    name: str
    role: str
    company: str
    email: str
    activity_ids: list[str] = []  # empty means "notify for every change"


class Email(BaseModel):
    """An inbound message: an email (folder, Gmail, Outlook) or a chat message from the team."""

    message_id: str
    sender: str  # email address, or the chat author's name
    subject: str
    sent_at: datetime
    body: str
    channel: Literal["email", "chat"] = "email"
