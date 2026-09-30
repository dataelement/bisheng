import json
from pathlib import Path

import orjson


def test_validation_error_handler_serializes_ctx_value_error():
    main_source = Path(__file__).resolve().parents[2] / "bisheng" / "main.py"
    assert "json.loads(json.dumps(exc.errors(), default=str))" in main_source.read_text()

    errors = [
        {
            "type": "bool_parsing",
            "loc": ("body", "force"),
            "msg": "Input should be a valid boolean",
            "input": "true",
            "ctx": {"error": ValueError("bad bool")},
        }
    ]
    payload = {
        "status_code": 422,
        "status_message": json.loads(json.dumps(errors, default=str)),
    }
    body = orjson.dumps(payload)
    assert b'"status_code":422' in body
    assert b"force" in body
    assert b"bad bool" in body


async def test_unhandled_exception_keeps_original_traceback_in_worker_thread():
    import ast
    import asyncio

    from fastapi import HTTPException, Request, status
    from fastapi.responses import ORJSONResponse
    from loguru import logger

    from bisheng.common.errcode import BaseErrorCode
    from bisheng.common.errcode.filelib_sync import FilelibSyncError

    # 隔离应用启动依赖，直接执行 main.py 中的真实处理函数。
    source = Path(__file__).resolve().parents[2] / "bisheng" / "main.py"
    tree = ast.parse(source.read_text())
    handler_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "handle_http_exception"
    )
    namespace = dict(
        Request=Request,
        ORJSONResponse=ORJSONResponse,
        HTTPException=HTTPException,
        status=status,
        logger=logger,
        BaseErrorCode=BaseErrorCode,
        FilelibSyncError=FilelibSyncError,
    )
    exec(compile(ast.Module(body=[handler_node], type_ignores=[]), str(source), "exec"), namespace)
    try:
        raise ValueError("original failure")
    except ValueError as exc:
        original = exc
    request = Request({"type": "http", "method": "GET", "path": "/probe", "headers": [], "query_string": b""})
    records = []
    sink = logger.add(lambda message: records.append(message.record))
    try:
        response = await asyncio.to_thread(namespace["handle_http_exception"], request, original)
    finally:
        logger.remove(sink)
    assert response.status_code == 500
    record = next(record for record in records if "Unhandled exception" in record["message"])
    assert record["exception"] is not None
    assert record["exception"].value is original
    assert record["exception"].traceback is original.__traceback__
