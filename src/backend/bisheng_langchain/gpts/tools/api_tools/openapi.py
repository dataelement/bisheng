from typing import Any, Optional

from langchain_core.tools import BaseTool
from loguru import logger

from bisheng_langchain.utils.openapi import convert_openapi_field_value
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

    def get_params_json(self, **kwargs):
        params_define = {}
        for one in self.params['parameters']:
            params_define[one['name']] = one

        path_params = {}
        params = {}
        json_data = {}
        for k, v in kwargs.items():
            if params_define.get(k):
                if params_define[k]['in'] == 'query':
                    field_type = params_define[k]['schema']['type']
                    params[k] = convert_openapi_field_value(v, field_type)
                elif params_define[k]['in'] == 'path':
                    path_params[k] = v
                else:
                    field_type = params_define[k]['schema']['type']
                    json_data[k] = convert_openapi_field_value(v, field_type)
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
            field_type = one['schema']['type']
            if field_type in ['number', 'integer', 'string', 'boolean']:
                field_info = {
                    "type": field_type,
                    "description": one['description']
                }
            elif field_type == 'array':
                field_info = {
                    "type": field_type,
                    "items": one['schema'].get('items', {}).get('type', 'string'),
                    "description": one['description']
                }
            elif field_type in {'object', 'dict'}:
                field_info = {
                    "type": "object",
                    "description": one['description'],
                    "properties": {}
                }
                for param in one['schema']['properties'].keys():
                    field_type = one['schema']['properties'][param]['type']
                    if field_type in ['number', 'integer', 'string', 'boolean']:
                        object_field_info = {
                            "type": field_type,
                            "description": one['description']
                        }
                    elif field_type == 'array':
                        object_field_info = {
                            "type": field_type,
                            "items": one['schema'].get('items', {}).get('type', 'string'),
                            "description": one['description']
                        }
                    else:
                        object_field_info = {
                            "type": field_type,
                            "description": one['description']
                        }
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
