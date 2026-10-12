# Construction Delay AI Workflows

Pilot: reduce project delays caused by **late material deliveries**.

Delivery news (email, chat) → events → update affected schedule activities →
re-plan the schedule to minimise project delay → human review in a UI.

## Setup

```bash
uv sync
cp .env.example .env   # add your LLM API key
```

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

**Events**
- One SQLite file and a single process.
- Event status (pending/done/failed) is updated in place, so the table isn't strictly append-only.
- Failed events aren't retried automatically.

**Actions**
- Emails and notifications are drafted to an outbox and never sent.
