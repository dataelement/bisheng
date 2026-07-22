from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bisheng.knowledge.pdf.validator import PdfValidationError, validate_pdf
from bisheng.knowledge.pdf.watermark import PdfWatermarkSpec, apply_pdf_watermark


class PdfWatermarkWorkerError(RuntimeError):
    """隔离水印进程执行失败。"""


class PdfWatermarkWorkerTimeout(PdfWatermarkWorkerError):
    """隔离水印进程超过生成截止时间。"""


@dataclass(frozen=True)
class PdfWatermarkWorkerResult:
    page_count: int
    artifact_size: int
    raw_stdout: str = ""


def _worker_environment() -> dict[str, str]:
    backend_root = str(Path(__file__).resolve().parents[3])
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": backend_root,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "LC_ALL": os.environ.get("LC_ALL", os.environ.get("LANG", "C.UTF-8")),
    }
    return {key: value for key, value in environment.items() if value}


def _serialize_spec(spec: PdfWatermarkSpec) -> str:
    return json.dumps(
        {
            "lines": list(spec.lines),
            "rotation": spec.rotation,
            "opacity": spec.opacity,
            "font_size": spec.font_size,
            "horizontal_gap": spec.horizontal_gap,
            "vertical_gap": spec.vertical_gap,
            "color": list(spec.color),
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )


def run_watermark_worker(
    *,
    input_path: str | Path,
    output_path: str | Path,
    spec: PdfWatermarkSpec,
    timeout_seconds: float,
    terminate_grace_seconds: float,
    popen_factory: Callable[..., Any] = subprocess.Popen,
    validate_output: bool = True,
) -> PdfWatermarkWorkerResult:
    source_path = Path(input_path).resolve()
    target_path = Path(output_path).resolve()
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.unlink(missing_ok=True)
    command = [
        sys.executable,
        "-m",
        "bisheng.knowledge.pdf.watermark_worker",
        "--input",
        str(source_path),
        "--output",
        str(target_path),
    ]
    process = popen_factory(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(target_path.parent),
        env=_worker_environment(),
        start_new_session=True,
    )
    try:
        stdout, _stderr = process.communicate(input=_serialize_spec(spec), timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.communicate(timeout=terminate_grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
        target_path.unlink(missing_ok=True)
        raise PdfWatermarkWorkerTimeout("watermark worker timed out") from None

    if process.returncode != 0:
        target_path.unlink(missing_ok=True)
        raise PdfWatermarkWorkerError("watermark worker failed")
    try:
        metadata = json.loads(stdout)
        page_count = int(metadata["page_count"])
        artifact_size = int(metadata["artifact_size"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        target_path.unlink(missing_ok=True)
        raise PdfWatermarkWorkerError("watermark worker returned invalid metadata") from None

    if validate_output:
        try:
            validation = validate_pdf(target_path)
        except PdfValidationError:
            target_path.unlink(missing_ok=True)
            raise PdfWatermarkWorkerError("watermark worker output is invalid") from None
        if validation.page_count != page_count or validation.artifact_size != artifact_size:
            target_path.unlink(missing_ok=True)
            raise PdfWatermarkWorkerError("watermark worker metadata mismatch")
    return PdfWatermarkWorkerResult(
        page_count=page_count,
        artifact_size=artifact_size,
        raw_stdout=stdout,
    )


def _parse_spec(payload: object) -> PdfWatermarkSpec:
    if not isinstance(payload, dict):
        raise ValueError("invalid worker spec")
    color = payload.get("color", (0.45, 0.45, 0.45))
    return PdfWatermarkSpec(
        lines=tuple(payload.get("lines", ())),
        rotation=float(payload.get("rotation", -35.0)),
        opacity=float(payload.get("opacity", 0.11)),
        font_size=float(payload.get("font_size", 12.0)),
        horizontal_gap=float(payload.get("horizontal_gap", 240.0)),
        vertical_gap=float(payload.get("vertical_gap", 180.0)),
        color=tuple(float(item) for item in color),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    output_path = Path(args.output).resolve()
    try:
        payload = json.loads(sys.stdin.read())
        result = apply_pdf_watermark(args.input, output_path, _parse_spec(payload))
        sys.stdout.write(
            json.dumps(
                {"page_count": result.page_count, "artifact_size": result.artifact_size},
                separators=(",", ":"),
            )
        )
        return 0
    except Exception:
        output_path.unlink(missing_ok=True)
        sys.stderr.write("watermark worker failed\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
