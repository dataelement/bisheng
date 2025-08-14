import asyncio
from typing import Any, Callable, Dict, List, Union

from langchain.callbacks.manager import Callbacks
from langchain.chains.router.base import Route, RouterChain


class RuleBasedRouter(RouterChain):
    rule_function: Callable[..., str]
    input_variables: List[str]

    @property
    def input_keys(self):
        return self.input_variables

    def _validate_outputs(self, outputs: Dict[str, Any]) -> None:
        super()._validate_outputs(outputs)
        if not isinstance(outputs['next_inputs'], dict):
            raise ValueError

    def _call(
        self,
        inputs: Union[Dict[str, Any], Any],
    ) -> Route:
        result = self.rule_function(inputs)
        if not result.get('destination') or not result:
            return Route(None, result['next_inputs'])
        return Route(result['destination'], result['next_inputs'])

    def route(
        self,
        inputs: Union[Dict[str, Any], Any],
        callbacks: Callbacks = None,
    ) -> Route:
        result = self.rule_function(inputs)
        if not result.get('destination') or not result:
            return Route(None, result['next_inputs'])
        return Route(result['destination'], result['next_inputs'])

    async def aroute(
        self,
        inputs: Union[Dict[str, Any], Any],
        callbacks: Callbacks = None,
    ) -> Route:
        """Route the inputs to the next chain based on the rule function."""
        # 如果是异步function，那么就用await
        if asyncio.iscoroutinefunction(self.rule_function):
            result = await self.rule_function(inputs)
        else:
            result = self.rule_function(inputs)
        if not result.get('destination') or not result:
            return Route(None, result['next_inputs'])
        return Route(result['destination'], result['next_inputs'])
