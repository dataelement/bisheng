"""Pure F048 action Catalog policy contracts.

覆盖 AC: AC-01, AC-02, AC-03, AC-04, AC-05, AC-06, AC-148, AC-149, AC-156
"""

from __future__ import annotations

import pytest

from bisheng.core.openfga.authorization_model_f048 import (
    DEFAULT_ACTION_CODES,
    RESOURCE_ACTION_SCOPES,
)
from bisheng.permission.domain.services.catalog_policy import (
    CatalogAction,
    action_zones,
    calculate_action_impact,
    derive_action_release,
    effective_action_codes,
)


def _action(
    code: str,
    *,
    level: int | None,
    active: bool = True,
    scopes: tuple[str, ...] | None = None,
) -> CatalogAction:
    selected_scopes = scopes if scopes is not None else tuple(sorted(RESOURCE_ACTION_SCOPES.get(code, {"workflow"})))
    return CatalogAction(
        code=code,
        name=code.replace("_", " ").title(),
        level=level,
        active=active,
        resource_types=frozenset(selected_scopes),
    )


def _complete_actions() -> tuple[CatalogAction, ...]:
    return tuple(
        _action(
            code,
            level=None,
            active=False,
            scopes=tuple(sorted(RESOURCE_ACTION_SCOPES[code])),
        )
        for code in DEFAULT_ACTION_CODES
    )


def test_catalog_requires_exactly_one_registered_row_per_action() -> None:
    actions = list(_complete_actions())
    actions.append(actions[0])
    with pytest.raises(ValueError, match="duplicate"):
        derive_action_release(actions)

    with pytest.raises(ValueError, match="complete"):
        derive_action_release(actions[:-2])

    actions[-1] = _action("view", level=1)
    with pytest.raises(ValueError, match="registered"):
        derive_action_release(actions)


def test_unassigned_inactive_and_resource_scope_are_not_effective() -> None:
    actions = list(_complete_actions())
    actions[DEFAULT_ACTION_CODES.index("edit")] = _action(
        "edit",
        level=2,
        scopes=("workflow", "dashboard"),
    )
    actions[DEFAULT_ACTION_CODES.index("delete")] = _action(
        "delete",
        level=4,
        active=False,
        scopes=("workflow",),
    )
    actions[DEFAULT_ACTION_CODES.index("use")] = _action(
        "use",
        level=None,
        active=True,
        scopes=("workflow",),
    )
    release = derive_action_release(actions)
    assert effective_action_codes(release.actions, "workflow") == ("edit",)
    assert effective_action_codes(release.actions, "dashboard") == ("edit",)
    assert effective_action_codes(release.actions, "knowledge_file") == ()


def test_action_level_is_one_to_four_or_unassigned() -> None:
    actions = list(_complete_actions())
    actions[0] = _action(actions[0].code, level=0)
    with pytest.raises(ValueError, match="level"):
        derive_action_release(actions)
    actions[0] = _action(actions[0].code, level=5)
    with pytest.raises(ValueError, match="level"):
        derive_action_release(actions)


def test_five_action_zones_are_deterministic() -> None:
    actions = list(_complete_actions())
    for level, code in enumerate(DEFAULT_ACTION_CODES[:4], start=1):
        actions[level - 1] = _action(code, level=level)
    zones = action_zones(derive_action_release(actions).actions)
    assert set(zones) == {None, 1, 2, 3, 4}
    assert [row.level for row in zones[None]] == [None] * (len(DEFAULT_ACTION_CODES) - 4)
    for level in range(1, 5):
        assert [row.level for row in zones[level]] == [level]


def test_complete_release_and_impact_recompute_all_standard_models() -> None:
    before = list(_complete_actions())
    after = list(before)
    index = DEFAULT_ACTION_CODES.index("edit")
    before[index] = _action("edit", level=2, scopes=("workflow",))
    after[index] = _action(
        "edit",
        level=3,
        scopes=("workflow", "dashboard"),
    )
    before_release = derive_action_release(before)
    after_release = derive_action_release(after)
    impact = calculate_action_impact(
        before_release,
        after_release,
        custom_model_actions={
            "custom-with-edit": frozenset({"edit", "use"}),
            "custom-without-edit": frozenset({"download"}),
        },
    )
    assert impact.changed_action_codes == ("edit",)
    assert {
        "viewer",
        "editor",
        "manager",
        "owner",
        "custom-with-edit",
    } <= set(impact.affected_model_keys)
    assert "custom-without-edit" not in impact.affected_model_keys
    assert impact.expanded_pairs == (("dashboard", "edit"),)
    assert len(impact.checksum) == 64
    assert before_release.checksum != after_release.checksum
