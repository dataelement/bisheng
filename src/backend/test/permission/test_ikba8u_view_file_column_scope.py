"""Regression coverage for IKBA8U column-scoped permission defaults.

A space-level ``viewer`` binding must NOT grant ``view_file`` on individual
files in the space; a folder-level ``viewer`` binding must still unlock the
files in that folder (the transitive grant the F036 listing UI relies on);
a file-level ``viewer`` binding must only grant the file column's level-1
permissions. Before the fix, ``FineGrainedPermissionService._permission_ids_for_relation``
called ``default_permission_ids_for_relation`` for any system-model default,
which flattens every level-1 permission across all three columns --
collapsing the three columns into one and leaking ``view_file`` for every
file in any space the user could browse.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bisheng.permission.domain.knowledge_space_permission_template import (
    column_permission_ids_for_relation,
    default_permission_ids_for_relation,
)
from bisheng.permission.domain.services.fine_grained_permission_service import (
    FineGrainedPermissionService,
)

# ---------------------------------------------------------------------------
# Direct helper tests
# ---------------------------------------------------------------------------


def test_column_scoped_knowledge_space_viewer_grants_only_view_space():
    """A space-level ``viewer`` binding returns ``view_space`` only.

    The space column at level 1 has just ``view_space``; the helper must not
    also surface ``view_folder`` / ``view_file`` / ``download_folder`` /
    ``download_file`` from the other columns.
    """
    result = column_permission_ids_for_relation("knowledge_space", "viewer")
    assert result == {"view_space"}


def test_column_scoped_folder_viewer_grants_view_folder_and_view_file():
    """A folder-level ``viewer`` binding unlocks the folder and its files.

    The folder column's own level-1 ids (``view_folder``, ``download_folder``)
    plus the file column's level-1 ids transitively (``view_file``,
    ``download_file``). Without the transitive step the F036 listing UI
    would hide the files in any folder the user could browse.
    """
    result = column_permission_ids_for_relation("folder", "viewer")
    assert result == {"view_folder", "download_folder", "view_file", "download_file"}


def test_column_scoped_knowledge_file_viewer_grants_only_file_column():
    """A file-level ``viewer`` binding grants only the file column's level-1
    permissions. The space and folder columns are not surfaced.
    """
    result = column_permission_ids_for_relation("knowledge_file", "viewer")
    assert result == {"view_file", "download_file"}


def test_column_scoped_can_edit_includes_higher_levels_within_column():
    """An ``editor`` (``can_edit``) relation on a folder must include
    ``can_read`` ids as well, but only within the matching column plus the
    transitive file column.
    """
    result = column_permission_ids_for_relation("folder", "editor")
    # can_read ids in folder column + can_edit ids in folder column +
    # transitive file column level-1 ids.
    assert result == {
        "view_folder",
        "download_folder",
        "create_folder",
        "rename_folder",
        "move_folder",
        "view_file",
        "download_file",
    }


def test_default_permission_ids_for_relation_unchanged():
    """Sanity: the legacy ``default_permission_ids_for_relation`` (which
    callers like ``_public_space_viewer_permission_ids`` still rely on for
    whole-space public access) is unchanged -- it still returns every
    level-1 permission across all three columns.
    """
    result = default_permission_ids_for_relation("viewer")
    # Order-independent; this is the existing behavior the F036 public-space
    # path depends on.
    assert result == {"view_space", "view_folder", "view_file", "download_folder", "download_file"}


def test_column_scoped_unknown_object_type_returns_empty():
    """Unknown object types fall through to an empty set rather than
    accidentally returning the legacy cross-column defaults.
    """
    assert column_permission_ids_for_relation("unknown", "viewer") == set()


# ---------------------------------------------------------------------------
# Real lineage-walk tests (via the FineGrainedPermissionService)
# ---------------------------------------------------------------------------

FGPS_MOD = "bisheng.permission.domain.services.fine_grained_permission_service"
USER_ID = 7
SPACE_ID = 100
FILE_ID = 200
FOLDER_ID = 300


def _system_default_model(relation: str) -> dict:
    """A relation model that has no explicit permissions and relies on the
    built-in system defaults (the production code path that triggered IKBA8U).
    """
    return {
        "id": f"m_system_{relation}",
        "name": f"m_system_{relation}",
        "relation": relation,
        "permissions": [],
        "permissions_explicit": False,
        "is_system": True,
    }


def _binding(resource_type: str, resource_id: int, relation: str, model_id: str) -> dict:
    return {
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "subject_type": "user",
        "subject_id": USER_ID,
        "relation": relation,
        "include_children": None,
        "model_id": model_id,
    }


@pytest.mark.asyncio
async def test_space_viewer_does_not_grant_view_file_for_files_in_space(mock_openfga):
    """End-to-end: a user with only a space-level ``viewer`` (system default)
    binding on ``knowledge_space:100`` must NOT have ``view_file`` when the
    QA retrieval filter asks "is this file visible to me?" for a file inside
    the space.
    """
    model = _system_default_model("viewer")
    models = {model["id"]: model}
    bindings = [_binding("knowledge_space", SPACE_ID, "viewer", model["id"])]
    await mock_openfga.write_tuples(
        writes=[{"object": f"knowledge_space:{SPACE_ID}", "relation": "viewer", "user": f"user:{USER_ID}"}]
    )

    login_user = MagicMock()
    login_user.user_id = USER_ID
    login_user.is_admin = MagicMock(return_value=False)

    lineage = [("knowledge_file", str(FILE_ID)), ("knowledge_space", str(SPACE_ID))]
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
        perms = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            "knowledge_file",
            FILE_ID,
            models=models,
            bindings=bindings,
            binding_department_paths={},
            user_subject_strings={f"user:{USER_ID}"},
            lineage=lineage,
        )

    assert "view_file" not in perms, (
        "IKBA8U regression: a space-level viewer binding must not grant "
        f"view_file on individual files in the space. Got: {sorted(perms)}"
    )
    # The space-level grant should still surface view_space so the user can
    # browse the space.
    assert "view_space" in perms


@pytest.mark.asyncio
async def test_folder_viewer_grants_view_file_transitively(mock_openfga):
    """A folder-level ``viewer`` binding must still grant ``view_file`` for
    files in that folder (the F036 listing UI semantics). Without the
    transitive step, the lineage walk would short-circuit at the folder
    level and return only ``view_folder`` -- the file inside the folder
    would then look inaccessible even though the user can browse its
    containing folder.
    """
    model = _system_default_model("viewer")
    models = {model["id"]: model}
    bindings = [_binding("folder", FOLDER_ID, "viewer", model["id"])]
    await mock_openfga.write_tuples(
        writes=[{"object": f"folder:{FOLDER_ID}", "relation": "viewer", "user": f"user:{USER_ID}"}]
    )

    login_user = MagicMock()
    login_user.user_id = USER_ID
    login_user.is_admin = MagicMock(return_value=False)

    lineage = [("knowledge_file", str(FILE_ID)), ("folder", str(FOLDER_ID)), ("knowledge_space", str(SPACE_ID))]
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
        perms = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            "knowledge_file",
            FILE_ID,
            models=models,
            bindings=bindings,
            binding_department_paths={},
            user_subject_strings={f"user:{USER_ID}"},
            lineage=lineage,
        )

    assert "view_file" in perms, (
        "F036 transitive grant lost: a folder-level viewer binding must "
        f"unlock the files in the folder. Got: {sorted(perms)}"
    )
    assert "view_folder" in perms


@pytest.mark.asyncio
async def test_file_viewer_grants_only_file_column(mock_openfga):
    """A file-level ``viewer`` binding grants ``view_file`` and
    ``download_file`` only -- the space/folder columns must not surface.
    """
    model = _system_default_model("viewer")
    models = {model["id"]: model}
    bindings = [_binding("knowledge_file", FILE_ID, "viewer", model["id"])]
    await mock_openfga.write_tuples(
        writes=[{"object": f"knowledge_file:{FILE_ID}", "relation": "viewer", "user": f"user:{USER_ID}"}]
    )

    login_user = MagicMock()
    login_user.user_id = USER_ID
    login_user.is_admin = MagicMock(return_value=False)

    lineage = [("knowledge_file", str(FILE_ID)), ("knowledge_space", str(SPACE_ID))]
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
        perms = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            "knowledge_file",
            FILE_ID,
            models=models,
            bindings=bindings,
            binding_department_paths={},
            user_subject_strings={f"user:{USER_ID}"},
            lineage=lineage,
        )

    assert "view_file" in perms
    assert "download_file" in perms
    # Space/folder columns must not surface.
    assert "view_space" not in perms
    assert "view_folder" not in perms
    assert "download_folder" not in perms


@pytest.mark.asyncio
async def test_explicit_model_permissions_unaffected_by_fix(mock_openfga):
    """Explicit relation-model ``permissions`` lists must continue to be
    authoritative -- the fix only changes the system-model default path.
    """
    explicit_model = {
        "id": "m_explicit",
        "name": "m_explicit",
        "relation": "viewer",
        "permissions": ["view_folder", "view_file"],
        "permissions_explicit": True,
        "is_system": False,
    }
    models = {explicit_model["id"]: explicit_model}
    bindings = [_binding("knowledge_space", SPACE_ID, "viewer", explicit_model["id"])]
    await mock_openfga.write_tuples(
        writes=[{"object": f"knowledge_space:{SPACE_ID}", "relation": "viewer", "user": f"user:{USER_ID}"}]
    )

    login_user = MagicMock()
    login_user.user_id = USER_ID
    login_user.is_admin = MagicMock(return_value=False)

    lineage = [("knowledge_file", str(FILE_ID)), ("knowledge_space", str(SPACE_ID))]
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
        perms = await FineGrainedPermissionService.get_effective_permission_ids_async(
            login_user,
            "knowledge_file",
            FILE_ID,
            models=models,
            bindings=bindings,
            binding_department_paths={},
            user_subject_strings={f"user:{USER_ID}"},
            lineage=lineage,
        )

    assert perms == {"view_folder", "view_file"}
