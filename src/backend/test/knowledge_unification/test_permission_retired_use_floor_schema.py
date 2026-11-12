"""T965: explicit retired-use floor facts, without issuance or publication."""

from dataclasses import replace

import pytest
import sqlalchemy as sa
from pydantic import ValidationError

from bisheng.permission.domain.models import PermissionModel
from bisheng.permission.domain.schemas import CatalogChangeRequest
from bisheng.permission.domain.services import model_policy as policy
from bisheng.permission.migration.f048_model_mapper import build_initial_action_release
from test.knowledge_unification.test_perm_control_snapshot import seed
from test.knowledge_unification.test_perm_control_snapshot import session_factory as session_factory


def derive(*, floor=None, types=("tool",), visibility=3, actions=("download",), key="controlled", **kwargs):
    selected = policy.CustomModelSelection(
        key,
        "Controlled",
        actions,
        visibility_only_resource_types=types,
        visibility_level=visibility,
        retired_use_level_floor=floor,
        **kwargs,
    )
    release = policy.derive_permission_models(build_initial_action_release(), custom_models=(selected,))
    return next(model for model in release.models if model.model_key == key)


def test_default_none_keeps_ordinary_payload_checksum_and_standard_levels_exact():
    release = policy.derive_permission_models(
        build_initial_action_release(),
        custom_models=(policy.CustomModelSelection("ordinary", "Ordinary", ("download",)),),
    )
    assert release.checksum == "6c0df18f320a4ced9f6ab75d84097171891f38867bd6142cd1750b8d7092c83d"
    assert {model.model_key: model.derived_level for model in release.models if model.kind == "STANDARD"} == {
        "viewer": 1,
        "editor": 2,
        "manager": 3,
        "owner": 4,
    }
    assert all(model.retired_use_level_floor is None for model in release.models)
    assert all("retired_use_level_floor" not in policy._model_payload(model) for model in release.models)
    assert derive().derived_level == 1
    assert derive().visibility_level == 3


@pytest.mark.parametrize("floor", [1, 2, 3, 4])
def test_independent_floor_preserves_tier_without_adding_actions_or_visibility_types(floor):
    model = derive(floor=floor, visibility=floor)
    assert model.retired_use_level_floor == floor and model.derived_level == floor
    assert model.action_codes == model.selected_action_codes == ("download",)
    assert model.visibility_only_resource_types == ("tool",) and model.visibility_level == floor
    assert policy._model_payload(model)["retired_use_level_floor"] == floor


def test_concrete_action_above_floor_still_derives_its_original_tier():
    model = derive(floor=2, visibility=2, actions=("delete",))
    assert model.derived_level == 4 and model.action_codes == ("delete",)


@pytest.mark.parametrize("floor", [True, False, 0, -1, 5, 1.0, "3", (), []])
def test_floor_requires_native_nonbool_tier(floor):
    with pytest.raises((TypeError, ValueError)):
        derive(floor=floor)


@pytest.mark.parametrize(
    "types,visibility",
    [
        ((), None),
        ((), 3),
        (("tool",), None),
        (("tool",), 1),
        (("tool",), True),
        (("tool", "tool"), 3),
        (("unknown",), 3),
    ],
)
def test_floor_requires_valid_matching_visibility_provenance(types, visibility):
    with pytest.raises((TypeError, ValueError)):
        derive(floor=3, types=types, visibility=visibility)


def test_standard_and_empty_model_rules_are_not_a_floor_override_port():
    with pytest.raises(ValueError):
        derive(floor=3, key="viewer")
    viewer = policy.derive_permission_models(build_initial_action_release()).models[0]
    with pytest.raises(ValueError):
        policy.validate_standard_model_update(viewer, replace(viewer, retired_use_level_floor=1))
    with pytest.raises(ValueError):
        derive(floor=3, types=(), visibility=None, actions=())
    with pytest.raises(ValueError):
        derive(floor=3, allow_same_level=True)


def test_floor_is_a_distinct_hash_bound_fact_even_when_the_effective_tier_is_equal():
    ordinary = derive(actions=("delete",))
    controlled = derive(floor=3, actions=("delete",))
    assert ordinary.derived_level == controlled.derived_level == 4
    assert policy._model_payload(ordinary) | {"retired_use_level_floor": 3} == policy._model_payload(controlled)
    actions = build_initial_action_release()

    def release(floor):
        return policy.derive_permission_models(
            actions,
            custom_models=(
                policy.CustomModelSelection(
                    "controlled",
                    "Controlled",
                    ("delete",),
                    visibility_only_resource_types=("tool",),
                    visibility_level=3,
                    retired_use_level_floor=floor,
                ),
            ),
        )

    assert release(None).checksum != release(3).checksum


@pytest.mark.parametrize("kind", ["CREATE_MODEL", "UPDATE_MODEL"])
def test_http_does_not_issue_or_edit_retired_use_floor(kind):
    with pytest.raises(ValidationError):
        CatalogChangeRequest.model_validate(
            {
                "type": kind,
                "model_key": "controlled",
                "name": "Controlled",
                "action_codes": ["download"],
                "retired_use_level_floor": 3,
            }
        )


async def test_native_nullable_storage_roundtrip_is_private_and_preserves_original_provenance(session_factory):
    column = PermissionModel.__table__.c.retired_use_level_floor
    assert isinstance(column.type, sa.Integer) and column.nullable
    assert column.default is None and column.server_default is None
    release_id, _, _ = await seed(session_factory)
    async with session_factory() as session:
        old = await session.get(PermissionModel, 1)
        assert old.retired_use_level_floor is None
        row = PermissionModel(
            catalog_release_id=release_id,
            model_key="controlled",
            name="Controlled",
            normalized_name="controlled",
            kind="CUSTOM",
            derived_level=3,
            visibility_only_resource_types=["tool"],
            visibility_level=3,
            retired_use_level_floor=3,
            legacy_source_key="original-legacy-source",
        )
        session.add(row)
        await session.commit()
        ident = row.id
    async with session_factory() as session:
        loaded = await session.get(PermissionModel, ident)
        raw = (
            await session.execute(
                sa.select(PermissionModel.__table__.c.retired_use_level_floor).where(
                    PermissionModel.__table__.c.id == ident
                )
            )
        ).scalar_one()
        assert raw == loaded.retired_use_level_floor == 3
        assert loaded.legacy_source_key == "original-legacy-source"
        assert "retired_use_level_floor" not in loaded.model_dump()
        assert "retired_use_level_floor" not in repr(loaded)
