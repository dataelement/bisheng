from types import SimpleNamespace

import pytest

from bisheng.permission.application.control_state import (
    RuntimeCatalogSnapshot,
    RuntimeModelSnapshot,
)
from bisheng.permission.application.runtime import F048PermissionRuntime
from bisheng.permission.domain.schemas import VerifiedPermissionTarget
from bisheng.permission.domain.services.grant_source_service import GrantModelSnapshot


@pytest.mark.asyncio
async def test_effective_direct_user_ids_by_model_filters_and_paginates():
    owner_model = GrantModelSnapshot(model_key="owner", active=True, action_codes=("manage",))
    manager_model = GrantModelSnapshot(model_key="manager", active=True, action_codes=("manage",))
    catalog = RuntimeCatalogSnapshot(
        release_id=1,
        release_key="release",
        version=1,
        checksum="c" * 64,
        store_id="store",
        model_id="model",
        model_checksum="m" * 64,
        models=(
            RuntimeModelSnapshot(snapshot=owner_model, name="Owner", kind="STANDARD", version=1),
            RuntimeModelSnapshot(snapshot=manager_model, name="Manager", kind="STANDARD", version=1),
        ),
    )
    pages = [
        (
            (
                SimpleNamespace(
                    source_id=1,
                    model_key="owner",
                    subject_type="user",
                    subject_id="11",
                    userset_relation=None,
                ),
                SimpleNamespace(
                    source_id=2,
                    model_key="manager",
                    subject_type="user_group",
                    subject_id="90",
                    userset_relation="member",
                ),
            ),
            True,
        ),
        (
            (
                SimpleNamespace(
                    source_id=3,
                    model_key="manager",
                    subject_type="user",
                    subject_id="22",
                    userset_relation=None,
                ),
                SimpleNamespace(
                    source_id=4,
                    model_key="manager",
                    subject_type="user",
                    subject_id="22",
                    userset_relation=None,
                ),
            ),
            False,
        ),
    ]

    class State:
        def __init__(self):
            self.after_ids = []

        async def current_catalog(self):
            return catalog

        async def mode_for_target(self, target):
            del target
            return SimpleNamespace(
                version=3,
                parent_type=None,
                parent_id=None,
                projection_state="CURRENT",
                mode="CUSTOM",
            )

        async def load_source_page(self, **kwargs):
            self.after_ids.append(kwargs["after_id"])
            return pages.pop(0)

    state = State()
    runtime = F048PermissionRuntime(
        client=SimpleNamespace(store_id="store", model_id="model"),
        state=state,
        marker=object(),
        decision=object(),
        projection=object(),
        sources=object(),
        owner=object(),
        grants=object(),
        modes=object(),
        explain=object(),
    )
    target = VerifiedPermissionTarget.from_business_service(
        tenant_id=7,
        resource_type="knowledge_space",
        resource_id="12",
        resource_version=3,
        context_version="ctx",
    )

    result = await runtime.list_effective_direct_user_ids_by_model(
        target=target,
        model_keys=("owner", "manager"),
    )

    assert result == {"owner": ("11",), "manager": ("22",)}
    assert state.after_ids == [0, 2]
