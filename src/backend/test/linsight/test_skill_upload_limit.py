"""The skill upload and unpacked caps are read from 系统配置.

``linsight.skill_upload_max_size_mb`` / ``linsight.skill_unpacked_max_size_mb``;
MAX_BUNDLE_SIZE / MAX_UNPACKED_SIZE are only the fallbacks. Both the endpoint's early
read check and the service's parse step must honour the configured upload value, and
/upload-limit must report the effective values of both.
"""

from types import SimpleNamespace

import pytest

from bisheng.common.errcode.linsight import SkillFileTooLargeError
from bisheng.linsight.api.endpoints import skill as skill_endpoint
from bisheng.linsight.domain.services import skill_store
from bisheng.linsight.domain.services.skill_service import SkillService

MB = 1024 * 1024


def _conf(monkeypatch, megabytes, unpacked_megabytes=None):
    # bisheng_settings is a pydantic BaseModel with validate_assignment=True, so an
    # instance-level setattr on a method is rejected ("no such attribute" — pydantic
    # only allows assigning declared fields). Patch the class method instead.
    fields = {"skill_upload_max_size_mb": megabytes}
    if unpacked_megabytes is not None:
        fields["skill_unpacked_max_size_mb"] = unpacked_megabytes

    async def _aget_linsight_conf(self):
        return SimpleNamespace(**fields)

    monkeypatch.setattr(type(skill_store.bisheng_settings), "aget_linsight_conf", _aget_linsight_conf)


async def test_limit_comes_from_system_config(monkeypatch):
    _conf(monkeypatch, 50)
    assert await skill_store.resolve_skill_upload_limit() == 50 * MB


async def test_unreadable_or_nonsense_config_falls_back_to_default(monkeypatch):
    async def _boom(self):
        raise RuntimeError("config store down")

    monkeypatch.setattr(type(skill_store.bisheng_settings), "aget_linsight_conf", _boom)
    assert await skill_store.resolve_skill_upload_limit() == skill_store.MAX_BUNDLE_SIZE

    _conf(monkeypatch, 0)
    assert await skill_store.resolve_skill_upload_limit() == skill_store.MAX_BUNDLE_SIZE


async def test_endpoint_reads_with_the_configured_cap(monkeypatch):
    class _Upload:
        async def read(self):
            return b"x" * (MB + 1)

    _conf(monkeypatch, 1)
    with pytest.raises(SkillFileTooLargeError):
        await skill_endpoint._read_upload(_Upload())

    _conf(monkeypatch, 2)
    assert len(await skill_endpoint._read_upload(_Upload())) == MB + 1


def test_parse_upload_honours_max_size():
    svc = object.__new__(SkillService)
    payload = b"---\nname: demo\ndescription: d\n---\nbody"

    with pytest.raises(SkillFileTooLargeError):
        svc._parse_upload("SKILL.md", payload, max_size=len(payload) - 1)


async def test_upload_limit_route_precedes_the_name_route_and_reports_the_cap(monkeypatch):
    paths = [route.path for route in skill_endpoint.router.routes]
    assert paths.index("/skill/upload-limit") < paths.index("/skill/{name}")

    _conf(monkeypatch, 7, unpacked_megabytes=300)
    body = await skill_endpoint.get_upload_limit(login_user=SimpleNamespace(user_id=1, tenant_id=1))
    data = body.data if hasattr(body, "data") else body["data"]
    assert data["max_size_mb"] == 7 and data["max_size_bytes"] == 7 * MB
    assert data["max_unpacked_mb"] == 300 and data["max_unpacked_bytes"] == 300 * MB


async def test_unpacked_limit_comes_from_system_config(monkeypatch):
    _conf(monkeypatch, 10, unpacked_megabytes=300)
    assert await skill_store.resolve_skill_unpacked_limit() == 300 * MB


async def test_unpacked_limit_falls_back_to_the_default(monkeypatch):
    # A deployment whose stored 系统配置 predates the key: only the upload cap is present.
    _conf(monkeypatch, 10)
    assert await skill_store.resolve_skill_unpacked_limit() == skill_store.MAX_UNPACKED_SIZE

    _conf(monkeypatch, 10, unpacked_megabytes=0)
    assert await skill_store.resolve_skill_unpacked_limit() == skill_store.MAX_UNPACKED_SIZE


async def test_unpacked_limit_never_below_the_upload_limit(monkeypatch):
    # Raising only the upload cap must not strand files that pass it (a stored,
    # uncompressed archive unpacks to about its own size).
    _conf(monkeypatch, 800, unpacked_megabytes=100)
    assert await skill_store.resolve_skill_unpacked_limit() == 800 * MB


async def test_unpacked_limit_clamped_to_the_ceiling(monkeypatch):
    _conf(monkeypatch, 10, unpacked_megabytes=50_000)
    assert await skill_store.resolve_skill_unpacked_limit() == skill_store.MAX_UNPACKED_CEILING
