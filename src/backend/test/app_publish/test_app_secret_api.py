"""Session API boundaries. 覆盖 AC: AC-66, AC-67, AC-68, AC-73, AC-74, AC-76, AC-89, AC-90, AC-91, AC-92."""

from test.app_publish.test_app_secret_repository import secret_repository as secret_repository


async def test_session_save_and_get_never_return_plaintext(
    secret_repository, app_factory, owner_user, api_app, monkeypatch
):
    from bisheng.app_publish.api.endpoints import app_secrets as endpoint
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService

    repo, cipher = secret_repository
    monkeypatch.setattr(endpoint, "service", lambda: AppSecretService(repository=repo, cipher=cipher))
    app, _ = await app_factory()
    async with api_app(payload=owner_user.payload) as client:
        response = await client.put(
            f"/api/v1/apps/{app.id}/secrets/COLOR", json={"value": "do-not-display", "expected_revision": 0}
        )
        assert response.status_code == 200 and response.json()["data"]["revision"] == 1
        assert "do-not-display" not in response.text
        response = await client.get(f"/api/v1/apps/{app.id}/secrets")
        assert response.json()["data"]["items"][0]["present"]
        assert "do-not-display" not in response.text


async def test_validation_strips_input_and_context(secret_repository, app_factory, owner_user, api_app):
    app, _ = await app_factory()
    async with api_app(payload=owner_user.payload) as client:
        for value in [{"sentinel": "never-print"}, ["never-print"]]:
            response = await client.put(
                f"/api/v1/apps/{app.id}/secrets/COLOR", json={"value": value, "expected_revision": 0}
            )
            assert response.status_code == 200 and response.json()["status_code"] == 16280
            assert "never-print" not in response.text
        response = await client.post(
            f"/api/v1/apps/{app.id}/secrets/rebuild", json={"confirm_restart": False, "env": {"A": "never-print"}}
        )
        assert response.json()["status_code"] == 16280 and "never-print" not in response.text


async def test_secret_routes_are_v1_only(api_app, owner_user):
    async with api_app(payload=owner_user.payload) as client:
        response = await client.put("/api/v2/apps/missing/secrets/COLOR", json={"value": "x", "expected_revision": 0})
        assert response.status_code in {401, 404, 405}


async def test_cli_polling_exposes_missing_names_without_values(
    secret_repository, app_factory, deployment_factory, owner_user, service_account_principal, api_app, monkeypatch
):
    """AC-72: the actual CLI polling endpoint carries safe missing-reference metadata."""
    from bisheng.app_publish.application import runtime_secrets
    from bisheng.app_publish.domain.services.app_secret_service import AppSecretService

    repo, cipher = secret_repository
    app, version = await app_factory()
    service = AppSecretService(repository=repo, cipher=cipher)
    await service.save(app.id, "READY", value="private-value", expected_revision=0, actor=owner_user.payload)
    deployment = await deployment_factory(
        app_id=app.id,
        version_id=version.id,
        manifest={"capabilities": {"secrets": [{"name": "READY"}, {"name": "MISSING"}]}},
    )

    async def summary(app_id, declaration):
        return await service.reference_status(app_id, declaration)

    monkeypatch.setattr(runtime_secrets, "secret_reference_status", summary)
    async with api_app(principal=service_account_principal()) as client:
        response = await client.get(f"/api/v2/apps/deployments/{deployment.id}")
    assert response.status_code == 200 and response.json()["status_code"] == 200
    rows = response.json()["data"]["secret_references"]
    assert {row["name"]: row["reason"] for row in rows} == {"READY": "ok", "MISSING": "missing_value"}
    assert "private-value" not in response.text
