from typing import Any

from bisheng.utils.exceptions import IgnoreException
from bisheng.workflow.nodes.base import BaseNode


class EndNode(BaseNode):
    def _return_enabled(self) -> bool:
        # F086: End nodes saved before the return switch existed have no such param.
        return self.node_params.get("return_enabled") is True

    def _run(self, unique_id: str):
        if not self._return_enabled():
            return None
        # F086: the return values become this node's variables, which the parent
        # subflow node reads after the run. Values are passed through unchanged.
        ret = {}
        for one in self.node_params.get("return_results") or []:
            if one.get("type") == "ref":
                # The editor blocks the run first; data saved through the API may still lack a variable.
                if "." not in (one.get("value") or ""):
                    raise IgnoreException(f"{self.name} -- return result {one['key']} has no variable selected")
                ret[one["key"]] = self.get_other_node_variable(one["value"])
            else:
                ret[one["key"]] = one.get("value")
        return ret

    def parse_log(self, unique_id: str, result: dict) -> Any:
        if not self._return_enabled():
            return []
        return [[{"key": "return_results", "value": result, "type": "params"}]]
