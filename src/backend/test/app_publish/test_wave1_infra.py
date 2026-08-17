"""Wave 1 infrastructure smoke tests (F055 T001-T007).

Guards the pieces that have no test pairing of their own: the two ORM shapes
and their DAOs on a real (sqlite) session, the 162xx error contract and its
"one code, one meaning" invariants, the audit lockstep registration, the five
new settings keys, and the conftest fixtures themselves — a broken
``tarball_factory`` or a half-patched ``fake_minio`` would otherwise surface as
a confusing failure inside a Wave 2 test.

These are infrastructure assertions, not AC coverage: the ACs of the tiers, the
package gates and the version records are carried by T008-T017.
"""

from __future__ import annotations

import tarfile
from pathlib import Path

import pytest

from bisheng.app_publish.domain.constants import RELEASE_AUDIT_TARGET_TYPE, AppReleaseAuditAction
from bisheng.app_publish.domain.models import AppDeployment, AppDeploymentDao
from bisheng.app_publish.domain.models.app_deployment import (
    ACTIVE_STATUSES,
    DEPLOYMENT_STAGES,
    DEPLOYMENT_STATUSES,
    STAGE_APPROVAL_CREATED,
    STAGE_RECEIVED,
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCEEDED,
    STATUS_WAITING_APPROVAL,
)
from bisheng.common.errcode import app_publish as errcodes
from bisheng.database.models.resource_tier import (
    DEFAULT_TIER_CODE,
    TIER_CODE_LIGHT,
    TIER_CODE_PERFORMANCE,
    TIER_CODE_STANDARD,
    ResourceTier,
    ResourceTierDao,
)

# ---- error codes (T004) ------------------------------------------------------


def _error_classes():
    return [
        value
        for value in vars(errcodes).values()
        if isinstance(value, type)
        and issubclass(value, errcodes.AppPublishError)
        and value is not errcodes.AppPublishError
    ]


def test_every_code_is_in_the_162_band_and_unique():
    codes = [cls.Code for cls in _error_classes()]
    assert codes, "the 162xx family must not be empty"
    assert all(16200 <= code <= 16299 for code in codes), sorted(codes)
    assert len(codes) == len(set(codes)), "one code, one meaning — duplicates found"


def test_16225_is_only_the_approval_scenario_and_capacity_is_16226():
    """The two codes this family has already merged once by accident (design §4.2 ⑧)."""
    assert errcodes.AppApprovalScenarioDisabledError.Code == 16225
    assert errcodes.AppCapacityInsufficientError.Code == 16226
    assert "approval" in errcodes.AppApprovalScenarioDisabledError.Msg.lower()
    assert "capacity" in errcodes.AppCapacityInsufficientError.Msg.lower()


def test_tier_failure_is_one_code_with_a_reason_not_two_codes():
    """``not_found`` and ``disabled`` share 16223; 16271 / 16272 must not exist."""
    assert errcodes.AppTierUnavailableError.Code == 16223
    assert {cls.Code for cls in _error_classes()}.isdisjoint({16271, 16272})


def test_error_payload_carries_reason_for_machine_readers():
    error = errcodes.AppTierUnavailableError(reason="disabled")
    assert error.to_dict()["data"]["reason"] == "disabled"
    assert error.to_dict()["status_code"] == 16223


def test_f055_codes_are_not_declared_in_the_f054_module():
    """162 lives in its own file; adding to ``app_factory.py`` breaks the band split (K9)."""
    from bisheng.common.errcode import app_factory

    f054_codes = {
        value.Code
        for value in vars(app_factory).values()
        if isinstance(value, type) and issubclass(value, app_factory.AppFactoryError)
    }
    assert all(not (16200 <= code <= 16299) for code in f054_codes), sorted(f054_codes)


def test_every_code_has_copy_in_all_three_languages():
    """The locale files are the other half of the code declaration (C5)."""
    import json

    root = Path(__file__).resolve().parents[4] / "src" / "frontend" / "packages" / "locales" / "src" / "api_errors"
    if not root.is_dir():  # pragma: no cover - backend-only checkout
        pytest.skip("frontend locales package not present in this checkout")
    codes = {str(cls.Code) for cls in _error_classes()} | {"16200"}
    for language in ("zh-Hans", "en", "ja"):
        copy = json.loads((root / f"{language}.json").read_text(encoding="utf-8"))
        missing = sorted(codes - set(copy))
        assert not missing, f"{language}.json is missing copy for {missing}"


