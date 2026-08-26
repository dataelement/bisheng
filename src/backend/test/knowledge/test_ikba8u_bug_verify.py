"""Bug verification test for IKBA8U using the real permission evaluation path.

This is the "buggy" snapshot captured against ``origin/main``: a user that only
holds a space-level ``viewer`` binding (i.e. system model default with
``can_read`` relation on the space) should NOT be granted ``view_file`` on
files in that space.

The current implementation of ``FineGrainedPermissionService._permission_ids_for_relation``
returns ALL level-1 permission ids (space + folder + file columns) for any
system-model default, regardless of which resource type the binding was placed
on. Because the lineage walk stops at the matched level (``nearest_binding_wins``),
a space-level binding incorrectly grants the user ``view_file`` too, which lets
those files leak into AI Q&A retrieval via ``KnowledgeFileVisibilityService.
post_filter_visible_files``.

This test exercises the **real** ``get_effective_permission_ids_async`` against
an ``InMemoryOpenFGAClient`` to demonstrate the leak. The companion
``test_f029_view_file_resource_type_fix.py`` test will assert the corrected
behavior once the fix lands.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.knowledge.domain.models.knowledge_file import FileType
from bisheng.knowledge.domain.services.knowledge_space_service import KnowledgeSpaceService
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)

SPACE_ID = 57
USER_ID = 7
FGPS_MOD = "bisheng.permission.domain.services.fine_grained_permission_service"


def _file(item_id, *, is_dir=False, owner=999, level_path=""):
    return SimpleNamespace(
        id=item_id,
        file_type=FileType.DIR.value if is_dir else FileType.FILE.value,
        file_level_path=level_path,
        user_id=owner,
    )


@pytest.mark.asyncio
async def test_space_viewonly_leaks_view_file_for_files_in_space(mock_openfga):
    """The IKBA8U bug: space-level ``viewer`` binding must NOT confer ``view_file``
    on individual files inside the space.

    With the current (buggy) lineage walk, the only binding is on the
    knowledge_space resource, relation ``viewer`` (can_read). The function
    returns all level-1 permissions for that level-1 relation — including
    ``view_file``, ``view_folder``, ``download_file``, ``download_folder`` —
    so a file 1002 with no per-file grant is incorrectly reported as visible
    in ``post_filter_visible_files``.
    """
    # Real system-model binding (no explicit permissions list) on the space.
    space_binding = {
        "resource_type": "knowledge_space",
        "resource_id": str(SPACE_ID),
        "subject_type": "user",
        "subject_id": USER_ID,
        "relation": "viewer",
        "include_children": None,
        "model_id": "m_space_viewonly",  # any non-system model id, see below
    }
    # The system model id in production is the system-implicit default; we
    # pass a model WITHOUT explicit permissions so that the system-default
    # branch fires inside _permission_ids_for_relation.
    system_default_model = {
        "id": "m_space_viewonly",
        "name": "m_space_viewonly",
        "relation": "viewer",
        "permissions": [],
        "permissions_explicit": False,
        "is_system": True,
    }
    models = {system_default_model["id"]: system_default_model}
    bindings = [space_binding]

    await mock_openfga.write_tuples(
        writes=[
            {"object": f"knowledge_space:{SPACE_ID}", "relation": "viewer", "user": f"user:{USER_ID}"},
        ]
    )

    login_user = MagicMock()
    login_user.user_id = USER_ID
    login_user.is_admin = MagicMock(return_value=False)

    with (
        patch(f"{FGPS_MOD}.PermissionService._get_fga", return_value=mock_openfga),
        patch(
            f"{FGPS_MOD}.PermissionService.get_implicit_permission_level",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            f"{FGPS_MOD}.PermissionService.get_permission_level",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        # Resolve the EFFECTIVE permission ids for a regular file in the space.
        # The lineage walk will hit the space-level binding and currently
        # returns the full level-1 set, including view_file.
        perms_for_file = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            "knowledge_file",
            1002,
            models=models,
            bindings=bindings,
            binding_department_paths={},
            user_subject_strings={f"user:{USER_ID}"},
        )

    # This is the LEAK: a space-only viewer should not have view_file.
    assert "view_file" not in perms_for_file, (
        "IKBA8U leak: a user with only a space-level viewer binding should not "
        f"be granted view_file on individual files. Got: {sorted(perms_for_file)}"
    )


@pytest.mark.asyncio
async def test_post_filter_visible_files_drops_files_for_space_viewer(mock_openfga):
    """End-to-end reproduction through ``KnowledgeSpaceService._get_child_item_effective_permission_ids``,
    which is what the workstation chat path delegates to.

    Expected post-fix: file 1002 is dropped. Pre-fix (this test pre-fix is the
    bug snapshot): file 1002 leaks through.
    """
    # System-model default binding on the space.
    space_binding = {
        "resource_type": "knowledge_space",
        "resource_id": str(SPACE_ID),
        "subject_type": "user",
        "subject_id": USER_ID,
        "relation": "viewer",
        "include_children": None,
        "model_id": "m_space_viewonly",
    }
    system_default_model = {
        "id": "m_space_viewonly",
        "name": "m_space_viewonly",
        "relation": "viewer",
        "permissions": [],
        "permissions_explicit": False,
        "is_system": True,
    }

    # Pre-build a minimal context as KnowledgeSpaceService expects.
    context = {
        "models": {system_default_model["id"]: system_default_model},
        "bindings": [space_binding],
        "binding_index": FineGrainedPermissionService.build_binding_index([space_binding]),
        "binding_department_paths": {},
        "user_subject_strings": {f"user:{USER_ID}"},
        "membership_permission_ids": set(),
        "public_space_permission_ids": set(),
        "tuple_cache": {},
        "tuple_department_paths": {},
    }

    await mock_openfga.write_tuples(
        writes=[
            {"object": f"knowledge_space:{SPACE_ID}", "relation": "viewer", "user": f"user:{USER_ID}"},
        ]
    )

    login_user = MagicMock()
    login_user.user_id = USER_ID
    login_user.is_admin = MagicMock(return_value=False)
    svc = KnowledgeSpaceService(request=MagicMock(), login_user=login_user)

    target_file = _file(1002)
    with (
        patch(f"{FGPS_MOD}.PermissionService._get_fga", return_value=mock_openfga),
        patch(
            f"{FGPS_MOD}.PermissionService.get_implicit_permission_level",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            f"{FGPS_MOD}.PermissionService.get_permission_level",
            new_callable=AsyncMock,
            return_value=None,
        ),
    ):
        effective = await svc._get_child_item_effective_permission_ids(target_file, space_id=SPACE_ID, context=context)

    # A space-only viewer must NOT see this file as viewable.
    assert "view_file" not in effective, (
        "IKBA8U leak through _get_child_item_effective_permission_ids: "
        f"got {sorted(effective)}; expected view_file to be absent."
    )
