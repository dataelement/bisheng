"""F056 T031 / AC-37, AC-38 — the backend half of 「零新增权限点」.

The frontend half lives in
``platform/src/test/gov07NoNewPermissionPoint.test.ts``: the role editor's
list of selectable entries, its cascade rules and a new role's defaults, all
frozen as literals. That file cannot see the side a permission point is
actually *added* on.

A menu permission point exists in three places on this side, and the honest
version of AC-37 is that none of them grew a hosted-application entry:

* :class:`WebMenuResource` — the registry of menu keys a role may hold;
* ``_ROLE_UI_WORKBENCH_CHILDREN`` / ``_ROLE_UI_ADMIN_CHILDREN`` — what the login
  path treats as a second-level entry, which is what makes a key *effective*;
* ``UserMenuAccessService._PARENT_DEPENDENCIES`` — the cascade a personal menu
  grant expands through.

The last test asserts the two sides agree. That is the lockstep the AC really
rests on: a key added to the backend alone is a permission point nobody can
switch off in the UI, and one added to the frontend alone is a switch that
grants nothing — either way "the role config screen is unchanged" stops being
true, and neither side's own suite notices.
"""

from __future__ import annotations

import re
from pathlib import Path

from bisheng.approval.domain.services.user_menu_access_service import UserMenuAccessService
from bisheng.database.models.role_access import WebMenuResource
from bisheng.user.domain.services.auth import (
    _ROLE_UI_ADMIN_CHILDREN,
    _ROLE_UI_WORKBENCH_CHILDREN,
)

#: ``platform/src/pages/SystemPage/components/roleMenuSelection.ts``.
ROLE_MENU_SELECTION_TS = (
    Path(__file__).resolve().parents[3]
    / "frontend"
    / "platform"
    / "src"
    / "pages"
    / "SystemPage"
    / "components"
    / "roleMenuSelection.ts"
)

#: Names that would mean the app factory got a permission point of its own.
#: ``app`` alone is not on the list on purpose — ``apps`` (应用中心) is a legacy
#: workbench entry and predates all of this.
FACTORY_WORDS = ("hosted", "app_runtime", "deploy", "square", "publish", "factory")


def _ts_string_list(source: str, name: str) -> list[str]:
    """The string literals of a ``export const NAME = [...]`` array in a .ts file."""
    match = re.search(rf"export const {name}\s*=\s*\[(.*?)\]", source, re.S)
    assert match, f"{name} is no longer declared as an array literal in {ROLE_MENU_SELECTION_TS.name}"
    return re.findall(r'"([^"]+)"', match.group(1))


class TestPermissionPointRegistry:
    def test_web_menu_resource_holds_exactly_the_keys_it_always_held(self):
        # Frozen as literals rather than as a count: a swap keeps a count
        # honest while changing every screen that reads the registry.
        assert {member.value for member in WebMenuResource} == {
            "workstation",
            "admin",
            "build",
            "create_app",
            "knowledge",
            "create_knowledge",
            "knowledge_space",
            "model",
            "tool",
            "mcp",
            "channel",
            "evaluation",
            "dataset",
            "mark_task",
            "board",
            "subscription",
            "home",
            "linsight_task_mode",
            "apps",
            # Deprecated, kept for backward compatibility (AD-07).
            "frontend",
            "backend",
            "create_dashboard",
        }

    def test_no_menu_key_is_about_the_app_factory(self):
        """AC-35 / 决议-10: hosted applications reuse ``create_app`` and reach
        the build page through ``build``. A key of their own would also be the
        one thing that makes 「升级前后数量不变」 false."""
        offenders = [member.value for member in WebMenuResource if any(word in member.value for word in FACTORY_WORDS)]
        assert offenders == []

    def test_the_effective_menu_sets_did_not_grow(self):
        assert _ROLE_UI_WORKBENCH_CHILDREN == frozenset(
            {"home", "linsight_task_mode", "apps", "subscription", "knowledge_space"}
        )
        assert _ROLE_UI_ADMIN_CHILDREN == frozenset(
            {
                "board",
                "model",
                "log",
                "knowledge",
                "create_knowledge",
                "build",
                "create_app",
                "evaluation",
                "dataset",
                "mark_task",
            }
        )

    def test_create_app_still_hangs_off_build_and_nothing_new_was_added(self):
        """AC-35's cascade: switching 「构建」 off has to take 「新建应用」 with it,
        on the personal-grant path as well as in the role editor."""
        assert UserMenuAccessService._PARENT_DEPENDENCIES["create_app"] == ("admin", "build")
        assert [
            key for key in UserMenuAccessService._PARENT_DEPENDENCIES if any(word in key for word in FACTORY_WORDS)
        ] == []
        assert UserMenuAccessService.expand_menu_keys_with_dependencies(["create_app"]) == [
            "admin",
            "build",
            "create_app",
        ]


class TestBothSidesAgree:
    """The inventory is one list living in two languages — check it reads the same."""

    def test_the_role_editor_offers_exactly_the_effective_second_level_keys(self):
        source = ROLE_MENU_SELECTION_TS.read_text(encoding="utf-8")

        workbench = set(_ts_string_list(source, "WORKBENCH_CHILD_MENUS"))
        admin = set(_ts_string_list(source, "ADMIN_CHILD_MENUS"))
        task_mode = re.search(r'export const TASK_MODE_MENU_ID\s*=\s*"([^"]+)"', source)
        assert task_mode

        assert workbench | {task_mode.group(1)} == set(_ROLE_UI_WORKBENCH_CHILDREN)
        assert admin == set(_ROLE_UI_ADMIN_CHILDREN)
