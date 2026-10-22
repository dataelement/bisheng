"""Offline harness contracts only; no assertion here proves a live deployment.

覆盖 AC: AC-35, AC-36, AC-55, AC-56
"""

from __future__ import annotations

import io
import json
import tarfile

import pytest

from test.e2e.helpers.vibe_runtime import (
    EvidenceJournal,
    Scenario,
    SuiteSettings,
    validate_package,
)


def package(path, document):
    with tarfile.open(path, "w:gz") as archive:
        content = json.dumps(document).encode()
        info = tarfile.TarInfo("bisheng-app.yaml")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
    return path


def test_settings_require_explicit_dedicated_tenant_and_safe_prefix(monkeypatch):
    """AC-55: no default production tenant or broad cleanup prefix is accepted."""
    monkeypatch.setenv("F059_E2E_TENANT_CODE", "production")
    with pytest.raises(ValueError, match="e2e-f059-"):
        SuiteSettings.from_env()


def test_settings_fail_without_explicit_live_opt_in(monkeypatch):
    """AC-55: importing or collecting the suite never starts a live mutation."""
    monkeypatch.setenv("F059_E2E_TENANT_CODE", "e2e-f059-tenant")
    monkeypatch.delenv("F059_E2E", raising=False)
    with pytest.raises(ValueError, match="F059_E2E=1"):
        SuiteSettings.from_env()


def test_package_name_and_slug_must_belong_to_suite(tmp_path):
    """AC-35, AC-55: package inspection rejects another application's identity."""
    path = package(tmp_path / "app.tar.gz", {"name": "foreign", "slug": "e2e-f059-smoke"})
    with pytest.raises(ValueError, match="name"):
        validate_package(path, "e2e-f059-smoke")


def test_package_is_inspected_without_extracting_paths(tmp_path):
    """AC-55: a nested or ambiguous manifest is not used to authorize cleanup."""
    path = tmp_path / "app.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        info = tarfile.TarInfo("../bisheng-app.yaml")
        info.size = 2
        archive.addfile(info, io.BytesIO(b"{}"))
    with pytest.raises(ValueError, match="root manifest"):
        validate_package(path, "e2e-f059-smoke")
    assert not (tmp_path.parent / "bisheng-app.yaml").exists()


def test_scenario_freezes_exact_slug_and_mode(tmp_path):
    """AC-24, AC-25, AC-55: expected delivery mode is checked before any API call."""
    path = package(
        tmp_path / "app.tar.gz",
        {
            "name": "e2e-f059-smoke",
            "slug": "e2e-f059-smoke",
            "runtime": "python3.11",
            "manifest_version": 2,
            "delivery": {"mode": "bundle"},
        },
    )
    scenario = Scenario.from_dict({"slug": "e2e-f059-smoke", "package": str(path), "mode": "bundle"})
    assert scenario.mode == "bundle"
    with pytest.raises(ValueError, match="delivery"):
        Scenario.from_dict({"slug": "e2e-f059-smoke", "package": str(path), "mode": "image"})


def test_journal_scope_cannot_change_and_contains_no_credentials(tmp_path):
    """AC-55: resume data is exact-scope, atomically saved and non-secret."""
    path = tmp_path / "evidence.json"
    journal = EvidenceJournal(path, tenant_code="e2e-f059-tenant")
    journal.record("case", ["AC-55"], "passed", app_id="app-1")
    journal.save()
    assert json.loads(path.read_text())["events"][0]["kind"] == "live-api"
    assert path.stat().st_mode & 0o077 == 0
    with pytest.raises(ValueError, match="secret"):
        journal.record("bad", ["AC-55"], "passed", access_token="fixture")
    with pytest.raises(ValueError, match="scope"):
        EvidenceJournal(path, tenant_code="e2e-f059-other")


def test_resumed_cleanup_registry_cannot_name_foreign_slug(tmp_path):
    """AC-35, AC-55: journal entries never authorize cleanup of another prefix."""
    path = tmp_path / "evidence.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tenant_code": "e2e-f059-tenant",
                "apps": {"production": {"app_id": "someone-elses-app"}},
                "events": [],
            }
        )
    )
    with pytest.raises(ValueError, match="slug"):
        EvidenceJournal(path, tenant_code="e2e-f059-tenant")


@pytest.mark.parametrize("mismatch", ["owner", "tenant", "slug"])
async def test_cleanup_revalidates_scope_before_mutation(tmp_path, mismatch):
    """AC-35, AC-55: a listed ID cannot cause writes without a fresh exact owner/scope match."""
    from types import SimpleNamespace

    from test.e2e.helpers.vibe_runtime import LiveVibeSuite

    settings = SuiteSettings("e2e-f059-tenant", (SimpleNamespace(slug="e2e-f059-smoke"),))
    journal = EvidenceJournal(tmp_path / "evidence.json", tenant_code=settings.tenant_code)
    suite = LiveVibeSuite(settings, journal, None)
    suite.tenant_id = 7
    suite.users["OWNER"] = 42
    mutations = []

    async def request(method, path, **kwargs):
        if method != "GET":
            mutations.append((method, path))
            raise AssertionError("unsafe mutation")
        if path == "/apps":
            return [{"app_id": "app-1", "slug": "e2e-f059-smoke"}]
        detail = {
            "app_id": "app-1",
            "slug": "e2e-f059-smoke",
            "name": "e2e-f059-smoke",
            "owner_user_id": 42,
            "tenant_id": 7,
            "state": "online",
        }
        detail[{"owner": "owner_user_id", "tenant": "tenant_id", "slug": "slug"}[mismatch]] = "999"
        return detail

    suite.request = request
    with pytest.raises(AssertionError):
        await suite.cleanup()
    assert not mutations
