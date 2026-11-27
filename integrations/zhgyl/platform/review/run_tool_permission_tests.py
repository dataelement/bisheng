"""Run real tool permission tests with the repository's infrastructure pre-mocks.

The RAG tool import is deliberately blocked: this suite exercises tool
permission/projection logic and must never initialize knowledge infrastructure.
No platform session, database, Redis or upstream business API is accessed.
"""

from pathlib import Path
import sys
import types

BACKEND = Path(__file__).resolve().parents[4] / "src/backend"
sys.path.insert(0, str(BACKEND))
# Preserve the real exception class before the repo's optional import pre-mocks.
import bisheng.common.errcode.http_error  # noqa: E402,F401
from test.fixtures.mock_services import premock_import_chain  # noqa: E402

premock_import_chain()

stub = types.ModuleType("bisheng.tool.domain.langchain.linsight_knowledge")


class UnusedKnowledgeTool:
    def __init__(self, *args, **kwargs):
        raise AssertionError("Permission unit tests must not initialize RAG")


stub.SearchKnowledgeBase = UnusedKnowledgeTool
sys.modules[stub.__name__] = stub

import pytest  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(
        pytest.main(["-q", str(BACKEND / "test/tool/test_f048_tool_permissions.py")])
    )
