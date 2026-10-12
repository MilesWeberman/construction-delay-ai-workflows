# Construction Delay AI Workflows

Pilot: reduce project delays caused by **late material deliveries**.

Delivery news (email, chat) → events → update affected schedule activities →
re-plan the schedule to minimise project delay → human review in a UI.

## Vision

The pilot starts with one problem, late deliveries. The real value is wider: this
tool becomes a **proactive, AI-enabled scheduling layer** that eventually replaces
a contractor's legacy scheduling systems. It is one place to store, view,
organise and optimise scheduling across every project.

Today's tools record the plan. This layer acts on it. When something changes, it
works out the effect on the programme, proposes ways to recover the time, and
orchestrates the follow-up with the people involved. Every change is
**optimised for reducing delay**.

It starts by connecting to the systems already in place and pulling from them:

- **Scheduling:** Primavera P6, Asta Powerproject, Microsoft Project
- **Email:** Outlook / Microsoft 365, Gmail
- **Procurement and ERP:** COINS, SAP, Viewpoint
- **Project and document platforms:** Procore, Autodesk Construction Cloud, Aconex
- **Spreadsheets:** Excel material and procurement trackers

Over time it becomes the contractor's own internal application. Planners and
site teams work in it directly, and the legacy tools become data sources rather
than the system of record.

## Setup

```bash
uv sync
cp .env.example .env   # add your LLM API key
```

## Run

```bash
uv run delay-ai ingest   # reads data/sample/emails into data/local/events.db
```

Prints the materials table built from the emails, the emails that need a person
to review them, and any failed events. Failed events are retried on the next run.

## Develop

```bash
uv run pytest
uv run ruff check .
uv run ruff format .
```

## Pilot simplifications

Shortcuts taken on purpose for v0. Each one is a candidate for after the pilot.

**Schedule**
- Read from a CSV export only, not P6, Asta or MS Project files.
- Finish-to-start dependencies only, with no lag.
- Mon–Fri working calendar with no bank holidays.
- No resource constraints (crews, cranes).
- Dates are computed from the project start; there's no progress or status date.
- An activity can start the working day after its material arrives.

**Materials**
- One material per PO.
- Built from supplier emails; there is no materials spreadsheet.

**Email**
- Read from a local `.eml` folder. Gmail and Outlook come later.
- Plain-text body only; attachments are ignored.
- A supplier is recognised by the domain of the sender's email address.
- PO numbers must look like `PO-<digits>`.
- Rules only read dates written in full with a year; the LLM resolves the rest.
- A fixed confidence threshold (0.7) decides what goes to review.
- If one item in an email fails a check, the whole email goes to review.

**Events**
- One SQLite file and a single process.
- Event status (pending/done/failed) is updated in place, so the table isn't strictly append-only.
- Failed events are retried only when the CLI runs again; there's no backoff.

**Actions**
- Emails and notifications are drafted to an outbox and never sent.
