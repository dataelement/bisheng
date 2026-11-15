"""The actual storage aspect retains its source before thawing exceptions."""

import ast
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from minio.error import S3Error
from urllib3.exceptions import ConnectTimeoutError

from bisheng.common.services.failure_context import FailureContextAdapter


@pytest.mark.parametrize(
    "error,category", [(ConnectTimeoutError("secret"), "object_storage"), (ValueError("bad local argument"), None)]
)
def test_storage_transport_has_storage_source_but_bad_input_does_not(error, category):
    path = Path(__file__).resolve().parents[2] / "bisheng/core/storage/minio/minio_storage.py"
    node = next(
        n for n in ast.parse(path.read_text()).body if isinstance(n, ast.FunctionDef) and n.name == "_storage_metric"
    )
    namespace = {
        "contextmanager": contextmanager,
        "time": time,
        "S3Error": S3Error,
        "FailureContextAdapter": FailureContextAdapter,
        "_classify_storage_exc": lambda e: ("error", None, None),
        "_thaw_s3_error": lambda e: e,
        "emit_metric": lambda *args, **kwargs: None,
    }
    exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])), str(path), "exec"), namespace)
    with pytest.raises(type(error)):
        with namespace["_storage_metric"]("get"):
            raise error
    info = FailureContextAdapter.from_error(error)
    assert (info["category"] if info else None) == category
