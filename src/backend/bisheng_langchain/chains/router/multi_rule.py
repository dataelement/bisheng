from typing import List, Mapping

from langchain.chains.router.base import Chain, MultiRouteChain, RouterChain


class MultiRuleChain(MultiRouteChain):
    router_chain: RouterChain
    destination_chains: Mapping[str, Chain]
    default_chain: Chain
    output_variables: List[str]

    @property
    def output_keys(self) -> List[str]:
        return self.output_variables