# ---- audit lockstep (T006) ---------------------------------------------------


def test_release_actions_are_registered_in_the_ui_whitelist():
    from bisheng.database.models.audit_log import _UI_VISIBLE_V2_ACTIONS, _V2_NAMESPACE_TO_ACTION_PREFIX

    assert _V2_NAMESPACE_TO_ACTION_PREFIX["app"] == "app."
    missing = [action.value for action in AppReleaseAuditAction if action.value not in _UI_VISIBLE_V2_ACTIONS]
    assert not missing, f"written but invisible on the audit page: {missing}"


def test_release_family_does_not_collide_with_f054_publish_actions():
    """``app.publish`` is F054's *state action*; the pipeline family is ``app.release.*`` (design D12)."""
    from bisheng.app_runtime.domain.constants import AppAuditAction

    f054 = {action.value for action in AppAuditAction}
    f055 = {action.value for action in AppReleaseAuditAction}
    assert f054.isdisjoint(f055)
    assert all(action.startswith("app.release.") for action in f055)
    assert RELEASE_AUDIT_TARGET_TYPE == "app_version"


# ---- settings (T005) ---------------------------------------------------------


def test_settings_expose_the_five_publish_keys_under_app_runtime():
    """All five hang off the F054 ``app_runtime`` block — no new top-level key (K10)."""
    from bisheng.core.config.settings import Settings

    settings = Settings()
    assert settings.app_runtime.max_package_mb == 50
    assert settings.app_runtime.max_unpacked_mb == 200
    assert settings.app_runtime.max_package_entries == 20000
    assert settings.app_runtime.default_tiers is None
    assert settings.app_runtime.preview_ttl_days == 7
    assert not hasattr(settings, "app_publish"), "publish settings must not open a second top-level key"


# ---- tenant-filter registration (T001 / T002) --------------------------------


def test_both_new_model_modules_are_registered_for_metadata_import():
    from bisheng.core.database.tenant_filter import _TENANT_AWARE_MODEL_MODULES

    assert "bisheng.app_publish.domain.models" in _TENANT_AWARE_MODEL_MODULES
    assert "bisheng.database.models.resource_tier" in _TENANT_AWARE_MODEL_MODULES


def test_resource_tier_has_no_tenant_column_and_app_deployment_has_one():
    """Platform-level vs. tenant-scoped, decided by the physical column (design K6)."""
    assert "tenant_id" not in ResourceTier.__table__.columns
    assert "tenant_id" in AppDeployment.__table__.columns


def test_stage_and_status_are_explicit_columns_not_json():
    """SQL filters on both; ``JSON_EXTRACT`` is banned on DM8 (C2)."""
    from sqlalchemy import String

    assert isinstance(AppDeployment.__table__.columns["stage"].type, String)
    assert isinstance(AppDeployment.__table__.columns["status"].type, String)
    assert isinstance(AppDeployment.__table__.columns["tier_code"].type, String)


def test_stage_and_status_value_sets_match_the_design():
    assert DEPLOYMENT_STAGES == {
        "received",
        "secret_scan",
        "precheck_manifest",
        "precheck_build",
        "precheck_probe",
        "version_recorded",
        "approval_created",
        "approved",
        "publishing",
        "online",
        "pending_online",
    }
    assert DEPLOYMENT_STATUSES == {"running", "waiting_approval", "succeeded", "failed"}
    assert set(ACTIVE_STATUSES) == {STATUS_RUNNING, STATUS_WAITING_APPROVAL}
    assert STATUS_SUCCEEDED not in ACTIVE_STATUSES and STATUS_FAILED not in ACTIVE_STATUSES


def test_resource_tier_dao_offers_no_delete():
    """ "Only disable, never delete" is the invariant F054 relies on (AC-47 / D11)."""
    assert not [name for name in dir(ResourceTierDao) if "delete" in name or "remove" in name]


# ---- DAOs on a real session (T001 / T002 / T003) -----------------------------


