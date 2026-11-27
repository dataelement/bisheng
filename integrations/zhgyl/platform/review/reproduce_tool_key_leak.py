"""Read-only source reproduction with synthetic rows and explicit permission stubs.

Extracts the actual service methods/response masker; does not authenticate to a
platform, read a database, send an upstream request or load any real credential.
"""

import ast
import asyncio
from dataclasses import dataclass, replace
import importlib.util
import json
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import AsyncMock

REPO = Path(__file__).resolve().parents[4]
BACKEND = REPO / "src/backend"


def method(path, cls, names, scope):
    tree = ast.parse(path.read_text())
    node = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
    selected = [
        n
        for n in node.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names
    ]
    for node in selected:
        node.decorator_list = []
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[])),
            str(path),
            "exec",
        ),
        scope,
    )


def leaf(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def main():
    const = leaf(BACKEND / "bisheng/tool/domain/const.py", "review_tool_const")
    masker = leaf(
        BACKEND / "bisheng/utils/mask_data.py", "review_json_masker"
    ).JsonFieldMasker
    response_scope = {
        "json": json,
        "JsonFieldMasker": masker,
        "ToolPresetType": const.ToolPresetType,
    }
    method(
        BACKEND / "bisheng/tool/domain/models/gpts_tools.py",
        "GptsToolsTypeRead",
        {"mask_sensitive_data"},
        response_scope,
    )

    class Read:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

        @classmethod
        def model_validate(cls, row):
            return cls(**row.__dict__)

        def model_dump(self):
            return self.__dict__.copy()

        mask_sensitive_data = response_scope["mask_sensitive_data"]

    @dataclass
    class Actor:
        current_tenant_id: int = 1

    key = "fixture-local-service-credential"
    row = Read(
        id=10,
        name="Synthetic native API",
        tenant_id=1,
        user_id=99,
        api_key=key,
        is_preset=0,
        extra="{}",
        logo="",
        description="",
        server_host="http://synthetic.invalid",
        auth_method=1,
        auth_type="bearer",
        openapi_schema="{}",
        api_location="header",
        parameter_name="Authorization",
    )
    dao = SimpleNamespace(
        aget_tenant_tool_type=AsyncMock(return_value=[row]),
        aget_list_by_type=AsyncMock(return_value=[]),
        update_tool_type=AsyncMock(),
    )
    permission_calls = []

    async def check(user, *, resource_type, resource_ids, actions):
        permission_calls.append(tuple(actions))
        allowed = {"use", "visible"} | ({"edit"} if editor else set())
        return {"10": frozenset(a for a in actions if a in allowed)}

    scope = {
        "ToolPresetType": const.ToolPresetType,
        "get_current_tenant_id": lambda: 1,
        "DEFAULT_TENANT_ID": 1,
        "perf_counter": perf_counter,
        "GptsToolsDao": dao,
        "GptsToolsTypeRead": Read,
        "batch_check_business_actions": check,
        "resolve_permission_actor": AsyncMock(return_value=Actor()),
        "replace": replace,
        "_TOOL_VISIBLE_MAX_RESULTS": 5000,
        "get_f048_runtime": AsyncMock(
            return_value=SimpleNamespace(
                list_visible_objects=AsyncMock(
                    return_value=SimpleNamespace(object_ids=("10",))
                )
            )
        ),
        "logger": SimpleNamespace(info=lambda *args, **kwargs: None),
        "json": json,
        "JsonFieldMasker": masker,
    }
    # Postponed source annotations avoid eager application class imports.
    scope.update(GptsTools=object, GptsToolsType=object)
    method(
        BACKEND / "bisheng/tool/domain/services/tool.py",
        "ToolServices",
        {"get_tool_list", "_update_gpts_tools"},
        scope,
    )
    output = {}
    user = SimpleNamespace(user_id=7, tenant_id=1, is_global_super=False)
    for editor in (False, True):
        for action in ("use", "visible"):
            permission_calls.clear()
            values = await scope["get_tool_list"](
                SimpleNamespace(login_user=user), is_preset=0, action=action
            )
            assert row.api_key == key
            assert values[0].api_key == (key if editor else "********")
            output[action + ("_editor" if editor else "_ordinary")] = {
                "api_key_exposed": values[0].api_key == key,
                "requested_permission_actions": list(permission_calls),
                "database_credential_unchanged": row.api_key == key,
            }
    request = Read(**row.model_dump(), children=[])
    await scope["_update_gpts_tools"](SimpleNamespace(), row, request)
    output["editor_round_trip_preserves_key"] = row.api_key == key
    output["fixed"] = True
    output["scope"] = (
        "actual_source_methods_with_synthetic_dao_and_permission_stubs_only"
    )
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
