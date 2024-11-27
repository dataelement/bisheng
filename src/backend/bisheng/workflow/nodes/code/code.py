from bisheng.workflow.nodes.base import BaseNode


class CodeNode(BaseNode):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._code_input = self.node_params['code_input']
        self._code = self.node_params['code']
        self._code_output = self.node_params['code_output']

        self._exec_globals = globals().copy()
        self._exec_locals = {}

        self._parse_code()

    def _parse_code(self):
        try:
            exec(self._code, self._exec_globals, self._exec_locals)
        except Exception as e:
            raise Exception(f"CodeNode {self.name} exec code error: " + str(e))

    def _run(self, unique_id: str):
        main_params = self._parse_code_input()

        main_ret = self._exec_locals['main'](**main_params)

        return main_ret

    def parse_log(self, unique_id: str, result: dict):
        return {
            'input': self._parse_code_input(),
            'output': result
        }

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
