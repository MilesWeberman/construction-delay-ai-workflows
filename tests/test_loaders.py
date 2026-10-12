from datetime import date

import pytest

from delay_ai.loaders import load_contacts, load_project, load_schedule


def test_load_project(sample_dir):
    project = load_project(sample_dir / "project.json")
    assert project.start_date == date(2026, 11, 2)


def test_load_schedule(sample_dir):
    activities = load_schedule(sample_dir / "schedule.csv")
    by_id = {a.id: a for a in activities}
    assert len(activities) == 20
    assert by_id["A01"].predecessors == []
    assert by_id["A11"].predecessors == ["A08", "A09", "A10"]
    assert by_id["A11"].duration_days == 0


def test_load_schedule_rejects_unknown_predecessor(tmp_path):
    path = tmp_path / "schedule.csv"
    path.write_text("activity_id,name,trade,duration_days,predecessors\nA01,Start,Prelims,5,A99\n")
    with pytest.raises(ValueError, match="A99"):
        load_schedule(path)


def test_load_contacts(sample_dir):
    contacts = load_contacts(sample_dir / "contacts.csv")
    by_name = {c.name: c for c in contacts}
    assert by_name["Sarah Okafor"].activity_ids == []
    assert by_name["Dave Mitchell"].activity_ids == ["A05", "A06", "A07"]
