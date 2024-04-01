from loguru import logger
from pydantic import BaseModel, Field

from .base import APIToolBase


class FlowTools(APIToolBase):

    def run(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = query

        url = self.url
        logger.info('api_call url={}', url)
        resp = self.client.post(url, json=self.params)
        if resp.status_code != 200:
            logger.info('api_call_fail res={}', resp.text)
        return resp.text

    async def arun(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = query

        url = self.url
        logger.info('api_call url={}', url)
        resp = await self.async_client.apost(url, json=self.params)
        logger.info(resp)
        return resp

    @classmethod
    def knowledge_retrieve(cls, collection_id: int = None) -> str:
        flow_id = 'e59f4beb-7eec-450a-9c45-c03c3142f0d1'
        url = 'http://192.168.106.120:3002/api/v1/process/{}'.format(flow_id)
        input_key = 'inputs'
        params = {}
        params['Milvus-u5L3K'] = {'collection_id': collection_id}
        params['Milvus-ABCD'] = {'collection_id': collection_id}

        class InputArgs(BaseModel):
            """args_schema"""
            query: str = Field(description='questions to ask')

        return cls(url=url, params=params, input_key=input_key, args_schema=InputArgs)
