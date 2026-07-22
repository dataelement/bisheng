from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import fitz
import pytest

from bisheng.knowledge.pdf.watermark import PdfWatermarkSpec
from bisheng.knowledge.pdf.watermark_worker import (
    PdfWatermarkWorkerError,
    PdfWatermarkWorkerTimeout,
    run_watermark_worker,
)


def _create_source(path: Path) -> None:
    document = fitz.open()
    document.new_page().insert_text((72, 72), "worker source")
    document.save(path)
    document.close()


def _spec() -> PdfWatermarkSpec:
    return PdfWatermarkSpec(
        lines=(
            "敏感部门-敏感姓名--SECRET-001-2026-07-21",
            "首钢股份内部资料，严禁外传，违者必究",
        )
    )


def test_worker_generates_pdf_and_returns_only_safe_metadata(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    _create_source(source)

    result = run_watermark_worker(
        input_path=source,
        output_path=output,
        spec=_spec(),
        timeout_seconds=10,
        terminate_grace_seconds=0.2,
    )

    assert output.is_file()
    assert result.page_count == 1
    assert result.artifact_size == output.stat().st_size
    assert "敏感姓名" not in result.raw_stdout
    assert "SECRET-001" not in result.raw_stdout


def test_worker_identity_is_sent_through_stdin_not_argv_or_environment(tmp_path: Path) -> None:
    captured: dict = {}

    class FakeProcess:
        returncode = 0

        def communicate(self, input=None, timeout=None):
            captured["stdin"] = input
            captured["timeout"] = timeout
            return json.dumps({"page_count": 1, "artifact_size": 10}), ""

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return FakeProcess()

    output = tmp_path / "output.pdf"
    run_watermark_worker(
        input_path=tmp_path / "source.pdf",
        output_path=output,
        spec=_spec(),
        timeout_seconds=5,
        terminate_grace_seconds=0.1,
        popen_factory=fake_popen,
        validate_output=False,
    )

    command_text = " ".join(captured["command"])
    environment_text = json.dumps(captured["kwargs"]["env"], ensure_ascii=False)
    assert "敏感姓名" not in command_text
    assert "SECRET-001" not in command_text
    assert "敏感姓名" not in environment_text
    assert "SECRET-001" not in environment_text
    assert "敏感姓名" in captured["stdin"]
    assert captured["kwargs"]["cwd"] == str(tmp_path.resolve())


def test_worker_failure_does_not_echo_spec_and_removes_partial_output(tmp_path: Path) -> None:
    source = tmp_path / "broken.pdf"
    output = tmp_path / "partial.pdf"
    source.write_bytes(b"broken")
    output.write_bytes(b"partial")

    with pytest.raises(PdfWatermarkWorkerError) as exc_info:
        run_watermark_worker(
            input_path=source,
            output_path=output,
            spec=_spec(),
            timeout_seconds=5,
            terminate_grace_seconds=0.2,
        )

    assert "敏感姓名" not in str(exc_info.value)
    assert "SECRET-001" not in str(exc_info.value)
    assert not output.exists()


def test_worker_timeout_terminates_then_kills_and_reaps(tmp_path: Path) -> None:
    calls: list[str] = []

    class SlowProcess:
        returncode = None

        def __init__(self) -> None:
            self.communicate_calls = 0

        def communicate(self, input=None, timeout=None):
            self.communicate_calls += 1
            calls.append(f"communicate:{timeout}")
            if self.communicate_calls < 3:
                raise subprocess.TimeoutExpired(cmd="worker", timeout=timeout)
            self.returncode = -9
            return "", ""

        def terminate(self):
            calls.append("terminate")

        def kill(self):
            calls.append("kill")

    process = SlowProcess()

    with pytest.raises(PdfWatermarkWorkerTimeout):
        run_watermark_worker(
            input_path=tmp_path / "source.pdf",
            output_path=tmp_path / "output.pdf",
            spec=_spec(),
            timeout_seconds=0.01,
            terminate_grace_seconds=0.01,
            popen_factory=lambda *_args, **_kwargs: process,
        )

    assert calls == ["communicate:0.01", "terminate", "communicate:0.01", "kill", "communicate:None"]


def test_worker_cli_rejects_invalid_stdin_without_echoing_sensitive_text(tmp_path: Path) -> None:
    source = tmp_path / "source.pdf"
    output = tmp_path / "output.pdf"
    _create_source(source)
    payload = '{"lines":["敏感姓名"]}'

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "bisheng.knowledge.pdf.watermark_worker",
            "--input",
            str(source),
            "--output",
            str(output),
        ],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode != 0
    assert "敏感姓名" not in completed.stdout + completed.stderr
    assert "SECRET-001" not in completed.stdout + completed.stderr
    assert not output.exists()
