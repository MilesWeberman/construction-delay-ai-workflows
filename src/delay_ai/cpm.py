"""Critical path method on a working-day calendar (Mon-Fri, no bank holidays in v0).

Times are working-day offsets from the project start: an activity with
early_start=0 and duration 10 occupies days 0-9 and has early_finish=10.
"""

from datetime import date, timedelta
from graphlib import CycleError, TopologicalSorter

from pydantic import BaseModel

from delay_ai.models import Activity


def add_working_days(start: date, days: int) -> date:
    current = start
    while days > 0:
        current += timedelta(days=1)
        if current.weekday() < 5:
            days -= 1
    return current


def working_days_between(start: date, end: date) -> int:
    """Number of working days from start to end (negative if end is earlier)."""
    sign = 1 if end >= start else -1
    low, high = sorted((start, end))
    days = sum(1 for i in range(1, (high - low).days + 1) if (low + timedelta(i)).weekday() < 5)
    return sign * days


class ScheduledActivity(BaseModel):
    id: str
    early_start: int
    early_finish: int
    late_start: int
    late_finish: int

    @property
    def total_float(self) -> int:
        return self.late_start - self.early_start

    @property
    def is_critical(self) -> bool:
        return self.total_float == 0


class Schedule(BaseModel):
    start_date: date
    duration_days: int
    activities: dict[str, ScheduledActivity]

    @property
    def finish_date(self) -> date:
        return add_working_days(self.start_date, self.duration_days)

    def start_of(self, activity_id: str) -> date:
        return add_working_days(self.start_date, self.activities[activity_id].early_start)

    def end_of(self, activity_id: str) -> date:
        """The last working day of the activity."""
        a = self.activities[activity_id]
        return add_working_days(self.start_date, max(a.early_finish - 1, a.early_start))

    def critical_path(self) -> list[str]:
        return [a.id for a in self.activities.values() if a.is_critical]


def compute_schedule(
    activities: list[Activity],
    start_date: date,
    earliest_start: dict[str, int] | None = None,
) -> Schedule:
    """Forward and backward pass. earliest_start holds extra constraints, e.g. material arrival."""
    earliest_start = earliest_start or {}
    by_id = {a.id: a for a in activities}
    try:
        order = list(TopologicalSorter({a.id: a.predecessors for a in activities}).static_order())
    except CycleError as e:
        raise ValueError(f"Schedule has a dependency cycle: {e.args[1]}") from e

    early_start, early_finish = {}, {}
    for activity_id in order:
        activity = by_id[activity_id]
        early_start[activity_id] = max(
            [early_finish[p] for p in activity.predecessors] + [earliest_start.get(activity_id, 0)]
        )
        early_finish[activity_id] = early_start[activity_id] + activity.duration_days
    duration = max(early_finish.values(), default=0)

    successors: dict[str, list[str]] = {a.id: [] for a in activities}
    for activity in activities:
        for predecessor in activity.predecessors:
            successors[predecessor].append(activity.id)

    late_start, late_finish = {}, {}
    for activity_id in reversed(order):
        late_finish[activity_id] = min(
            (late_start[s] for s in successors[activity_id]), default=duration
        )
        late_start[activity_id] = late_finish[activity_id] - by_id[activity_id].duration_days

    return Schedule(
        start_date=start_date,
        duration_days=duration,
        activities={
            a.id: ScheduledActivity(
                id=a.id,
                early_start=early_start[a.id],
                early_finish=early_finish[a.id],
                late_start=late_start[a.id],
                late_finish=late_finish[a.id],
            )
            for a in activities
        },
    )
