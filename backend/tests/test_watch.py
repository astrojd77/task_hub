"""Watch scoring and sectioning — the milestone is that ranking is explainable."""

from __future__ import annotations

from datetime import date, timedelta

from app.models.task import Task
from app.services.watch import DEFAULT_WEIGHTS, WatchWeights, score_task, sections_for

TODAY = date(2026, 7, 26)


def task(**overrides) -> Task:
    base = {
        "id": overrides.pop("id", "t1"),
        "title": "t",
        "status": "todo",
        "priority": "medium",
        "criticality": None,
        "impact_size": None,
        "due_date": None,
        "source_provider": "csv",
        "source_ref": "r",
        "labels": [],
        "external_refs": {},
    }
    return Task(**(base | overrides))


# -- score ---------------------------------------------------------------


def test_a_bare_task_scores_zero():
    assert score_task(task(), TODAY).score == 0


def test_criticality_and_impact_add_up():
    s = score_task(task(criticality="critical", impact_size="xl"), TODAY)
    assert s.score == 5 + 4


def test_overdue_beats_due_soon():
    overdue = score_task(task(due_date=TODAY - timedelta(days=1)), TODAY).score
    two_days = score_task(task(due_date=TODAY + timedelta(days=2)), TODAY).score
    a_week = score_task(task(due_date=TODAY + timedelta(days=7)), TODAY).score
    far = score_task(task(due_date=TODAY + timedelta(days=30)), TODAY).score

    assert overdue == 5
    assert two_days == 3
    assert a_week == 1
    assert far == 0
    assert overdue > two_days > a_week > far


def test_due_today_counts_as_imminent_not_overdue():
    s = score_task(task(due_date=TODAY), TODAY)
    assert s.score == DEFAULT_WEIGHTS.due_within_2_days
    assert "overdue" not in s.sections


def test_blocked_adds_its_weight():
    assert score_task(task(status="blocked"), TODAY).score == 2


def test_the_milestone_case_tops_the_list():
    """High criticality + xl impact + overdue should outrank everything else."""
    worst = score_task(
        task(criticality="critical", impact_size="xl", due_date=TODAY - timedelta(days=3)),
        TODAY,
    )
    ordinary = score_task(task(criticality="medium", impact_size="s"), TODAY)

    assert worst.score == 5 + 4 + 5
    assert worst.score > ordinary.score


def test_the_score_explains_itself():
    s = score_task(
        task(
            criticality="high",
            impact_size="l",
            due_date=TODAY - timedelta(days=2),
            status="blocked",
        ),
        TODAY,
    )
    joined = " | ".join(s.reasons)

    assert "criticality high +3" in joined
    assert "impact l +3" in joined
    assert "overdue by 2d +5" in joined
    assert "blocked +2" in joined
    # The reasons must actually account for the number shown.
    assert s.score == 3 + 3 + 5 + 2


def test_turning_a_weight_changes_the_ranking():
    """The whole point of a visible weight table."""
    impact_heavy = task(criticality="low", impact_size="xl")
    crit_heavy = task(criticality="critical", impact_size="xs")

    default_wins = score_task(crit_heavy, TODAY).score > score_task(impact_heavy, TODAY).score
    assert default_wins

    # Turn one knob: make blast radius dominate.
    tuned = WatchWeights(impact={"xs": 0, "s": 1, "m": 2, "l": 6, "xl": 10})
    assert score_task(impact_heavy, TODAY, tuned).score > score_task(crit_heavy, TODAY, tuned).score


def test_unset_criticality_and_impact_contribute_nothing():
    assert score_task(task(criticality=None, impact_size=None), TODAY).score == 0


# -- sections ------------------------------------------------------------


def test_overdue_and_due_soon_are_mutually_exclusive():
    overdue = sections_for(task(due_date=TODAY - timedelta(days=1)), TODAY)
    soon = sections_for(task(due_date=TODAY + timedelta(days=3)), TODAY)

    assert "overdue" in overdue and "due_soon" not in overdue
    assert "due_soon" in soon and "overdue" not in soon


def test_a_task_can_be_in_several_sections():
    s = sections_for(
        task(criticality="critical", status="blocked", due_date=TODAY - timedelta(days=1)),
        TODAY,
    )
    assert set(s) == {"overdue", "keep_an_eye_on", "blocked"}


def test_keep_an_eye_on_ignores_dates():
    assert "keep_an_eye_on" in sections_for(task(criticality="high"), TODAY)
    assert "keep_an_eye_on" in sections_for(task(impact_size="xl"), TODAY)
    assert "keep_an_eye_on" not in sections_for(task(criticality="medium", impact_size="m"), TODAY)


def test_far_future_work_is_in_no_date_section():
    assert sections_for(task(due_date=TODAY + timedelta(days=90)), TODAY) == []