async def test_deployment_dao_advance_and_fail(publish_db, deployment_factory):
    row = await deployment_factory()
    assert row.stage == STAGE_RECEIVED and row.status == STATUS_RUNNING

    async with publish_db() as session:
        assert await AppDeploymentDao.aadvance_stage(
            session,
            row.id,
            stage=STAGE_APPROVAL_CREATED,
            status=STATUS_WAITING_APPROVAL,
            approval_instance_id=77,
            tier_code=TIER_CODE_LIGHT,
        )
        await session.commit()

    async with publish_db() as session:
        loaded = await AppDeploymentDao.aget(session, row.id)
        assert (loaded.stage, loaded.status) == (STAGE_APPROVAL_CREATED, STATUS_WAITING_APPROVAL)
        assert loaded.approval_instance_id == 77
        assert loaded.tier_code == TIER_CODE_LIGHT
        # Columns not named in the call keep their value: ``None`` means "leave
        # alone", never "write NULL".
        assert loaded.owner_user_id == row.owner_user_id

    failure = {"stage": "precheck_manifest", "code": 16221, "message": "bad", "details": [], "hints": []}
    async with publish_db() as session:
        assert await AppDeploymentDao.aset_failed(session, row.id, failure=failure)
        await session.commit()

    async with publish_db() as session:
        loaded = await AppDeploymentDao.aget(session, row.id)
        assert loaded.status == STATUS_FAILED
        assert loaded.failure == failure
        # ``aset_failed`` without an explicit stage keeps where it failed.
        assert loaded.stage == STAGE_APPROVAL_CREATED


async def test_active_lookup_ignores_finished_attempts(publish_db, deployment_factory):
    app_id = "app-under-test"
    await deployment_factory(app_id=app_id, status=STATUS_FAILED)
    await deployment_factory(app_id=app_id, status=STATUS_SUCCEEDED)
    async with publish_db() as session:
        assert await AppDeploymentDao.aget_active_by_app(session, app_id) is None

    live = await deployment_factory(app_id=app_id, status=STATUS_WAITING_APPROVAL)
    async with publish_db() as session:
        found = await AppDeploymentDao.aget_active_by_app(session, app_id)
        assert found is not None and found.id == live.id


async def test_resource_tier_dao_roundtrip_and_disable_semantics(publish_db):
    async with publish_db() as session:
        for index, (code, name, cpu, memory) in enumerate(
            (
                (TIER_CODE_LIGHT, "轻量", 1000, 2048),
                (TIER_CODE_STANDARD, "标准", 2000, 4096),
                (TIER_CODE_PERFORMANCE, "性能", 4000, 8192),
            )
        ):
            await ResourceTierDao.acreate(
                session,
                ResourceTier(code=code, name=name, cpu_millicores=cpu, memory_mb=memory, sort_order=index),
            )
        await session.commit()

    async with publish_db() as session:
        assert [tier.code for tier in await ResourceTierDao.alist(session)] == [
            TIER_CODE_LIGHT,
            TIER_CODE_STANDARD,
            TIER_CODE_PERFORMANCE,
        ]
        assert (await ResourceTierDao.aget_by_code(session, TIER_CODE_LIGHT)).cpu_millicores == 1000
        assert await ResourceTierDao.aget_by_code(session, "nope") is None

    async with publish_db() as session:
        assert await ResourceTierDao.aupdate_row(session, TIER_CODE_PERFORMANCE, enabled=False)
        await session.commit()

    async with publish_db() as session:
        # A disabled tier is still resolvable — that is what keeps existing
        # versions runnable (AC-47); it just drops out of the selection list.
        disabled = await ResourceTierDao.aget_by_code(session, TIER_CODE_PERFORMANCE)
        assert disabled is not None and disabled.enabled is False
        assert [tier.code for tier in await ResourceTierDao.alist(session, enabled_only=True)] == [
            TIER_CODE_LIGHT,
            TIER_CODE_STANDARD,
        ]


async def test_tier_code_cannot_be_renamed_through_the_dao(publish_db):
    """``app_version.tier_id`` points at the code; renaming one would dangle every snapshot."""
    async with publish_db() as session:
        await ResourceTierDao.acreate(
            session, ResourceTier(code=TIER_CODE_LIGHT, name="轻量", cpu_millicores=1000, memory_mb=2048)
        )
        await session.commit()
    async with publish_db() as session:
        with pytest.raises(ValueError, match="not editable"):
            await ResourceTierDao.aupdate_row(session, TIER_CODE_LIGHT, code="tiny")


def test_default_tier_code_is_light():
    assert DEFAULT_TIER_CODE == TIER_CODE_LIGHT


# ---- alembic (T003) ----------------------------------------------------------


