"""Run isolated production contracts without booting external middleware.

Namespace-only packages bypass eager application registration. All tested leaf
modules remain the real source. Archive infrastructure is replaced explicitly;
this runner does not validate production authentication, storage or deployment.
"""

import argparse
from pathlib import Path
import sys
import types

import pytest


ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "src/backend"


def namespace(name, relative):
    module = types.ModuleType(name)
    module.__path__ = [str(BACKEND / relative)]
    sys.modules[name] = module


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("group", choices=["core", "archive", "d-adapters"])
    group = parser.parse_args().group
    sys.path.insert(0, str(BACKEND))
    if group == "core":
        namespace(
            "bisheng.knowledge.domain.services", "bisheng/knowledge/domain/services"
        )
        tests = [
            "test/knowledge/test_archive_validation.py",
            "test/knowledge/docflow",
            "test/security/test_report_52_55.py",
            "test/knowledge/rag/test_rewrite_local_image_refs.py",
        ]
    elif group == "archive":
        for name, relative in [
            ("bisheng.knowledge.domain.services", "bisheng/knowledge/domain/services"),
            ("bisheng.common.services", "bisheng/common/services"),
            ("bisheng.core.cache", "bisheng/core/cache"),
        ]:
            namespace(name, relative)
        config = types.ModuleType("bisheng.common.services.config_service")
        config.settings = types.SimpleNamespace(get_from_db=lambda *args, **kwargs: {})
        sys.modules[config.__name__] = config
        cache = types.ModuleType("bisheng.core.cache.utils")

        def unused_download(*args, **kwargs):
            raise AssertionError("These cases must not download ordinary files")

        cache.file_download = unused_download
        sys.modules[cache.__name__] = cache
        tests = ["test/knowledge/test_archive_upload_service.py"]
    else:
        tests = [
            "test/linsight/test_zhgyl_d_adapters.py",
            "test/linsight/test_zhgyl_stream_cleanup.py",
        ]
    return pytest.main(["--noconftest", "-q", *[str(BACKEND / test) for test in tests]])


if __name__ == "__main__":
    raise SystemExit(main())
