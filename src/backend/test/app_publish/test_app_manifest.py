"""T008 — ``bisheng-app.yaml``: the acceptance and rejection matrix (AC-07 / AC-11 / AC-46 / AC-56).

This is the file that decides what a developer sees when the manifest is wrong,
so every case asserts on the *shape* of the rejection, not just that one
happened. Three shape rules run through all of it:

* **The failure is always the five-tuple** ``{stage, code, message, details,
  hints}`` (AC-11). ``code`` + ``stage`` + ``details`` are what the CLI and a
  local agent branch on; ``message`` + ``hints`` are what a person reads. Two
  parallel structures for the same failure would drift within a release.
* **``details`` names the field.** "manifest 校验失败" without saying *which*
  field is the reason developers paste the whole file into a chat window.
* **A rejected manifest never becomes a silent default.** A non-empty
  ``capabilities`` block on a deployment without the capability bus is refused
  (16231) rather than dropped — an app that quietly starts without the models
  it asked for gives its owner nothing to debug (design D16).
"""

from __future__ import annotations

import textwrap

import pytest

pytestmark = pytest.mark.asyncio

BASE = {
    "name": "minimal-app",
    "runtime": "python3.11",
    "port": 8080,
}


def _yaml(**overrides) -> str:
    """A manifest body with ``overrides`` merged in; ``None`` drops the key."""
    import yaml as pyyaml

    body = dict(BASE)
    body.update(overrides)
    body = {key: value for key, value in body.items() if value is not None}
    return pyyaml.safe_dump(body, allow_unicode=True, sort_keys=False)


async def _validate(raw: str):
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest

    return await validate_manifest(raw)


# ---------------------------------------------------------------------------
# Schema layer (AC-07)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["name", "runtime", "port"])
async def test_missing_required_name_runtime_port_each_rejected(tier_seed, field):
    """Each required field, dropped one at a time → 16221 naming that field (AC-07 / AC-11)."""
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    with pytest.raises(AppManifestInvalidError) as excinfo:
        await _validate(_yaml(**{field: None}))
    assert excinfo.value.code == 16221
    reported = {item["field"]: item["reason"] for item in excinfo.value.kwargs["details"]["errors"]}
    assert reported.get(field) == "missing", f"details must name {field!r}, got {reported}"


async def test_unknown_field_rejected_with_suggestion(tier_seed):
    """``extra='forbid'`` plus a "did you mean" — a typo'd key is the most common manifest bug."""
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    with pytest.raises(AppManifestInvalidError) as excinfo:
        await _validate(_yaml(runtimee="python3.11"))
    errors = excinfo.value.kwargs["details"]["errors"]
    unknown = [item for item in errors if item["field"] == "runtimee"]
    assert unknown, f"the unknown key must be reported by name: {errors}"
    assert unknown[0].get("suggestion") == "runtime"


async def test_runtime_not_in_local_enum_rejected_16222(tier_seed):
    """A well-formed but unsupported ``runtime`` is its own code — the CLI's remedy differs."""
    from bisheng.common.errcode.app_publish import AppRuntimeUnsupportedError

    with pytest.raises(AppRuntimeUnsupportedError) as excinfo:
        await _validate(_yaml(runtime="node20"))
    assert excinfo.value.code == 16222
    assert excinfo.value.kwargs["details"]["field"] == "runtime"
    assert "python3.11" in " ".join(excinfo.value.kwargs["hints"])


@pytest.mark.parametrize("port", [0, 65536, -1])
async def test_port_out_of_range_rejected(tier_seed, port):
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    with pytest.raises(AppManifestInvalidError) as excinfo:
        await _validate(_yaml(port=port))
    assert any(item["field"] == "port" for item in excinfo.value.kwargs["details"]["errors"])


async def test_manifest_version_ahead_hints_upgrade_platform(tier_seed):
    """A newer CLI against an older platform gets "upgrade the platform", not "unknown field" (D3)."""
    from bisheng.app_publish.domain.schemas.app_manifest import SUPPORTED_MANIFEST_VERSION
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    with pytest.raises(AppManifestInvalidError) as excinfo:
        await _validate(_yaml(manifest_version=SUPPORTED_MANIFEST_VERSION + 1))
    joined = " ".join(excinfo.value.kwargs["hints"])
    assert "升级" in joined or "upgrade" in joined.lower()
    assert excinfo.value.kwargs["details"]["field"] == "manifest_version"


