"""Saved OpenAPI execution with bounded, non-logging transport."""

import httpx
from pydantic import Field

from bisheng.common.errcode.dsh import (
    DshToolExecutionTimeoutError,
    DshToolOutputTooLargeError,
    DshToolResultInvalidError,
    DshToolUpstreamFailedError,
)
from bisheng.tool.domain.services.saved_schema import validate_destination
from bisheng.utils.private_http_logs import private_http_logs
from bisheng_langchain.gpts.tools.api_tools.openapi import OpenApiTools


class BoundedOpenApiTools(OpenApiTools):
    max_output_bytes: int = Field(ge=1, le=1048576)

    def parse_args_schema(self):
        # Arguments are validated by SavedToolSchema before execution.
        return {"type": "object"}

    def _split_arguments(self, kwargs):
        """Place validated arguments as-is; the legacy mapper would coerce numbers to float."""
        locations = {p["name"]: p["in"] for p in self.params["parameters"]}
        params = {k: v for k, v in kwargs.items() if locations.get(k) != "body"}
        body = {k: v for k, v in kwargs.items() if locations.get(k) == "body"}
        if self.params.get("api_location") == "query" or self.api_location == "query":
            name = self.parameter_name or self.params.get("parameter_name")
            if name:
                params[name] = self.api_key
        return params, body

    async def arun(self, **kwargs):
        with private_http_logs():
            return await self._request(**kwargs)

    async def _request(self, **kwargs):
        params, json_data = self._split_arguments(kwargs)
        url = validate_destination(self.get_real_path(None))
        headers = {**self.headers, "Accept-Encoding": "identity"}
        try:
            async with httpx.AsyncClient(
                headers=headers, timeout=self.request_timeout, follow_redirects=False, trust_env=False
            ) as client:
                async with client.stream(
                    self.get_request_method(),
                    url,
                    params=params,
                    json=json_data if self.get_request_method() != "get" else None,
                ) as response:
                    if (
                        not 200 <= response.status_code < 300
                        or response.headers.get("content-encoding", "identity").lower() != "identity"
                    ):
                        raise DshToolUpstreamFailedError()
                    length = response.headers.get("content-length")
                    if length is not None and int(length) > self.max_output_bytes:
                        raise DshToolOutputTooLargeError()
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=min(8192, self.max_output_bytes + 1)):
                        if len(body) + len(chunk) > self.max_output_bytes:
                            raise DshToolOutputTooLargeError()
                        body.extend(chunk)
                    try:
                        return body.decode("utf-8", errors="strict")
                    except UnicodeError:
                        raise DshToolResultInvalidError() from None
        except httpx.TimeoutException:
            raise DshToolExecutionTimeoutError() from None
        except (httpx.HTTPError, ValueError):
            raise DshToolUpstreamFailedError() from None
