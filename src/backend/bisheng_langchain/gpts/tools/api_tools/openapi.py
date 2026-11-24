from typing import Any, Optional

from langchain_core.tools import BaseTool
from loguru import logger

from bisheng_langchain.utils.openapi import (
    convert_openapi_field_value,
    has_null_member,
    resolve_openapi_type,
)
from .base import APIToolBase, MultArgsSchemaTool


class OpenApiTools(APIToolBase):
    api_key: Optional[str] = None
    api_location: Optional[str] = None
    parameter_name: Optional[str] = None

    def get_real_path(self, path_params: dict | None):
        path = self.params['path']
        if path_params:
            path = path.format(**path_params)
        return self.url + path

    def get_request_method(self):
        return self.params['method'].lower()

    @staticmethod
    def _is_blank_optional_value(param_define: dict, value: Any) -> bool:
        if value != '' or param_define.get('required') or param_define.get('in') == 'path':
            return False
        field_type = resolve_openapi_type(param_define.get('schema'))
        # Untyped values may be strings, so "" is only dropped when the type is known.
        return field_type is not None and field_type != 'string'

    @staticmethod
    def _convert_value(param_define: dict, value: Any) -> Any:
        schema = param_define.get('schema')
        if value is None and has_null_member(schema):
            return None
        return convert_openapi_field_value(value, resolve_openapi_type(schema))

    def get_params_json(self, **kwargs):
        params_define = {}
        for one in self.params['parameters']:
            params_define[one['name']] = one

        path_params = {}
        params = {}
        json_data = {}
        for k, v in kwargs.items():
            if params_define.get(k):
                if self._is_blank_optional_value(params_define[k], v):
                    # A blank optional non-string value means "not provided": omit it so the
                    # upstream applies its own default instead of rejecting "" (e.g. integer count).
                    continue
                if params_define[k]['in'] == 'query':
                    params[k] = self._convert_value(params_define[k], v)
                elif params_define[k]['in'] == 'path':
                    path_params[k] = v
                else:
                    json_data[k] = self._convert_value(params_define[k], v)
            else:
                params[k] = v
        # if ('api_location' in self.params and self.params['api_location'] == "query") or \
        #     (hasattr(self, 'api_location') and self.api_location == "query"):
        #     if self.parameter_name:
        #         params.update({self.parameter_name:self.api_key})
        #     elif self.params['parameter_name']:
        #         params.update({self.params['parameter_name']:self.api_key})
        api_location = self.params.get('api_location')
        if (api_location == 'query') or (hasattr(self, 'api_location')
                                         and self.api_location == 'query'):
            parameter_name = getattr(self, 'parameter_name',
                                     None) or self.params.get('parameter_name')
            if parameter_name:
                params.update({parameter_name: self.api_key})
        return params, json_data, path_params

    @staticmethod
    def _field_info(schema: Any, field_type: str | None, description: str) -> dict:
        """JSON schema for one argument. Untyped (any) values carry no "type" key."""
        field_info = {"description": description}
        if field_type is not None:
            field_info["type"] = field_type
        if has_null_member(schema):
            field_info["nullable"] = True
        return field_info

    @staticmethod
    def _items_type(schema: dict) -> str:
        return resolve_openapi_type(schema.get('items')) or 'string'

    def parse_args_schema(self):
        args_schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
        params = self.params['parameters']
        for one in params:
            if one.get('required'):
                args_schema['required'].append(one['name'])
            schema = one.get('schema') or {}
            field_type = resolve_openapi_type(schema)
            if field_type is None or field_type in ['number', 'integer', 'string', 'boolean']:
                # None: anyOf/oneOf or a type array without a single concrete type -> any value.
                field_info = self._field_info(schema, field_type, one['description'])
            elif field_type == 'array':
                field_info = self._field_info(schema, field_type, one['description'])
                field_info["items"] = self._items_type(schema)
            elif field_type in {'object', 'dict'}:
                field_info = self._field_info(schema, "object", one['description'])
                properties = schema.get('properties') or {}
                field_info["properties"] = {}
                if 'properties' not in schema:
                    # An object without declared properties accepts any keys.
                    field_info["additionalProperties"] = True
                for param, param_schema in properties.items():
                    field_type = resolve_openapi_type(param_schema)
                    object_field_info = self._field_info(param_schema, field_type, one['description'])
                    if field_type == 'array':
                        object_field_info["items"] = self._items_type(schema)
                    field_info["properties"][param] = object_field_info
            else:
                raise Exception(f'schema type is not support: {field_type}')
            args_schema[one['name']] = field_info
        return args_schema

    def run(self, **kwargs) -> str:
        """Run query through api and parse result."""
        extra = {}
        if 'proxy' in kwargs:
            extra['proxy'] = kwargs.pop('proxy')

        params, json_data, path_params = self.get_params_json(**kwargs)
        path = self.get_real_path(path_params)
        logger.info('api_call url={}', path)
        method = self.get_request_method()

        if method == 'get':
            resp = self.client.get(path, params=params, **extra)
        elif method == 'post':
            resp = self.client.post(path, params=params, json=json_data, **extra)
        elif method == 'put':
            resp = self.client.put(path, params=params, json=json_data, **extra)
        elif method == 'delete':
            resp = self.client.delete(path, params=params, json=json_data, **extra)
        else:
            raise Exception(f'http method is not support: {method}')
        if resp.status_code != 200:
            logger.info(f'api_call_fail code={resp.status_code} res={resp.text}')
            raise Exception(f'api_call_fail: {resp.status_code} {resp.text}')
        return resp.text

    async def arun(self, **kwargs) -> str:
        """Run query through api and parse result."""
        extra = {}
        if 'proxy' in kwargs:
            extra['proxy'] = kwargs.pop('proxy')

        params, json_data, path_params = self.get_params_json(**kwargs)
        path = self.get_real_path(path_params)
        logger.info('api_call url={} params={}', path, params)
        method = self.get_request_method()

        if method == 'get':
            resp = await self.async_client.aget(path, params=params, **extra)
        elif method == 'post':
            resp = await self.async_client.apost(path, params=params, json=json_data, **extra)
        elif method == 'put':
            resp = await self.async_client.aput(path, params=params, json=json_data, **extra)
        elif method == 'delete':
            resp = await self.async_client.adelete(path, params=params, json=json_data, **extra)
        else:
            raise Exception(f'http method is not support: {method}')
        return resp

    @classmethod
    def get_api_tool(cls, name, **kwargs: Any) -> BaseTool:
        description = kwargs.pop('description', '')
        obj = cls(**kwargs)
        return MultArgsSchemaTool(name=name,
                                  description=description,
                                  func=obj.run,
                                  coroutine=obj.arun,
                                  args_schema=obj.parse_args_schema())
