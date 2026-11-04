"""Execute two real local turns through workspace persistence and delivery."""

import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from minio.error import S3Error

from bisheng.linsight.domain import utils
from bisheng.linsight.domain.models.linsight_session_version import LinsightSessionVersion
from bisheng.linsight.domain.services.workspace_backend import WorkspaceBackend, seed_workspace_from_previous
from bisheng.linsight.domain.task_exec import LinsightWorkflowTask
from bisheng.tool.domain.models.gpts_tools import GptsTools, GptsToolsDao
from bisheng.tool.domain.services.executor import ToolExecutor
from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor


class MemoryStorage:
    """Persist object bytes independently of either turn's disposable directory."""

    bucket = "bisheng"

    def __init__(self):
        self.objects = {}
        self.minio_client_sync = self

    def fput_object(self, bucket_name, object_name, file_path):
        self.objects[object_name] = Path(file_path).read_bytes()

    async def put_object(self, bucket_name, object_name, file):
        self.fput_object(bucket_name, object_name, file)

    def list_objects(self, bucket, prefix="", recursive=True):
        return iter(
            [
                SimpleNamespace(object_name=k, size=len(v), is_dir=False)
                for k, v in self.objects.items()
                if k.startswith(prefix)
            ]
        )

    def get_object_sync(self, bucket_name, object_name):
        return self.objects.get(object_name)

    def copy_object_sync(self, source_bucket, source_object, dest_bucket, dest_object):
        if source_object not in self.objects:
            raise S3Error("NoSuchKey", "missing", source_object, "test", "test", None)
        self.objects[dest_object] = self.objects[source_object]


@pytest.mark.parametrize("selected", [False, True])
async def test_local_files_survive_cleanup_and_followup(monkeypatch, tmp_path, selected):
    storage = MemoryStorage()
    category = SimpleNamespace(id=6, tenant_id=7, extra={"type": "local"})
    row = GptsTools(id=6, type=6, tool_key="bisheng_code_interpreter")
    monkeypatch.setattr(GptsToolsDao, "aget_tool_by_tool_key", AsyncMock(return_value=row))
    monkeypatch.setattr(GptsToolsDao, "aget_one_tool_type", AsyncMock(return_value=category))
    monkeypatch.setattr(ToolExecutor, "_ensure_use_permission_async", AsyncMock())
    monkeypatch.setattr(
        ToolExecutor,
        "init_by_tool_id",
        AsyncMock(side_effect=lambda tool, **kwargs: ToolExecutor._init_preset_tool(tool, category)),
    )
    monkeypatch.setattr(LocalExecutor, "_minio_client", lambda self: storage)
    # Font cache rewriting is unrelated to these plain Python/CSV scripts.
    monkeypatch.setattr(LocalExecutor, "insert_set_font_code", staticmethod(lambda code: code))
    monkeypatch.setattr(utils, "get_minio_storage", AsyncMock(return_value=storage))
    monkeypatch.setattr("bisheng.linsight.domain.task_exec.get_minio_storage", AsyncMock(return_value=storage))

    async def prepare(svid):
        folder = tmp_path / svid
        folder.mkdir()
        session = LinsightSessionVersion(
            id=svid,
            session_id="chat-1",
            user_id=42,
            tenant_id=7,
            question="Update the report",
            tools=[{"children": [{"id": 6}]}] if selected else [],
        )
        task = LinsightWorkflowTask.__new__(LinsightWorkflowTask)
        task.file_dir = str(folder)
        task._baseline_files = {}
        task.llm = object()
        (tool,) = await task._generate_tools(session)
        return folder, session, task, tool

    storage.objects["workspace/first/uploads/source.csv"] = b"amount\n3\n4\n"
    first, session, task, tool = await prepare("first")
    result = tool.invoke(
        {
            "python_code": (
                "from pathlib import Path\n"
                "values = Path('uploads/source.csv').read_text().splitlines()[1:]\n"
                "Path('output').mkdir(exist_ok=True)\n"
                "Path('output/report.csv').write_text('total\\n' + str(sum(map(int, values))) + '\\n')\n"
                "print('saved')\n"
            )
        }
    )
    assert result["exitcode"] == 0
    assert result["file_list"] == ["/output/report.csv"]
    assert storage.objects["workspace/first/output/report.csv"] == b"total\n7\n"
    backend = WorkspaceBackend("first", storage, str(first))
    assert "7" in backend.read("/output/report.csv").file_data["content"]
    delivered = await utils.get_final_result_file(
        session,
        await utils.read_file_directory(str(first)),
        task._baseline_files,
    )
    assert [item["file_name"] for item in delivered] == ["report.csv"]
    assert storage.objects[delivered[0]["file_url"]] == b"total\n7\n"
    shutil.rmtree(first)

    assert await seed_workspace_from_previous(storage, "first", "followup") == 2
    second, session, task, tool = await prepare("followup")
    assert (second / "uploads/source.csv").read_bytes() == b"amount\n3\n4\n"
    assert (second / "output/report.csv").read_bytes() == b"total\n7\n"
    assert (
        await utils.get_final_result_file(
            session,
            await utils.read_file_directory(str(second)),
            task._baseline_files,
        )
        == []
    )
    result = tool.invoke(
        {
            "python_code": (
                "from pathlib import Path\n"
                "p = Path('output/report.csv')\n"
                "value = int(p.read_text().splitlines()[1])\n"
                "p.write_text('total\\n' + str(value * 2) + '\\n')\n"
                "print('updated')\n"
            )
        }
    )
    assert result["exitcode"] == 0
    assert result["file_list"] == ["/output/report.csv"]
    assert storage.objects["workspace/followup/output/report.csv"] == b"total\n14\n"
    assert storage.objects["workspace/first/output/report.csv"] == b"total\n7\n"
    delivered = await utils.get_final_result_file(
        session,
        await utils.read_file_directory(str(second)),
        task._baseline_files,
    )
    assert [item["file_name"] for item in delivered] == ["report.csv"]
    assert storage.objects[delivered[0]["file_url"]] == b"total\n14\n"
