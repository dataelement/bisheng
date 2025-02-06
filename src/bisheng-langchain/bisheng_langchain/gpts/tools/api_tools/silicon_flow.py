from loguru import logger

from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase


class SiliconFlow(APIToolBase):
    """siliconFlow api"""

    def run(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = {"question": query}

        url = self.url
        logger.info("api_call url={}", url)
        resp = self.client.post(url, json=self.params)
        if resp.status_code != 200:
            logger.info("api_call_fail res={}", resp.text)
        return resp.text

    async def arun(self, query: str) -> str:
        """Run query through api and parse result."""
        if query:
            self.params[self.input_key] = {"question": query}

        url = self.url
        logger.info("api_call url={}", url)
        resp = await self.async_client.apost(url, json=self.params)
        logger.info(resp)
        return resp

    @classmethod
    def stable_diffusion(cls, api_key: str, prompt: str) -> "SiliconFlow":
        url = "https://api.siliconflow.cn/v1/images/generations"
        input_key = "prompt"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        }
        params= {
            "model": "stabilityai/stable-diffusion-3-5-large",
            "prompt": prompt,
            "seed": 4999999999,
        }

        return cls(url=url, api_key=api_key, input_key=input_key, headers=headers,params=params)

    @classmethod
    def flux(cls, api_key: str, prompt: str) -> "SiliconFlow":
        url = "https://api.siliconflow.cn/v1/images/generations"
        input_key = "prompt"
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
        }
        params= {
            "model": "black-forest-labs/FLUX.1-pro",
            "prompt": prompt,
            "seed": 4999999999,
        }

        return cls(url=url, api_key=api_key, input_key=input_key, headers=headers,params=params)
