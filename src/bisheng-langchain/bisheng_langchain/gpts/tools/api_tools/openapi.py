from typing import Any

from langchain_core.tools import BaseTool
from loguru import logger
from pydantic import BaseModel, create_model

from .base import APIToolBase, Field, MultArgsSchemaTool


class OpenApiTools(APIToolBase):

    def get_real_path(self, path_params: dict|None):
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
                    params[k] = v
                elif params_define[k]['in'] == 'path':
                    path_params[k] = v
                else:
                    json_data[k] = v
            else:
                params[k] = v
        return params, json_data, path_params

    def parse_args_schema(self):
        params = self.params['parameters']
        model_params = {}
        for one in params:
            field_type = one['schema']['type']
            if field_type == 'number':
                field_type = float
            elif field_type == 'integer':
                field_type = int
            elif field_type == 'string':
                field_type = str
            elif field_type == 'boolean':
                field_type = bool
            elif field_type == 'array':
                field_type = list
            elif field_type in {'object', 'dict'}:
                param_object_param = {}
                for param in one['schema']['properties'].keys():
                    field_type = one['schema']['properties'][param]['type']
                    if field_type == 'number':
                        field_type = float
                    elif field_type == 'integer':
                        field_type = int
                    elif field_type == 'string':
                        field_type = str
                    elif field_type == 'boolean':
                        field_type = bool
                    elif field_type == 'array':
                        field_type = list
                    param_object_param[param] = (
                        field_type,
                        Field(description=one['schema']['properties'][param]['description']))
                param_model = create_model(
                    param,
                    __module__='bisheng_langchain.gpts.tools.api_tools.openapi',
                    **param_object_param)
                field_type = param_model
            else:
                raise Exception(f'schema type is not support: {field_type}')
            model_params[one['name']] = (field_type, Field(description=one['description']))
        return create_model('InputArgs',
                            __module__='bisheng_langchain.gpts.tools.api_tools.openapi',
                            __base__=BaseModel,
                            **model_params)

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
        logger.info('api_call url={}', path)
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
