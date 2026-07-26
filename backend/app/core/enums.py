"""Canonical enums.

These are the *only* vocabularies core knows about. Every adapter is responsible
for translating its platform's native values into these, and back out again on
push. Native values must never leak past an adapter boundary.

The three prioritization axes are deliberately independent:

* ``Priority``    — urgency. What do I do first?
* ``Criticality`` — severity. How bad is it if this fails or slips?
* ``ImpactSize``  — blast radius. How much / how many is affected?

Do not collapse them into a single score at the model layer. The Watch view
(phase 3) combines them into a score at *read* time, which is where it belongs.
"""

from __future__ import annotations

from enum import StrEnum


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class Criticality(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ImpactSize(StrEnum):
    XS = "xs"
    S = "s"
    M = "m"
    L = "l"
    XL = "xl"


#: Serialised for the frontend so the review UI never hardcodes option lists.
ENUM_CATALOG: dict[str, list[str]] = {
    "status": [e.value for e in TaskStatus],
    "priority": [e.value for e in Priority],
    "criticality": [e.value for e in Criticality],
    "impact_size": [e.value for e in ImpactSize],
}
