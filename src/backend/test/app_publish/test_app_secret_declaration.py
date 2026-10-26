"""Manifest boundaries. 覆盖 AC: AC-54, AC-56, AC-69, AC-71, AC-72, AC-78, AC-84, AC-87, AC-88."""

import pytest
import yaml

from bisheng.common.errcode.app_publish import AppSecretReferenceUnsupportedError
from test.app_publish.test_app_secret_repository import secret_repository as secret_repository


def body(capabilities):
    return yaml.safe_dump({"name": "secret-test", "runtime": "python3.11", "port": 8080, "capabilities": capabilities})


async def test_exact_name_only_declaration_accepted_without_new_scopes(tier_seed):
    from bisheng.app_publish.domain.services.capability_bus_service import derive_scopes, parse_declaration
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest

    result = await validate_manifest(body({"secrets": [{"name": "MY_TOKEN"}, {"name": "Other"}]}))
    declaration = result.manifest.capabilities
    assert not declaration.is_empty()
    assert [ref.name for ref in declaration.secrets] == ["MY_TOKEN", "Other"]
    assert derive_scopes(declaration) == []
    assert parse_declaration(declaration.model_dump()).secrets == declaration.secrets
    assert result.hints


@pytest.mark.parametrize(
    "references",
    [
        [{"name": "DUP"}, {"name": "DUP"}],
        [{"name": "BISHENG_TOKEN"}],
        [{"name": "secretref://foo"}],
        [{"name": "ok", "value": "plain-value"}],
        [{"name": "ok", "provider": "vault"}],
        {"A": "plain-value"},
        ["TOKEN"],
    ],
)
async def test_invalid_secret_subtree_is_not_exempt(tier_seed, references):
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest
    from bisheng.common.errcode.app_publish import AppManifestInvalidError

    with pytest.raises((AppSecretReferenceUnsupportedError, AppManifestInvalidError)) as exc:
        await validate_manifest(body({"secrets": references}))
    assert "plain-value" not in str(exc.value.kwargs)


async def test_other_secret_locations_remain_rejected(tier_seed):
    from bisheng.app_publish.domain.services.manifest_validator import validate_manifest

    for capabilities in [
        {"secrets": [{"name": "TOKEN"}], "token": "do-not-leak"},
        {"models": [{"name": "vault://model"}]},
    ]:
        with pytest.raises(AppSecretReferenceUnsupportedError) as exc:
            await validate_manifest(body(capabilities))
        assert "do-not-leak" not in str(exc.value.kwargs)


def test_secret_name_diff_has_no_values():
    from bisheng.app_publish.domain.services.version_diff_service import VersionDiffService

    result = VersionDiffService.secret_reference_diff({"secrets": [{"name": "A"}]}, {"secrets": [{"name": "B"}]})
    assert result == {"added": ["B"], "removed": ["A"]}


async def test_approval_summary_contains_only_names_and_missing_status(
    secret_repository, app_factory, owner_user, monkeypatch
):
    """AC-69, AC-72, AC-84: the actual approval summary consumes secret status."""
    from bisheng.app_publish.application import runtime_secrets
    from bisheng.app_publish.domain.services import publish_approval_service
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService

    repo, cipher = secret_repository
    app, _ = await app_factory()
    service = AppSecretService(repository=repo, cipher=cipher)
    await service.save(app.id, "READY_KEY", value="never-expose-value", expected_revision=0, actor=owner_user.payload)

    async def summary(app_id, declaration):
        return await service.reference_status(app_id, declaration)

    monkeypatch.setattr(runtime_secrets, "secret_reference_status", summary)
    rows = await publish_approval_service._capabilities_payload(
        {"secrets": [{"name": "READY_KEY"}, {"name": "MISSING_KEY"}]}, tenant_id=app.tenant_id, app_id=app.id
    )
    assert rows == [
        {"kind": "secret", "name": "MISSING_KEY", "revoked": False, "reason": "missing_value"},
        {"kind": "secret", "name": "READY_KEY", "revoked": False, "reason": "ok"},
    ]
    assert "never-expose-value" not in str(rows)
