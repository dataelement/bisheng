"""The publish pipeline: a synchronous receive leg and an asynchronous stage machine (design D1).

One ``bisheng deploy`` is two halves, split where the latency changes by three
orders of magnitude:

* :meth:`PublishPipelineService.accept` runs **inside the HTTP request** and
  answers in milliseconds: ownership, the volume gates, unpack safety, the
  manifest, the two submission gates, the snapshot upload, one ``app_deployment``
  row. **It issues no RPC** — a single call to an unreachable runtime-manager
  here would turn "you forgot ``port``" into a request hanging on a socket
  timeout, and that is exactly what design D1 rejected option A over.
* :meth:`PublishPipelineService.run_pipeline` runs **on a Celery worker** and
  takes minutes: dependency build, startup probe, secret scan, metadata,
  approval request. Each stage is one single-row ``app_deployment`` UPDATE plus
  one ``app.release.*`` audit row, so "where is my publish" is answerable from
  either the table or the audit page.

Boundaries this module respects rather than works around:

* **F055 never writes the ``app`` table** (决议-8). A first publish creates the
  draft through F054's ``AppProvisionService.create_draft``; metadata updates go
  through ``AppMetaService.update_meta``. Both are imported at call time so this
  module stays importable while F054's service layer is in flight.
* **The submission gates are asked before the approval gate.** ``ApprovalGate``
  answers a duplicate submission by silently returning the existing instance,
  which would make a second ``deploy`` look successful (design K2 ① / 坑 8).
* **The stage order is the tuple** :data:`PIPELINE_STAGES`, and the scan comes
  first. Scanning is a few seconds of regex over the unpacked source; building
  is minutes plus a capacity slot. Since a hit ends the attempt outright,
  running the build first means every hit burns a build for nothing. The scan
  reads ``context["root"]``, which ``run_pipeline`` materialises before the
  loop, so it has no dependency on any build artifact (design D5, ruled
  2026-08-17; F055 AC-01 and F053 AC-31a were amended in the same change).
  Nothing else in the pipeline may assume an order beyond "the scan and both
  prechecks all pass before a version row exists".
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from bisheng.app_publish.domain.constants import AppReleaseAuditAction
from bisheng.app_publish.domain.models.app_deployment import (
    STAGE_PRECHECK_BUILD,
    STAGE_PRECHECK_PROBE,
    STAGE_RECEIVED,
    STAGE_SECRET_SCAN,
    STATUS_RUNNING,
    AppDeployment,
    AppDeploymentDao,
)
from bisheng.app_publish.domain.schemas.app_manifest import ICON_EXTENSIONS, MAX_ICON_BYTES, AppManifest
from bisheng.app_publish.domain.schemas.failure import failure_from_error
from bisheng.app_publish.domain.services import package_service, precheck_service
from bisheng.app_publish.domain.services.manifest_validator import validate_manifest
from bisheng.app_publish.domain.services.release_audit import write_release_audit
from bisheng.app_publish.domain.services.secret_scanner import scan_package
from bisheng.app_publish.domain.services.version_service import VersionService
from bisheng.common.errcode.app_publish import (
    AppNotOwnedBySubjectError,
    AppPublishRuntimeLayerDisabledError,
    AppSecretScanBlockedError,
)
from bisheng.common.errcode.base import BaseErrorCode
from bisheng.common.services.config_service import settings
from bisheng.core.context.tenant import get_current_tenant_id, set_current_tenant_id
from bisheng.core.database import get_async_db_session
from bisheng.core.storage.minio.minio_manager import get_minio_storage
from bisheng.database.models.app import AppDao
from bisheng.utils import generate_uuid

#: The asynchronous stage machine, in order. Reordering this tuple is the whole
#: mechanical cost of moving the secret scan before the build — and the reason
#: it must not be done without amending F055 AC-01 and F053 AC-31a (design D5).
PIPELINE_STAGES: tuple[tuple[str, str], ...] = (
    (STAGE_SECRET_SCAN, "_stage_scan"),
    (STAGE_PRECHECK_BUILD, "_stage_build"),
    (STAGE_PRECHECK_PROBE, "_stage_probe"),
)


@dataclass(slots=True)
class AcceptResult:
    """What ``POST /api/v2/apps/deploy`` returns — the CLI polls on ``deployment_id``."""

    deployment_id: str
    app_id: str
    version_id: str


async def enqueue_pipeline(deployment_id: str) -> None:
    """Hand the attempt to the default Celery queue.

    Imported at call time so that neither the API process nor a unit test pulls
    in the Celery app just to accept a package. The tenant id rides along in the
    task header automatically (``worker/tenant_context.py``).
    """
    from bisheng.worker.app_publish.tasks import run_publish_pipeline

    run_publish_pipeline.apply_async(args=[deployment_id])


class PublishPipelineService:
    """Both legs of one publish attempt."""

    # ------------------------------------------------------------------
    # Synchronous leg
    # ------------------------------------------------------------------

    @classmethod
    async def accept(
        cls,
        *,
        package_path: Path,
        principal,
        app_id: str | None = None,
        confirm_schema_change: bool = False,
        tenant_id: int | None = None,
    ) -> AcceptResult:
        """Receive one package. Fast, local, and it leaves nothing behind when it refuses.

        ``confirm_schema_change`` is accepted and recorded but not consumed this
        round (design D3): the parameter exists now so the CLI's flag does not
        have to change again when structural evolution ships.
        """
        if not settings.app_runtime.enabled:
            raise AppPublishRuntimeLayerDisabledError(
                msg="本环境未启用应用工场运行时层",
                details={"reason": "runtime_layer_disabled"},
                hints=["请联系管理员在部署配置中开启 app_runtime"],
            )

        tenant = tenant_id if tenant_id is not None else get_current_tenant_id()
        owner_user_id = int(principal.resource_owner_user_id)
        package_service.check_upload_size(Path(package_path).stat().st_size)

        workdir = Path(tempfile.mkdtemp(prefix="bisheng-app-"))
        try:
            extracted = package_service.safe_extract(Path(package_path), workdir / "src")
            validated = await validate_manifest(package_service.read_manifest_bytes(extracted.root))

            if app_id:
                await cls._assert_owned(app_id, owner_user_id)
            else:
                app_id = await cls._create_draft(validated.manifest, owner_user_id=owner_user_id, tenant_id=tenant)

            # AC-03's two gates, asked before the approval gate ever sees this.
            await cls._assert_submittable(app_id)

            version_id = generate_uuid()
            code_object_key = await package_service.store_package(
                Path(package_path), app_id=app_id, version_id=version_id
            )

            deployment = AppDeployment(
                tenant_id=tenant,
                app_id=app_id,
                owner_user_id=owner_user_id,
                submitted_by_user_id=int(principal.subject_user_id),
                version_id=version_id,
                stage=STAGE_RECEIVED,
                status=STATUS_RUNNING,
                code_object_key=code_object_key,
                manifest=validated.manifest.model_dump(),
                tier_code=validated.tier.code,
            )
            async with get_async_db_session() as session:
                await AppDeploymentDao.acreate(session, deployment)
                await session.commit()
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

        await write_release_audit(
            AppReleaseAuditAction.SUBMIT,
            deployment=deployment,
            metadata={
                "source": "cli",
                "tier_code": validated.tier.code,
                "confirm_schema_change": bool(confirm_schema_change),
                "manifest_hints": validated.hints,
            },
        )
        # Best effort, on the receive leg rather than on a schedule (design D2).
        try:
            await package_service.cleanup_orphans(app_id)
        except Exception:
            # Best effort by design: the sweep is a housekeeping side errand and
            # must never be able to refuse somebody's publish.
            logger.exception(f"app_publish.orphan_sweep_failed app_id={app_id}")

        await enqueue_pipeline(deployment.id)
        logger.info(
            f"app_publish.pipeline deployment_id={deployment.id} app_id={app_id} "
            f"stage={STAGE_RECEIVED} status={STATUS_RUNNING}"
        )
        return AcceptResult(deployment_id=deployment.id, app_id=app_id, version_id=version_id)

    @classmethod
    async def _assert_owned(cls, app_id: str, owner_user_id: int) -> None:
        """An iteration only proceeds on an app the credential's resource owner owns (AC-04)."""
        async with get_async_db_session() as session:
            app_row = await AppDao.aget(session, app_id)
        if app_row is None or app_row.owner_user_id != owner_user_id:
            raise AppNotOwnedBySubjectError(
                msg="该应用归属其他用户, 当前密钥无法发布",
                details={"app_id": app_id, "reason": "owner_mismatch"},
                hints=["确认 .bisheng/app_id 指向的是本人名下的应用, 或省略 app_id 以首发一个新应用"],
            )

    @classmethod
    async def _create_draft(cls, manifest: AppManifest, *, owner_user_id: int, tenant_id: int) -> str:
        """First publish: F054 creates the application row, F055 never does (决议-8 / 坑 26)."""
        from bisheng.app_runtime.domain.services.app_provision_service import AppProvisionService

        return await AppProvisionService.create_draft(
            name=manifest.name,
            slug=manifest.slug,
            description=manifest.description,
            owner_user_id=owner_user_id,
            tenant_id=tenant_id,
        )

    @classmethod
    async def _assert_submittable(cls, app_id: str) -> None:
        """16251 / 16252 — asked here, not delegated to the approval gate (design K2 ①)."""
        from bisheng.app_publish.domain.services import publish_approval_service

        await publish_approval_service.assert_submittable(app_id)

    @classmethod
    async def get_deployment_status(cls, deployment_id: str, *, principal) -> dict[str, Any]:
        """What the CLI polls (design §4.2 ①). Read-only, and scoped to the caller's owner.

        Two scoping layers, and both are needed. The tenant filter keeps another
        tenant's attempt invisible on the SELECT; the explicit owner comparison
        keeps a second service account inside the *same* tenant from watching
        somebody else's publish. Neither is redundant — the first would let a
        colleague poll, the second cannot see across tenants at all.

        A miss answers 16205 rather than "not found": distinguishing "no such
        deployment" from "not yours" hands a caller an id oracle for free.
        """
        async with get_async_db_session() as session:
            deployment = await AppDeploymentDao.aget(session, deployment_id)
        owner_user_id = int(getattr(principal, "resource_owner_user_id", 0) or 0)
        if deployment is None or int(deployment.owner_user_id or 0) != owner_user_id:
            raise AppNotOwnedBySubjectError(
                msg="该发布记录不存在或不属于当前密钥",
                details={"deployment_id": deployment_id, "reason": "not_owned"},
                hints=["确认 deployment_id 来自本人名下应用的发布"],
            )

        app_state = None
        version_no = None
        app_row = None
        if deployment.app_id:
            async with get_async_db_session() as session:
                app_row = await AppDao.aget(session, deployment.app_id)
            app_state = app_row.state if app_row is not None else None
        if deployment.version_id and deployment.app_id:
            version = await VersionService.get_version(deployment.app_id, deployment.version_id)
            version_no = version.version_no if version is not None else None

        # The address exists as soon as the application row does — it is a
        # function of the slug, not of the deployment's outcome. Reporting it
        # while the attempt is still in flight is deliberate: the CLI can print
        # "this is where it will live" instead of making the developer wait.
        entry_url = None
        if app_row is not None and app_row.slug:
            from bisheng.app_runtime.domain.services.app_query_service import AppQueryService

            entry_url = AppQueryService.entry_url(app_row.slug)

        return {
            "deployment_id": deployment.id,
            "app_id": deployment.app_id,
            "version_id": deployment.version_id,
            "version_no": version_no,
            "stage": deployment.stage,
            "status": deployment.status,
            # AC-11's five-tuple, or None. The CLI branches on ``code`` and
            # prints ``message`` + ``hints``; a partially filled failure is what
            # turns an actionable error into "something went wrong".
            "failure": deployment.failure,
            "approval": {"instance_id": deployment.approval_instance_id} if deployment.approval_instance_id else None,
            "app_state": app_state,
            # F053 T034 write-back 3. Without it the CLI's ``deploy --wait``
            # could not print the entry address on success: ``entry_url`` was
            # only ever in the ``POST /deploy`` response, and at that moment a
            # first publish is still a draft, so the field was almost always
            # null exactly when it mattered. Derived from the slug by F054's
            # single implementation — never composed here, and never in the
            # browser (AC-25).
            "entry_url": entry_url,
            "scan_result": deployment.scan_result,
        }

    # ------------------------------------------------------------------
    # Asynchronous leg
    # ------------------------------------------------------------------

    @classmethod
    async def run_pipeline(cls, deployment_id: str) -> None:
        """Scan → build → probe → metadata → approval request. One UPDATE and one audit per stage."""
        async with get_async_db_session() as session:
            deployment = await AppDeploymentDao.aget(session, deployment_id)
        if deployment is None:
            logger.warning(f"app_publish.pipeline deployment_id={deployment_id} vanished before the worker ran")
            return

        cls._restore_tenant_context(deployment)
        manifest = AppManifest.model_validate(deployment.manifest or {})

        workdir = Path(tempfile.mkdtemp(prefix="bisheng-app-run-"))
        try:
            root = await cls._materialise_snapshot(deployment, workdir)
            context: dict[str, Any] = {"manifest": manifest, "root": root, "image_ref": None}
            for stage, step in PIPELINE_STAGES:
                await cls._advance(deployment, stage)
                await getattr(cls, step)(deployment, context)
            await cls._update_meta(deployment, context)
            await cls._record_version(deployment, context)
        except BaseErrorCode as exc:
            await cls._fail(deployment, exc)
            return
        except Exception as exc:  # unexpected: still leave a readable failure behind
            logger.exception(f"app_publish.pipeline deployment_id={deployment_id} crashed")
            await cls._fail(deployment, exc)
            return
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    # -- stages ---------------------------------------------------------

    @classmethod
    async def _stage_build(cls, deployment: AppDeployment, context: dict[str, Any]) -> None:
        tier = await cls._tier(deployment)
        context["tier"] = tier
        context["image_ref"] = await precheck_service.precheck_build(
            deployment, manifest=context["manifest"], tier=tier
        )

    @classmethod
    async def _stage_probe(cls, deployment: AppDeployment, context: dict[str, Any]) -> None:
        await precheck_service.precheck_probe(deployment, manifest=context["manifest"], image_ref=context["image_ref"])

    @classmethod
    async def _stage_scan(cls, deployment: AppDeployment, context: dict[str, Any]) -> None:
        """The secret scan. A hit ends the attempt: no version record, no approval request."""
        result = scan_package(context["root"])
        context["scan_result"] = result
        async with get_async_db_session() as session:
            await AppDeploymentDao.aadvance_stage(
                session, deployment.id, stage=STAGE_SECRET_SCAN, scan_result=result.to_dict()
            )
            await session.commit()
        logger.info(
            f"app_publish.scan deployment_id={deployment.id} files_scanned={result.files_scanned} "
            f"files_skipped={result.files_skipped} hits={len(result.hits)}"
        )
        if not result.blocked:
            return
        await write_release_audit(
            AppReleaseAuditAction.SCAN_BLOCKED,
            deployment=deployment,
            metadata={"hits": result.hits, "files_scanned": result.files_scanned},
        )
        raise AppSecretScanBlockedError(
            msg="发布前密钥扫描命中, 已阻断发布",
            details={"reason": "secret_scan_hit", "hits": result.hits},
            hints=[
                "从代码中移除命中的凭据, 改为读环境变量或平台注入的运行期凭据",
                "凭据一旦进过版本库就应视为已泄漏, 请同时吊销它",
            ],
        )

    # -- post-precheck steps --------------------------------------------

    @classmethod
    async def _update_meta(cls, deployment: AppDeployment, context: dict[str, Any]) -> None:
        """AC-05: name / description / icon land now, without waiting for approval.

        Delegated to F054's ``AppMetaService`` — the detail page writes metadata
        through the same method, and a second implementation here would drift
        from it the first time either side gains a rule.
        """
        from bisheng.app_runtime.domain.services.app_meta_service import AppMetaService

        manifest: AppManifest = context["manifest"]
        logo, hints = await cls._store_icon(manifest, context["root"])
        await AppMetaService.update_meta(
            app_id=deployment.app_id,
            name=manifest.name,
            description=manifest.description,
            logo=logo,
        )
        if hints:
            context.setdefault("hints", []).extend(hints)
        await write_release_audit(
            AppReleaseAuditAction.CAPABILITY_DECLARED,
            deployment=deployment,
            metadata={
                "capabilities": manifest.capabilities.model_dump(),
                "tier_code": deployment.tier_code,
            },
        )

    @classmethod
    async def _store_icon(cls, manifest: AppManifest, root: Path) -> tuple[str | None, list[str]]:
        """Put the icon in the public bucket and return its **object name**.

        Not the helper endpoint's ``file_path``: that is a presigned URL with a
        seven-day lifetime, so storing it would make every hosted app's icon 403
        a week later (design 坑 16). Not the package-relative path either — that
        means nothing outside the tarball.

        An icon that is too big or in the wrong format is skipped with a hint.
        It is metadata, not a precondition for publishing.
        """
        if not manifest.icon:
            return None, []
        source = (root / manifest.icon).resolve()
        try:
            source.relative_to(root.resolve())
        except ValueError:
            return None, [f"图标路径 {manifest.icon} 指向包外, 已跳过"]
        if not source.is_file():
            return None, [f"图标文件 {manifest.icon} 不存在, 已跳过"]
        if source.suffix.lower() not in ICON_EXTENSIONS:
            return None, [f"图标仅支持 {', '.join(ICON_EXTENSIONS)}, 已跳过 {manifest.icon}"]
        if source.stat().st_size > MAX_ICON_BYTES:
            return None, [f"图标超过 {MAX_ICON_BYTES // 1024 // 1024} MB, 已跳过 {manifest.icon}"]

        storage = await get_minio_storage()
        object_name = f"icon/{generate_uuid()}{source.suffix.lower()}"
        await storage.put_object(object_name=object_name, file=source, content_type="image/png")
        return object_name, []

    @classmethod
    async def _record_version(cls, deployment: AppDeployment, context: dict[str, Any]) -> None:
        """Approval request first, version record second — design D6, owned by ``VersionService``."""
        from bisheng.app_publish.domain.services import publish_approval_service

        await VersionService.record_version(deployment, approval=publish_approval_service)

    # -- plumbing --------------------------------------------------------

    @classmethod
    def _restore_tenant_context(cls, deployment: AppDeployment) -> None:
        """The worker inherits the tenant through the Celery header; this is the assertion, not the mechanism.

        ``worker/tenant_context.py`` falls back to the default tenant when the
        header is missing — silently publishing into the wrong tenant is the
        worst shape this can take, so a mismatch is logged loudly and the row's
        own tenant wins.
        """
        current = get_current_tenant_id()
        if deployment.tenant_id and current != deployment.tenant_id:
            logger.warning(
                f"app_publish.pipeline deployment_id={deployment.id} tenant context {current} != "
                f"row tenant {deployment.tenant_id}; using the row's tenant"
            )
            set_current_tenant_id(deployment.tenant_id)

    @classmethod
    async def _materialise_snapshot(cls, deployment: AppDeployment, workdir: Path) -> Path:
        """Fetch and unpack the frozen snapshot — the worker never sees the API process's temp dir."""
        payload = await package_service.fetch_package(deployment.code_object_key)
        archive = workdir / "code.tar.gz"
        archive.write_bytes(payload or b"")
        return package_service.safe_extract(archive, workdir / "src").root

    @classmethod
    async def _tier(cls, deployment: AppDeployment):
        from bisheng.app_publish.domain.services.resource_tier_service import ResourceTierService

        return await ResourceTierService.resolve_spec(deployment.tier_code or "light")

    @classmethod
    async def _advance(cls, deployment: AppDeployment, stage: str) -> None:
        async with get_async_db_session() as session:
            await AppDeploymentDao.aadvance_stage(session, deployment.id, stage=stage, status=STATUS_RUNNING)
            await session.commit()
        deployment.stage = stage
        logger.info(
            f"app_publish.pipeline deployment_id={deployment.id} app_id={deployment.app_id} "
            f"stage={stage} status={STATUS_RUNNING}"
        )

    @classmethod
    async def _fail(cls, deployment: AppDeployment, exc: Exception) -> None:
        """Latch the five-tuple. ``record_version`` already latched its own failures — this is idempotent."""
        if isinstance(exc, BaseErrorCode):
            failure = failure_from_error(exc, stage=deployment.stage)
        else:
            failure = {
                "stage": deployment.stage,
                "code": 0,
                "message": "发布管线异常终止",
                "details": {"reason": "unexpected_error", "error": str(exc)},
                "hints": ["请重试发布; 若反复失败请联系管理员查看后端日志"],
            }
        async with get_async_db_session() as session:
            await AppDeploymentDao.aset_failed(session, deployment.id, failure=failure, stage=failure["stage"])
            await session.commit()
        if failure["code"] != 16241:  # the scan already wrote its own, more specific audit row
            await write_release_audit(
                AppReleaseAuditAction.PRECHECK_FAILED, deployment=deployment, metadata={"failure": failure}
            )
        logger.info(
            f"app_publish.pipeline deployment_id={deployment.id} app_id={deployment.app_id} "
            f"stage={failure['stage']} status=failed failure_code={failure['code']}"
        )
