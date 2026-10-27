"""Addresses and names shared by the release suite. Secrets stay in the environment."""

from __future__ import annotations

import os

SANDBOX_URL = os.environ.get("SANDBOX_URL", "http://127.0.0.1:8080").rstrip("/")
SANDBOX_TOKEN = os.environ.get("SANDBOX_TOKEN", "bisheng-sandbox-local")
API_BASE = os.environ.get("E2E_API_BASE", "http://127.0.0.1:7860/api/v1").rstrip("/")
FRONTEND_ORIGIN = os.environ.get("BISHENG_FRONTEND_ORIGIN", "http://127.0.0.1:3001").rstrip("/")
TOOL_NAME = "bisheng_code_interpreter"
SUM_PROMPT = "必须用代码工具执行 print(sum([1,2,3]))，不要心算。"
# Seeded in the current environment: 沙箱发布测试代码工具 / 代码助手 / 代码节点.
WORKFLOW_ID = os.environ.get("BISHENG_RELEASE_WORKFLOW_ID") or "520d961f49664b0eb8b588fdc9421148"
ASSISTANT_ID = os.environ.get("BISHENG_RELEASE_ASSISTANT_ID") or "e61c44f5d16c492392652f593e5594ec"
CODE_WORKFLOW_ID = os.environ.get("BISHENG_RELEASE_CODE_WORKFLOW_ID") or "7e3d3ff4c5464f1eaea6519d45bdc53c"
# Seeded built-in bundle. The task copies it to /skills/bisheng-docx/SKILL.md.
SKILL_FILE = os.environ.get("BISHENG_RELEASE_SKILL_FILE", "bisheng-docx/SKILL.md")
FIXED_MODEL = os.environ.get("BISHENG_RELEASE_FIXED_MODEL", "1")
PAGE_LABELS = {
    "executionLocalLabel": "本地隔离运行",
    "executionContainerLabel": "沙箱运行",
    "executionE2bLabel": "E2B沙箱运行",
}
