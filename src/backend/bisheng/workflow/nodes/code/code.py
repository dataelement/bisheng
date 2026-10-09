from typing import Any

from bisheng.common.services.config_service import settings as bisheng_settings
from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.nodes.base import BaseNode
from bisheng.workflow.nodes.code.code_parse import make_code_parser

# Surfaced to whoever ran the workflow as the run's failure reason, so it has
# to name the setting an administrator would have to change.
CODE_NODE_DISABLED_MESSAGE = (
    "The Code node is disabled. An administrator can enable it under "
    "workflow.code_node_enabled in the system settings. It is off by default because this "
    "release runs the node without an execution sandbox: while it is on, everyone who can "
    "edit a workflow can run commands on the server."
)


def assert_code_node_enabled() -> None:
    """Refuse to touch user code while the node is switched off.

    Checked when the node is built rather than when it runs: parsing the code
    already executes it (decorators, module-level statements), so a gate in the
    run path would fire after the fact.
    """
    if not bisheng_settings.get_workflow_conf().code_node_enabled:
        raise IgnoreException(CODE_NODE_DISABLED_MESSAGE)


class CodeNode(BaseNode):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        assert_code_node_enabled()
        self._code_input = self.node_params["code_input"]
        self._code = self.node_params["code"]
        self._code_output = self.node_params["code_output"]

        self._code_parser = make_code_parser(self._code)

        self._parse_code()

    def handle_input(self, user_input: dict) -> Any:
        self.node_params.update(user_input)
        self._code_input = self.node_params["code_input"]
        self._code_output = self.node_params["code_output"]
        self._code = self.node_params["code"]

    def _parse_code(self):
        try:
            self._code_parser.parse_code()
        except Exception as e:
            raise Exception(f"CodeNode {self.name} exec code error: " + str(e))

    def _run(self, unique_id: str):
        main_params = self._parse_code_input()

        main_ret = self._code_parser.exec_method("main", **main_params)
        main_ret = self._parse_code_output(main_ret)

        return main_ret

    def parse_log(self, unique_id: str, result: dict):
        return [
            [
                {"key": "code_input", "value": self._parse_code_input(), "type": "params"},
                {"key": "code_output", "value": result, "type": "params"},
            ]
        ]

    def _parse_code_input(self) -> dict:
        ret = {}
        for one in self._code_input:
            if one["type"] == "ref":
                ret[one["key"]] = self.get_other_node_variable(one["value"])
            else:
                ret[one["key"]] = one["value"]
        return ret

    def _parse_code_output(self, result: dict) -> dict:
        if not isinstance(result, dict):
            raise Exception(f"CodeNode {self.name} main function output must be dict")
        ret = {}
        for one in self._code_output:
            if one["key"] not in result:
                raise Exception(f"CodeNode {self.name} main function output must have key {one['key']}")
            ret[one["key"]] = result.get(one["key"])
        return ret
