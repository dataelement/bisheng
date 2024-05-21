import json

from bisheng.database.models.gpts_tools import AuthMethod


class OpenApiSchema:
    def __init__(self, contents: dict):
        self.contents = contents
        self.version = contents['openapi']
        self.info = contents['info']
        self.title = self.info['title']
        self.description = self.info.get('description', '')

        self.default_server = ""
        self.apis = []

    def parse_server(self) -> str:
        """
        get the default server url
        """
        if self.contents.get('servers') is None:
            raise Exception('openapi schema must have servers')
        servers = self.contents['servers']
        if isinstance(servers, list):
            self.default_server = servers[0]['url']
        else:
            self.default_server = servers['url']
        return self.default_server

    def parse_paths(self) -> list[dict]:
        paths = self.contents['paths']
        self.apis = []

        for path, path_info in paths.items():
            for method, method_info in path_info.items():
                one_api_info = {
                    "path": path,
                    "method": method
                }
                if method not in ['get', 'post', 'put', 'delete']:
                    continue
                one_api_info["description"] = method_info.get('description', '') or method_info.get('summary', '')
                one_api_info["operationId"] = method_info['operationId']
                one_api_info["parameters"] = method_info.get('parameters', [])
                self.apis.append(one_api_info)
        return self.apis

    @staticmethod
    def parse_openapi_tool_params(name: str, description: str, extra: str, server_host: str,
                                  auth_method: int, auth_type: str = None, api_key: str = None):
        # 拼接请求头
        headers = {}
        if auth_method == AuthMethod.API_KEY.value:
            headers = {
                "Authorization": f"{auth_type} {api_key}"
            }

        # 返回初始化 openapi所需的入参
        params = {
            "params": json.loads(extra),
            "headers": headers,
            "url": server_host,
            "description": name + description if description else name
        }
        return params
