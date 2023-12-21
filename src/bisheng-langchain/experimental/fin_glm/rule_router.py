from typing import Any, Callable, Dict, List, Union

from langchain.callbacks.manager import Callbacks
from langchain.chains.router.base import Route, RouterChain


class RuleBasedRouter(RouterChain):
    input_variables: List[str]
    rule_function: Callable

    @property
    def input_keys(self):
        return self.input_variables

    def _validate_outputs(self, outputs: Dict[str, Any]) -> None:
        super()._validate_outputs(outputs)
        if not isinstance(outputs["next_inputs"], dict):
            raise ValueError

    def _call(
        self,
        inputs: Union[Dict[str, Any], Any],
    ) -> Route:
        result = self.rule_function(inputs)
        if not result.get('destination'):
            return Route(None, result["next_inputs"])
        return Route(result["destination"], result["next_inputs"])

    def route(
        self,
        inputs: Union[Dict[str, Any], Any],
        callbacks: Callbacks = None,
    ) -> Route:
        result = self.rule_function(inputs)
        if not result.get('destination'):
            return Route(None, result["next_inputs"])
        return Route(result["destination"], result["next_inputs"])

    async def aroute(
        self,
        inputs: Union[Dict[str, Any], Any],
        callbacks: Callbacks = None,
    ) -> Route:
        result = await self.rule_function(inputs)
        if not result.get('destination'):
            return Route(None, result["next_inputs"])
        return Route(result["destination"], result["next_inputs"])