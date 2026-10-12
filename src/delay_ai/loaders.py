"""Load project, schedule and contacts from files."""

import csv
import json
from pathlib import Path

from delay_ai.models import Activity, Contact, Project


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def load_project(path: Path) -> Project:
    return Project.model_validate(json.loads(path.read_text()))


def load_schedule(path: Path) -> list[Activity]:
    """Read a schedule CSV export and check every predecessor exists."""
    with path.open(newline="") as f:
        activities = [
            Activity(
                id=row["activity_id"],
                name=row["name"],
                trade=row["trade"],
                duration_days=int(row["duration_days"]),
                predecessors=_split(row["predecessors"]),
            )
            for row in csv.DictReader(f)
        ]

    ids = {a.id for a in activities}
    for activity in activities:
        unknown = set(activity.predecessors) - ids
        if unknown:
            raise ValueError(f"{activity.id} has unknown predecessors: {sorted(unknown)}")
    return activities


def load_contacts(path: Path) -> list[Contact]:
    with path.open(newline="") as f:
        return [
            Contact(
                name=row["name"],
                role=row["role"],
                company=row["company"],
                email=row["email"],
                activity_ids=_split(row["activity_ids"]),
            )
            for row in csv.DictReader(f)
        ]
