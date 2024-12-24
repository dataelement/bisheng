from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.code.code_parse import CodeParser


class CodeNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._code_input = self.node_params['code_input']
        self._code = self.node_params['code']
        self._code_output = self.node_params['code_output']

        self._code_parser = CodeParser(self._code)

        self._parse_code()

    def _parse_code(self):
        try:
            self._code_parser.parse_code()
        except Exception as e:
            raise Exception(f"CodeNode {self.name} exec code error: " + str(e))

    def _run(self, unique_id: str):
        main_params = self._parse_code_input()

        main_ret = self._code_parser.exec_method('main', **main_params)

        return main_ret

    def parse_log(self, unique_id: str, result: dict):
        return [
            {"key": "code_input", "value": self._parse_code_input(), "type": "params"},
            {"key": "code_output", "value": result, "type": "params"}
        ]

    def _parse_code_input(self) -> dict:
        ret = {}
        for one in self._code_input:
            if one["type"] == "ref":
                ret[one['key']] = self.graph_state.get_variable_by_str(one['value'])
            else:
                ret[one['key']] = one['value']
        return ret

    def _parse_code_output(self, result: dict) -> dict:
        if not isinstance(result, dict):
            raise Exception(f"CodeNode {self.name} main function output must be dict")
        ret = {}
        for one in self._code_output:
            if one["key"] not in result:
                raise Exception(f"CodeNode {self.name} main function output must have key {one['key']}")
            ret[one['key']] = result.get([one['key']])
        return ret
