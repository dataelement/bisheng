from bisheng_langchain.gpts.tools.api_tools.base import APIToolBase


class JinaTool(APIToolBase):

    @classmethod
    def get_url(cls, url: str, input_key: str) -> "JinaTool":
        """get url from jina api"""
        url = "https://r.jina.ai/".join(url)

        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer " + input_key,
        }

        return cls(url=url, headers=headers)
