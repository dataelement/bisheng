"""Application pack imports freeze the server-verified concrete scope (AC-16)."""

import importlib.util
import io
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "f114_materials_tool", Path(__file__).parents[1] / "tools/runtime_materials.py"
)
materials = importlib.util.module_from_spec(spec)
spec.loader.exec_module(materials)


@pytest.mark.parametrize("scope", ["3", None, "all", "0"])
def test_private_pack_uses_verified_scope_and_never_silently_retries(monkeypatch, tmp_path, scope):
    """AC-16、AC-17、AC-20: malformed/missing scope causes no upload, valid scope pins one write."""
    calls = []

    class Response(io.BytesIO):
        headers = {"X-Management-Tenant": scope} if scope is not None else {}

    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            return Response(json.dumps({"status_code": 200, "data": {"app_id": "app"}}).encode())

    monkeypatch.setenv("BISHENG_MANAGEMENT_TOKEN", "not-a-real-session")
    monkeypatch.setattr(materials.urllib.request, "build_opener", lambda *args: Opener())
    pack = tmp_path / "pack.tar.gz"
    pack.write_bytes(b"not-uploaded-to-network")
    if scope == "3":
        materials.request("https://example.test", "/api/v1/apps/app/runtime/materials?profile=p", file=pack)
        assert len(calls) == 2 and calls[0].get_method() == "GET"
        assert calls[1].get_header("X-management-tenant") == "3"
    else:
        with pytest.raises(ValueError, match="management_scope_unavailable"):
            materials.request("https://example.test", "/api/v1/apps/app/runtime/materials?profile=p", file=pack)
        assert len(calls) == 1 and calls[0].get_method() == "GET"
