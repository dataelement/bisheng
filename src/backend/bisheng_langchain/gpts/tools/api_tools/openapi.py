from typing import Any, Optional

from langchain_core.tools import BaseTool
from loguru import logger

from bisheng_langchain.utils.openapi import (
    convert_openapi_field_value,
    is_nullable,
    resolve_openapi_type,
)
from .base import APIToolBase, MultArgsSchemaTool

_JSON_TYPES = {'number', 'integer', 'string', 'boolean', 'array', 'object'}


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
        if value is None and is_nullable(schema):
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

    @classmethod
    def _json_schema(cls, schema: Any, description: str | None = None) -> dict:
        """Convert one OpenAPI schema to the standard JSON Schema that is sent to the model.

        Only standard JSON Schema keywords are written. A nullable value (OpenAPI 3.0
        ``nullable: true``, a 3.1 type array with "null", or an anyOf/oneOf null branch)
        becomes a type array such as ``["integer", "null"]``. An untyped value (no type,
        or a union of different types) has no "type" key, so it accepts any value.
        """
        schema = schema if isinstance(schema, dict) else {}
        field_type = resolve_openapi_type(schema)
        if field_type == 'dict':
            field_type = 'object'
        json_schema = {}
        if description is not None:
            json_schema['description'] = description
        if field_type not in _JSON_TYPES:
            # Untyped, or a type that JSON Schema does not know: accept any value.
            return json_schema
        if field_type == 'array':
            items = schema.get('items')
            json_schema['items'] = cls._json_schema(items) if isinstance(items, dict) else {'type': 'string'}
        elif field_type == 'object':
            properties = schema.get('properties')
            properties = properties if isinstance(properties, dict) else {}
            json_schema['properties'] = {
                name: cls._json_schema(prop, prop.get('description') if isinstance(prop, dict) else None)
                for name, prop in properties.items()
            }
            required = schema.get('required')
            if isinstance(required, list):
                required = [name for name in required if name in properties]
                if required:
                    json_schema['required'] = required
            if 'properties' not in schema:
                # An object without declared properties accepts any keys.
                json_schema['additionalProperties'] = True
        json_schema['type'] = [field_type, 'null'] if is_nullable(schema) else field_type
        return json_schema

    def parse_args_schema(self):
        """JSON Schema of the tool arguments, in the standard form that langchain sends to the model.

        The arguments must be under "properties": langchain reads ``args_schema["properties"]``
        for the ReAct text and sends the dict unchanged as the function parameters.
        """
        args_schema = {
            "type": "object",
            "properties": {},
            "required": []
        }
        for one in self.params['parameters']:
            if one.get('required'):
                args_schema['required'].append(one['name'])
            field_type = resolve_openapi_type(one.get('schema'))
            if field_type is not None and field_type not in _JSON_TYPES and field_type != 'dict':
                raise Exception(f'schema type is not support: {field_type}')
            args_schema['properties'][one['name']] = self._json_schema(one.get('schema'),
                                                                       one.get('description', ''))
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
