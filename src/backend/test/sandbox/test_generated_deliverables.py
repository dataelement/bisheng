"""Code-interpreter deliverable collection for the daily chat (F016).

The daily chat attaches what a run published under ``output/`` to the answer,
reading it off the executor instead of trusting the link the model writes.
Collection is opt-in, so deep research / workflow / assistant executors keep
their behaviour, and the result handed to the model is unchanged.
"""

from __future__ import annotations

import threading

from bisheng_langchain.gpts.tools.code_interpreter.local_executor import LocalExecutor


def _executor(tmp_path, monkeypatch, *, collect: bool) -> tuple[LocalExecutor, list[str]]:
    exe = LocalExecutor(minio={})
    exe.local_sync_path = str(tmp_path)
    exe.collect_deliverables = collect
    object_names: list[str] = []

    def fake_upload(object_name, file_path):
        object_names.append(object_name)
        return f"http://h/tmp-dir/{object_name}?sig"

    monkeypatch.setattr(exe, "upload_minio", fake_upload)
    return exe, object_names


def _run(exe: LocalExecutor, tmp_path, code: str):
    return exe.run_with_dir(code, dir_path=str(tmp_path), lang="python")


_WRITE_BOTH = (
    "import os\n"
    "os.makedirs('output', exist_ok=True)\n"
    "os.makedirs('scratch', exist_ok=True)\n"
    "open('output/北京今日天气.docx', 'w').write('doc')\n"
    "open('scratch/tmp.csv', 'w').write('a,b')\n"
)


def test_collect_off_by_default(tmp_path, monkeypatch):
    exe = LocalExecutor(minio={})
    assert exe.collect_deliverables is False

    exe, _ = _executor(tmp_path, monkeypatch, collect=False)
    exitcode, _, _ = _run(exe, tmp_path, _WRITE_BOTH)

    assert exitcode == 0
    assert exe.published_deliverables == []


def test_only_output_files_collected(tmp_path, monkeypatch):
    (tmp_path / "需求文档.md").write_text("user upload")
    exe, _ = _executor(tmp_path, monkeypatch, collect=True)

    exitcode, _, _ = _run(exe, tmp_path, _WRITE_BOTH + "open('需求文档.md', 'a').write(' edited')\n")

    assert exitcode == 0
    assert [d["path"] for d in exe.published_deliverables] == ["output/北京今日天气.docx"]
    entry = exe.published_deliverables[0]
    assert entry["name"] == "北京今日天气.docx"
    assert entry["size"] == 3
    assert entry["url"].startswith("http://h/tmp-dir/")


def test_root_file_collected_after_relocation(tmp_path, monkeypatch):
    exe, _ = _executor(tmp_path, monkeypatch, collect=True)

    exitcode, _, _ = _run(exe, tmp_path, "open('report.xlsx', 'w').write('x')")

    assert exitcode == 0
    assert [d["path"] for d in exe.published_deliverables] == ["output/report.xlsx"]


def test_failed_run_collects_nothing(tmp_path, monkeypatch):
    exe, _ = _executor(tmp_path, monkeypatch, collect=True)

    exitcode, _, _ = _run(exe, tmp_path, _WRITE_BOTH + "raise SystemExit(3)\n")

    assert exitcode != 0
    assert exe.published_deliverables == []


def test_object_name_has_single_dot(tmp_path, monkeypatch):
    exe, object_names = _executor(tmp_path, monkeypatch, collect=False)

    _run(exe, tmp_path, _WRITE_BOTH)

    assert object_names
    for name in object_names:
        assert ".." not in name
    assert any(name.endswith(".docx") for name in object_names)


def test_file_list_return_unchanged(tmp_path, monkeypatch):
    exe, _ = _executor(tmp_path, monkeypatch, collect=True)

    _, _, file_list = _run(exe, tmp_path, _WRITE_BOTH)

    assert len(file_list) == 2
    assert all(isinstance(url, str) for url in file_list)


def test_parallel_publishes_keep_all_entries(tmp_path, monkeypatch):
    exe, _ = _executor(tmp_path, monkeypatch, collect=True)
    (tmp_path / "output").mkdir()
    names = [f"f{i:02d}.txt" for i in range(40)]
    for name in names:
        (tmp_path / "output" / name).write_text("x")

    threads = [
        threading.Thread(target=exe._publish_generated_files, args=(str(tmp_path), [f"output/{name}"]))
        for name in names
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(d["name"] for d in exe.published_deliverables) == names
