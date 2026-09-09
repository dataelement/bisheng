"""Every model preset is a complete ladder up to its own level.

Applying 权限管理 produced a level-3 model with level 2 entirely unticked — its
holder could manage permissions but not rename, edit or upload. A preset that
skips a level is almost certainly an omission: the level of a model is the
highest level among its actions, so a preset that reaches level 3 is claiming
everything below it as well.
"""

from __future__ import annotations

import pytest

from bisheng.permission.application.catalog_api import F048CatalogApi
from bisheng.permission.migration.f048_model_mapper import INITIAL_ACTION_LEVELS

_PRESETS = {preset["key"]: tuple(preset["action_codes"]) for preset in F048CatalogApi.PRESETS}


def _levels(action_codes) -> set[int]:
    return {INITIAL_ACTION_LEVELS[code] for code in action_codes}


@pytest.mark.parametrize("key", sorted(_PRESETS))
def test_a_preset_leaves_no_level_behind(key):
    """No gaps: reaching level N means holding every level below it."""
    levels = _levels(_PRESETS[key])
    assert levels, key
    assert levels == set(range(1, max(levels) + 1)), f"{key} skips {sorted(set(range(1, max(levels) + 1)) - levels)}"


@pytest.mark.parametrize("key", sorted(_PRESETS))
def test_a_preset_holds_every_action_of_the_levels_it_claims(key):
    """Within a level a preset takes all of it, or the checkbox count lies."""
    selected = set(_PRESETS[key])
    claimed = _levels(selected)
    top = max(claimed)
    for level in range(1, top):
        of_level = {code for code, value in INITIAL_ACTION_LEVELS.items() if value == level}
        assert of_level <= selected, f"{key} is missing {sorted(of_level - selected)} from level {level}"


def test_permission_management_reaches_level_three_through_level_two():
    codes = set(_PRESETS["permission_management"])
    assert {"rename", "edit", "create_folder", "upload_file", "move"} <= codes
    assert {"manage_permission", "share"} <= codes
    # Still short of 高级管理, which is what keeps the two presets distinct.
    assert not {"delete", "publish", "unpublish"} & codes


def test_collaborative_editing_stops_below_permission_management():
    codes = set(_PRESETS["collaborative_editing"])
    assert max(_levels(codes)) == 2
    assert codes < set(_PRESETS["permission_management"])
