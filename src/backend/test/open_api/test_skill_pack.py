from io import BytesIO
from zipfile import ZipFile

import pytest

from bisheng.common.errcode.open_api import ApiCredentialNotFoundError
from bisheng.open_api.domain.services.skill_pack_service import SkillPackService


def test_pack_is_deterministic_safe_and_instance_rendered():
    first = SkillPackService.build("bisheng-knowledge-search", base_url="https://example.test/base")
    second = SkillPackService.build("bisheng-knowledge-search", base_url="https://example.test/base")
    assert first == second

    with ZipFile(BytesIO(first)) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(not name.startswith("/") and ".." not in name.split("/") for name in names)
        skill = archive.read("bisheng-knowledge-search/SKILL.md").decode()
        security = archive.read("bisheng-knowledge-search/SECURITY.md").decode()
        script = archive.read("bisheng-knowledge-search/scripts/search.py").decode()

    assert "https://example.test/base" in skill
    assert "https://example.test" in security
    assert "/api/v2/filelib/retrieve" in script
    assert "BISHENG_API_KEY" in script
    assert "X-Bisheng" not in first.decode("latin-1")


def test_pack_name_is_allowlisted():
    with pytest.raises(ApiCredentialNotFoundError):
        SkillPackService.build("../secret", base_url="https://example.test")
