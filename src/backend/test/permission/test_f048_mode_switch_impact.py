"""Switching back to INHERIT must report the grants it is about to drop.

The confirmation counted only `snapshot_sources`, which the CUSTOM direction
fills when it copies inherited members down. Switching the other way keeps just
the protected rows and discards every ordinary local grant — yet reported
"影响 0 个授权对象" while it was about to remove people.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class _Source:
    active: bool
    protected: bool


@dataclass(frozen=True)
class _Grant:
    sources: tuple[_Source, ...]


def _discarded(local_grants: tuple[_Grant, ...]) -> tuple[_Source, ...]:
    """The selection `create_draft` makes for the INHERIT direction."""

    return tuple(
        source for grant in local_grants for source in grant.sources if source.active and not source.protected
    )


def test_ordinary_local_grants_are_counted() -> None:
    grants = (
        _Grant((_Source(active=True, protected=True),)),  # the creator stays
        _Grant((_Source(active=True, protected=False), _Source(active=True, protected=False))),
    )
    assert len(_discarded(grants)) == 2


def test_the_protected_creator_is_not_counted() -> None:
    grants = (_Grant((_Source(active=True, protected=True),)),)
    assert _discarded(grants) == ()


def test_inactive_sources_are_not_counted() -> None:
    grants = (_Grant((_Source(active=False, protected=False),)),)
    assert _discarded(grants) == ()


def test_a_resource_with_only_inherited_members_reports_nothing_to_drop() -> None:
    assert _discarded(()) == ()
