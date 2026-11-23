"""Pinned transport used only by the unsaved OpenAPI test endpoint."""

from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools
from bisheng_langchain.utils import safe_http


class TestOpenApiTools(OpenApiTools):
    """Do not replace the normal tool executor's transport or contracts."""

    __test__ = False

    async def arun(self, **kwargs) -> str:
        params, json_data, path_params = self.get_params_json(**kwargs)
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
