"""Evaluation case format and coverage (AC-104)."""

from pathlib import Path

from memory_eval.runner import load_cases

CASES = Path(__file__).resolve().parents[1] / "cases"
REQUIRED_ACS = [
    "AC-13", "AC-15", "AC-17", "AC-18", "AC-19", "AC-20", "AC-29", "AC-30", "AC-31", "AC-32", "AC-33",
    "AC-34", "AC-35", "AC-36", "AC-46", "AC-47", "AC-48", "AC-49", "AC-63", "AC-64", "AC-65",
]  # fmt: skip


def test_cases_are_valid():
    cases = load_cases(CASES)
    assert cases
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))
    for c in cases:
        assert c.acs and all(a.startswith("AC-") for a in c.acs), c.id
        assert c.question.user.strip(), c.id
        assert c.rules, c.id
        assert set(c.rules) <= {"must_contain_any", "must_contain_all", "must_not_contain", "regex"}, c.id


def test_every_required_ac_has_two_cases():
    cases = load_cases(CASES)
    for ac in REQUIRED_ACS:
        assert sum(ac in c.acs for c in cases) >= 2, ac
