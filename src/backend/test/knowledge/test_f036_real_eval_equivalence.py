"""F036-(1) real-eval equivalence: optimized fast-path vs full per-item oracle.

覆盖 AC: AC-01 / AC-02 / AC-03 (spec 2.1). 与 test_f036_child_fastpath_equivalence 的区别:
那个 mock 掉评估函数,只验分发;本测试用真实 `FineGrainedPermissionService.get_effective_permission_ids_async`
跑在 InMemoryOpenFGA + 真实 binding/model 解析之上,对**同一后端**比较
`_filter_visible_child_items`(优化)与 `_filter_visible_child_items_reference`(完整逐项 oracle),
因此 fast == reference 真实证明"快速通道 == 完整逐项评估".

重点场景(非 admin user:7,空间绑定只授 view_space -- 即"有空间 view 不等于有文件 view"):
  - 文件被单独授权(view_file binding) -> 可见
  - 文件无授权,非 owner            -> 仅继承 view_space -> 不可见(被单独授权才严于空间)
  - 文件 owner=当前用户             -> 可见(裸 owner 授权)
  - 文件夹被单独授权(view_folder)  -> 可见
  - 文件夹无授权                    -> 不可见
"""

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


def _model(model_id, relation, permissions):
    return {
        "id": model_id,
        "name": model_id,
        "relation": relation,
        "permissions": permissions,
        "permissions_explicit": True,
        "is_system": False,
    }


def _binding(resource_type, resource_id, relation, model_id, subject_id=USER_ID):
    return {
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "subject_type": "user",
        "subject_id": subject_id,
        "relation": relation,
        "include_children": None,
        "model_id": model_id,
    }


def _file(item_id, *, is_dir=False, owner=999, level_path=""):
    return SimpleNamespace(
        id=item_id,
        file_type=FileType.DIR.value if is_dir else FileType.FILE.value,
        file_level_path=level_path,
        user_id=owner,
    )


def _build_context():
    models = {
        "m_space_viewonly": _model("m_space_viewonly", "viewer", ["view_space"]),
        "m_file_view": _model("m_file_view", "viewer", ["view_file"]),
        "m_folder_view": _model("m_folder_view", "viewer", ["view_folder", "view_file"]),
    }
    bindings = [
        _binding("knowledge_space", SPACE_ID, "viewer", "m_space_viewonly"),
        _binding("knowledge_file", 1001, "viewer", "m_file_view"),
        _binding("folder", 300, "viewer", "m_folder_view"),
    ]
    return {
        "models": models,
        "bindings": bindings,
        "binding_index": FineGrainedPermissionService.build_binding_index(bindings),
        "binding_department_paths": {},
        "user_subject_strings": {f"user:{USER_ID}"},
        "membership_permission_ids": set(),
        "public_space_permission_ids": set(),
        "tuple_cache": {},
        "tuple_department_paths": {},
    }


async def _setup_tuples(fga):
    await fga.write_tuples(
        writes=[
            # space grant: view_space only (the "space view != file view" case)
            {"object": f"knowledge_space:{SPACE_ID}", "relation": "viewer", "user": f"user:{USER_ID}"},
            # individually granted file -> view_file
            {"object": "knowledge_file:1001", "relation": "viewer", "user": f"user:{USER_ID}"},
            # individually granted folder -> view_folder
            {"object": "folder:300", "relation": "viewer", "user": f"user:{USER_ID}"},
            # owner tuple for file 1003 (naked owner grant: no binding)
            {"object": "knowledge_file:1003", "relation": "owner", "user": f"user:{USER_ID}"},
        ]
    )


@pytest.mark.asyncio
async def test_fast_equals_reference_real_eval(mock_openfga):
    await _setup_tuples(mock_openfga)
    login_user = MagicMock()
    login_user.user_id = USER_ID
    login_user.is_admin = MagicMock(return_value=False)
    svc = KnowledgeSpaceService(request=MagicMock(), login_user=login_user)

    items = [
        _file(1001),  # individually granted file -> visible
        _file(1002),  # no grant, not owner -> only view_space -> hidden
        _file(1003, owner=USER_ID),  # owner -> visible
        _file(300, is_dir=True),  # individually granted folder -> visible
        _file(301, is_dir=True),  # no grant folder -> hidden
    ]

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
        # fresh context per path so request-level tuple_cache doesn't leak between them
        fast = await svc._filter_visible_child_items(items, space_id=SPACE_ID, context=_build_context())
        reference = await svc._filter_visible_child_items_reference(items, space_id=SPACE_ID, context=_build_context())

    fast_ids = sorted(i.id for i in fast)
    ref_ids = sorted(i.id for i in reference)
    assert fast_ids == ref_ids, f"fast={fast_ids} reference={ref_ids}"
    # explicit truth: granted file 1001 + owner 1003 + granted folder 300
    assert fast_ids == [300, 1001, 1003]
