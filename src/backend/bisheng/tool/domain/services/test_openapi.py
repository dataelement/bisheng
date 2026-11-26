"""Pinned transport for OpenAPI tool tests."""

import json
from urllib.parse import quote, quote_plus

from bisheng.common.errcode.http_error import NotFoundError
from bisheng.common.errcode.tool import ToolDestinationDeniedError, ToolRequestFailedError
from bisheng.core.context.tenant import get_current_tenant_id
from bisheng.permission.application.business_authorization import require_business_action
from bisheng.tool.domain.const import AuthMethod, AuthType, ToolPresetType
from bisheng.tool.domain.models.gpts_tools import GptsToolsDao
from bisheng.tool.domain.services.egress import map_tool_egress_error
from bisheng.tool.domain.services.openapi import OpenApiSchema
from bisheng.tool.domain.services.read_projection import MASK
from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools
from bisheng_langchain.utils import safe_http
from bisheng_langchain.utils.egress_policy import DestinationDenied
from bisheng_langchain.utils.safe_http_errors import RequestFailed, RequestTimeout, ResponseTooLarge


class TestOpenApiTools(OpenApiTools):
    """Do not replace the normal tool executor's transport or contracts."""

    __test__ = False
    encode_path_parameters: bool = False

    async def arun(self, **kwargs) -> str:
        params, json_data, path_params = self.get_params_json(**kwargs)
        if self.encode_path_parameters:
            if any(str(value) in {".", ".."} for value in path_params.values()):
                raise DestinationDenied()
            path_params = {name: quote(str(value), safe="") for name, value in path_params.items()}
        method = self.get_request_method().upper()
        response = await safe_http.arequest(
            method,
            self.get_real_path(path_params),
            headers=self.headers,
            params=params,
            json=json_data if method != "GET" else None,
            timeout=min(self.request_timeout, 30),
        )
        return response.text()


async def run_saved_openapi_test(login_user, tool_type_id: int, operation_id: int, request_params: dict) -> str:
    tenant_id = get_current_tenant_id()
    if tenant_id is None:
        raise NotFoundError()
    tool = await GptsToolsDao.aget_one_tool_type(tool_type_id)
    if not tool or tool.tenant_id != tenant_id or tool.is_delete or tool.is_preset != ToolPresetType.API.value:
        raise NotFoundError()
    await require_business_action(login_user, resource_type="tool", resource_id=tool_type_id, action="edit")

    operation = await GptsToolsDao.aget_one_tool(operation_id)
    if (
        not operation
        or operation.tenant_id != tenant_id
        or operation.type != tool_type_id
        or operation.is_delete
        or operation.is_preset != ToolPresetType.API.value
    ):
        raise NotFoundError()

    extra = json.loads(operation.extra) if isinstance(operation.extra, str) else dict(operation.extra or {})
    path = extra.get("path")
    # A relative operation starts after the saved server authority.
    if not isinstance(path, str) or not path.startswith("/"):
        raise ToolDestinationDeniedError()

    api_key = tool.api_key if tool.auth_method == AuthMethod.API_KEY.value else None
    if api_key == MASK or not tool.server_host:
        raise ToolRequestFailedError()
    extra.update(api_location=None, parameter_name=None)
    if api_key and tool.auth_type == AuthType.CUSTOM.value:
        auth = json.loads(tool.extra or "{}")
        extra.update(api_location=auth.get("api_location"), parameter_name=auth.get("parameter_name"))
    params = OpenApiSchema.parse_openapi_tool_params(
        "test", "", extra, tool.server_host, tool.auth_method, tool.auth_type, api_key
    )
    params.pop("description")
    tester = TestOpenApiTools(encode_path_parameters=True, **params)
    declared = {item["name"] for item in extra["parameters"]}
    try:
        response = await tester.arun(**{name: value for name, value in request_params.items() if name in declared})
    except (DestinationDenied, RequestFailed, RequestTimeout, ResponseTooLarge) as exc:
        raise map_tool_egress_error(exc) from None

    if api_key:
        # Providers may echo credentials in error bodies, including escaped forms.
        variants = {api_key, quote(api_key, safe=""), quote_plus(api_key), json.dumps(api_key)[1:-1]}
        for variant in sorted(variants, key=len, reverse=True):
            response = response.replace(variant, MASK)
    return response
