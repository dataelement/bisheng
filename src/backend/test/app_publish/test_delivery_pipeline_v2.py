"""覆盖 AC: AC-11、AC-13、AC-16、AC-31、AC-39、AC-48。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from bisheng.app_publish.domain.schemas.app_manifest import AppManifest
from bisheng.app_publish.domain.services.publish_pipeline_service import PublishPipelineService
from bisheng.app_runtime.domain.services.runtime_delivery_coordinator import RuntimeDeliveryCoordinator
from bisheng.common.services.config_service import settings


async def test_v2_bundle_prepare_never_calls_legacy_image_build(monkeypatch):
    monkeypatch.setattr(settings.app_runtime, "runtime_protocol_version", 2)
    prepare = AsyncMock(return_value=SimpleNamespace(content={"mode": "bundle", "compiled_artifact_id": "artifact"}))
    monkeypatch.setattr(RuntimeDeliveryCoordinator, "prepare", prepare)
    monkeypatch.setattr(PublishPipelineService, "_tier", AsyncMock(return_value="tier"))
    legacy = AsyncMock()
    monkeypatch.setattr("bisheng.app_publish.domain.services.precheck_service.precheck_build", legacy)
    manifest = AppManifest.model_validate(
        {"manifest_version": 2, "name": "Example", "slug": "example", "runtime": "python3.11", "port": 8080}
    )
    context = {"manifest": manifest}
    await PublishPipelineService._stage_build(SimpleNamespace(id="deployment"), context)
    legacy.assert_not_called()
    prepare.assert_awaited_once()
    assert context["image_ref"] is None and context["resolved_delivery"]["mode"] == "bundle"


async def test_probe_uses_frozen_delivery_not_runtime_base_image(monkeypatch):
    probe = AsyncMock()
    monkeypatch.setattr(RuntimeDeliveryCoordinator, "probe", probe)
    legacy = AsyncMock()
    monkeypatch.setattr("bisheng.app_publish.domain.services.precheck_service.precheck_probe", legacy)
    await PublishPipelineService._stage_probe(
        "deployment",
        {"resolved_delivery": {"mode": "bundle"}, "manifest": "manifest", "tier": "tier", "image_ref": None},
    )
    probe.assert_awaited_once_with("deployment", "manifest", "tier")
    legacy.assert_not_called()