def test_revision_chains_onto_the_f054_head():
    import importlib.util

    path = (
        Path(__file__).resolve().parents[2]
        / "bisheng"
        / "core"
        / "database"
        / "alembic"
        / "versions"
        / "v3_0_0_f055_app_publish_tables.py"
    )
    spec = importlib.util.spec_from_file_location("f055_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.revision == "f055_app_publish_tables"
    assert module.down_revision == "f054_app_runtime_tables"


# ---- conftest fixtures (T007) ------------------------------------------------


def test_tarball_factory_emits_the_four_tar_only_entry_kinds(tarball_factory):
    package = tarball_factory(symlink=True, hardlink=True, device=True, fifo=True, absolute_path=True, traversal=True)
    with tarfile.open(package, mode="r:gz") as tar:
        members = {member.name: member for member in tar.getmembers()}
    assert members["link-to-etc-passwd"].issym()
    assert members["hardlink-to-main"].islnk()
    assert members["dev-null"].isdev()
    assert members["a-fifo"].isfifo()
    assert any(name.startswith("/") for name in members)
    assert any(".." in name for name in members)
    assert "bisheng-app.yaml" in members


def test_tarball_factory_can_drop_the_manifest_and_pad_entries(tarball_factory):
    package = tarball_factory(include_manifest=False, entries=40)
    with tarfile.open(package, mode="r:gz") as tar:
        names = tar.getnames()
    assert "bisheng-app.yaml" not in names
    assert len(names) == 40


def test_tarball_factory_tar_bomb_stays_small_on_the_wire(tarball_factory):
    """The unpacked gate exists because the upload gate cannot see this."""
    package = tarball_factory(payload_mb=8)
    assert package.stat().st_size < 1 * 1024 * 1024
    with tarfile.open(package, mode="r:gz") as tar:
        assert sum(member.size for member in tar.getmembers()) > 8 * 1024 * 1024


async def test_fake_minio_records_path_uploads_and_bucket_creation(fake_minio, tmp_path):
    source = tmp_path / "code.tar.gz"
    source.write_bytes(b"payload")

    fake_minio.create_bucket_sync("bisheng-apps")
    await fake_minio.put_object(bucket_name="bisheng-apps", object_name="apps/a/versions/v/code.tar.gz", file=source)

    assert fake_minio.created_buckets == ["bisheng-apps"]
    put_calls = [kwargs for name, kwargs in fake_minio.calls if name == "put_object"]
    assert put_calls and put_calls[0]["from_path"] is True
    assert await fake_minio.get_object("bisheng-apps", "apps/a/versions/v/code.tar.gz") == b"payload"
    assert fake_minio.list_object_names("bisheng-apps", prefix="apps/a/") == ["apps/a/versions/v/code.tar.gz"]


def test_service_account_principal_defaults_to_the_owner(service_account_principal, owner_user):
    principal = service_account_principal()
    assert principal.has_scope("app:manage")
    assert principal.resource_owner_user_id == owner_user.user_id
    assert principal.subject_user_id != owner_user.user_id, "the acting subject is the service account, not the owner"


def test_tenant_admin_fixture_is_not_a_super_admin(tenant_admin_user, super_admin_user):
    assert tenant_admin_user.payload.is_global_super is False
    assert super_admin_user.payload.is_global_super is True
    assert tenant_admin_user.tenant_id != 1, "Root has no tenant administrators; that is why AC-21 needs a fallback"


async def test_dept_admin_fixture_is_resolvable_by_the_approver_resolver(publish_db, dept_admin_user, owner_user):
    from bisheng.approval.domain.services.approver_resolver import resolve_approvers_from_sources

    class _Req:
        applicant_department_id = dept_admin_user.department_id

    resolved = await resolve_approvers_from_sources([{"type": "department_admin"}], _Req())
    assert resolved == [dept_admin_user.user_id]


async def test_app_factory_and_deployment_factory_link_up(app_factory, deployment_factory, publish_db):
    app_row, version_row = await app_factory()
    deployment = await deployment_factory(app_id=app_row.id, version_id=version_row.id)
    async with publish_db() as session:
        loaded = await AppDeploymentDao.aget(session, deployment.id)
    assert loaded.app_id == app_row.id
    assert loaded.version_id == version_row.id


def test_app_runtime_settings_fixture_patches_the_gates(app_runtime_settings):
    conf = app_runtime_settings(max_package_mb=1, max_package_entries=5)
    assert conf.max_package_mb == 1
    assert conf.max_package_entries == 5


async def test_tier_seed_skips_until_the_service_exists(tier_seed):
    """Placeholder that turns green the moment T015 lands — a skip here is the expected Wave 1 state."""
    assert tier_seed
