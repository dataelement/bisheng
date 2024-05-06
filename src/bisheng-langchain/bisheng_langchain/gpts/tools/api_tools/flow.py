from loguru import logger
from langchain_core.pydantic_v1 import BaseModel, Field
from typing import Any
from .base import APIToolBase
from .base import MultArgsSchemaTool
from langchain_core.tools import BaseTool


class FlowTools(APIToolBase):

    def run(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = {
                'question': query
            }

        url = self.url
        logger.info('api_call url={}', url)
        resp = self.client.post(url, json=self.params)
        if resp.status_code != 200:
            logger.info('api_call_fail res={}', resp.text)
        return resp.text

    async def arun(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = {
                'question': query
            }

        url = self.url
        logger.info('api_call url={}', url)
        resp = await self.async_client.apost(url, json=self.params)
        logger.info(resp)
        return resp

    @classmethod
    def knowledge_retrieve(cls, collection_id: int = None) -> str:    

        flow_id = 'c7985115-a9d2-446a-9c55-40b5728ffb52'
        url = 'http://192.168.106.120:3002/api/v1/process/{}'.format(flow_id)
        input_key = 'inputs'
        params = {
            'tweaks': {
                'ElasticKeywordsSearch-pFFyR': {
                    'collection_id': collection_id
                },
                'Milvus-9KIR6': {
                    'collection_id': collection_id
                }
            }
        }

        class InputArgs(BaseModel):
            query: str = Field(description='questions to ask')

        return cls(url=url, params=params, input_key=input_key, args_schema=InputArgs)
    
    @classmethod
    def get_api_tool(cls, name, **kwargs: Any) -> BaseTool:
        attr_name = name.split('_', 1)[-1]
        class_method = getattr(cls, attr_name)
        function_description = kwargs.get('description','')
        kwargs.pop('description')
        return MultArgsSchemaTool(name=name + '_' +str(kwargs.get('collection_id')),
                                  description=function_description,
                                  func=class_method(**kwargs).run,
                                  coroutine=class_method(**kwargs).arun,
                                  args_schema=class_method(**kwargs).args_schema)
    
