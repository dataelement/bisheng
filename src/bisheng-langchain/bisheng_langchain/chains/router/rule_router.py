from typing import Any, Callable, Dict, List, Union

from langchain.callbacks.manager import Callbacks
from langchain.chains.router.base import Route, RouterChain


class RuleBasedRouter(RouterChain):
    rule_function: Callable

    @property
    def input_keys(self):
        return self.rule_function.__code__.co_varnames[: self.rule_function.__code__.co_argcount]

    def prep_outputs(
        self,
        inputs: Dict[str, str],
        outputs: Dict[str, Any],
        return_only_outputs: bool = False,
    ) -> Route:
        missing_keys = set(self.output_keys).difference(outputs._asdict().keys())
        if missing_keys:
            raise ValueError(f"Missing some output keys: {missing_keys}")
        return outputs

    def _call(
        self,
        inputs: Union[Dict[str, Any], Any],
    ) -> Route:
        result = self.rule_function(**inputs)
        return Route(result["destination"], result["next_inputs"])

    def route(
        self,
        inputs: Union[Dict[str, Any], Any],
        callbacks: Callbacks = None,
    ) -> Route:
        result = self.rule_function(**inputs)
        return Route(result["destination"], result["next_inputs"])

    async def aroute(
        self,
        inputs: Union[Dict[str, Any], Any],
        callbacks: Callbacks = None,
    ) -> Route:
        result = await self.rule_function(**inputs)
        return Route(result["destination"], result["next_inputs"])
