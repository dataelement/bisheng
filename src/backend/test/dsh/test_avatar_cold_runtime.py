"""Cold process guard: optional avatar code must not load the web user service."""

import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def test_cold_avatar_import_and_runtime_composition_leave_web_user_service_unloaded(tmp_path):
    # A subprocess is essential: other avatar tests intentionally exercise UserService,
    # so sys.modules assertions in the pytest process could conceal eager imports.
    config_file = tmp_path / "empty.yaml"
    config_file.write_text("{}\n", encoding="utf-8")
    script = dedent(
        """
        import asyncio
        import importlib.abc
        import sys
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        target = "bisheng.user.domain.services.user"
        assert target not in sys.modules

        class RejectWebUserService(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "bisheng.user.domain.services.user":
                    raise AssertionError("Web user service imported during cold runtime composition")
                return None

        # Reject rather than stub the module: a fake preloaded module would hide the bug.
        sys.meta_path.insert(0, RejectWebUserService())
        from bisheng.user.domain.services.dsh_avatar import read_dsh_avatar
        assert target not in sys.modules

        from bisheng.core.cache import redis_manager
        from bisheng.dsh.access_runtime import build_runtime
        from bisheng.dsh.config import DshSettings

        async def check():
            redis = SimpleNamespace(async_connection=object())
            with patch.object(redis_manager, "get_redis_client", AsyncMock(return_value=redis)) as factory:
                runtime = await build_runtime(DshSettings())
            factory.assert_awaited_once_with()
            assert runtime.identity.avatar_reader is read_dsh_avatar
            assert runtime.access.identities is runtime.identity
            assert runtime.sessions.identities is runtime.identity
            assert target not in sys.modules
            await runtime.close()

        asyncio.run(check())
        print("cold avatar import and runtime composition passed")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "config": str(config_file), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "cold avatar import and runtime composition passed" in result.stdout
