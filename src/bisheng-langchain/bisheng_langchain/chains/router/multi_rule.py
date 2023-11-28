from typing import List

from langchain.chains.router.base import MultiRouteChain


class MultiRuleChain(MultiRouteChain):
    output_variables: List[str]

    @property
    def output_keys(self) -> List[str]:
        return self.output_variables
