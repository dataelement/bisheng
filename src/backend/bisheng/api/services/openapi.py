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
                one_api_info["summary"] = method_info['summary']
                one_api_info["description"] = method_info.get('description', '')
                one_api_info["operationId"] = method_info['operationId']
                one_api_info["parameters"] = method_info.get('parameters', [])
                self.apis.append(one_api_info)
        return self.apis