async def test_yaml_uses_safe_load_rejects_python_object_tag(tier_seed):
    """``!!python/object`` is remote code execution under ``full_load`` — it must never construct."""
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    hostile = textwrap.dedent(
        """
        name: evil
        runtime: python3.11
        port: 8080
        description: !!python/object/apply:os.system ["touch /tmp/f055-pwned"]
        """
    )
    with pytest.raises(AppManifestInvalidError):
        await _validate(hostile)


# ---------------------------------------------------------------------------
# Local reference layer (AC-46 / AC-56)
# ---------------------------------------------------------------------------


async def test_tier_absent_defaults_to_light(tier_seed):
    outcome = await _validate(_yaml())
    assert outcome.manifest.tier is None, "the manifest keeps what the developer wrote"
    assert outcome.tier.code == "light", "the resolved tier is 轻量 (AC-46)"


async def test_tier_unknown_or_disabled_rejected_16223_with_details_reason(publish_db, tier_seed):
    """One code, ``details.reason`` carries the cause — resolved by ``ResourceTierService``, not re-derived."""
    from bisheng.common.errcode.app_publish import AppTierUnavailableError
    from bisheng.database.models.resource_tier import ResourceTierDao

    with pytest.raises(AppTierUnavailableError) as excinfo:
        await _validate(_yaml(tier="gigantic"))
    assert (excinfo.value.code, excinfo.value.kwargs["details"]["reason"]) == (16223, "not_found")

    async with publish_db() as session:
        await ResourceTierDao.aupdate_row(session, "performance", enabled=False)
        await session.commit()
    with pytest.raises(AppTierUnavailableError) as excinfo:
        await _validate(_yaml(tier="performance"))
    assert (excinfo.value.code, excinfo.value.kwargs["details"]["reason"]) == (16223, "disabled")


async def test_capabilities_non_empty_rejected_16231(tier_seed):
    """Refused, not silently ignored (design D16)."""
    from bisheng.common.errcode.app_publish import AppCapabilityBusDisabledError

    with pytest.raises(AppCapabilityBusDisabledError) as excinfo:
        await _validate(_yaml(capabilities={"models": [{"name": "Qwen3"}]}))
    assert excinfo.value.code == 16231
    assert excinfo.value.kwargs["details"]["field"].startswith("capabilities")

    # An empty / absent block is fine — the common case must not be collateral.
    assert (await _validate(_yaml(capabilities={"models": [], "knowledge_bases": []}))).manifest is not None


async def test_secret_reference_rejected_16230(tier_seed):
    """AC-56: a secret reference anywhere in the declaration is refused in this version."""
    from bisheng.common.errcode.app_publish import AppSecretReferenceUnsupportedError

    with pytest.raises(AppSecretReferenceUnsupportedError) as excinfo:
        await _validate(_yaml(capabilities={"models": [{"name": "Qwen3", "secret_ref": "vault://k"}]}))
    assert excinfo.value.code == 16230


async def test_database_tables_declared_gives_hints_not_reject(tier_seed):
    """This round the platform does not create tables; refusing the declaration would block the script (D3)."""
    outcome = await _validate(_yaml(database={"tables": [{"name": "orders", "columns": []}]}))
    assert outcome.manifest.database.tables
    assert any("BISHENG_APP_DB_URL" in hint for hint in outcome.hints)


# ---------------------------------------------------------------------------
# Failure shape (AC-11)
# ---------------------------------------------------------------------------


async def test_failure_tuple_has_machine_and_human_forms(tier_seed):
    """One structure, two audiences — the same dict is returned to the CLI, shown on the publish face and stored."""
    from bisheng.app_publish.domain.models.app_deployment import STAGE_PRECHECK_MANIFEST
    from bisheng.app_publish.domain.schemas.failure import failure_from_error
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    with pytest.raises(AppManifestInvalidError) as excinfo:
        await _validate(_yaml(name=None))
    failure = failure_from_error(excinfo.value, stage=STAGE_PRECHECK_MANIFEST)

    assert set(failure) == {"stage", "code", "message", "details", "hints"}
    # machine-readable half
    assert failure["stage"] == STAGE_PRECHECK_MANIFEST
    assert failure["code"] == 16221
    assert isinstance(failure["details"], dict)
    # human-readable half
    assert failure["message"] and isinstance(failure["message"], str)
    assert isinstance(failure["hints"], list) and all(isinstance(hint, str) for hint in failure["hints"])
    # and it survives a JSON round trip, because that is how it reaches all three consumers
    import json

    assert json.loads(json.dumps(failure, ensure_ascii=False)) == failure
