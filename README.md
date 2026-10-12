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
