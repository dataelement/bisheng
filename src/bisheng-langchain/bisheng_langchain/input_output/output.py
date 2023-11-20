from typing import Any, Dict, List, Optional

from langchain.agents.agent import AgentExecutor
from langchain.callbacks.manager import AsyncCallbackManagerForChainRun, CallbackManagerForChainRun
from langchain.chains.base import Chain
from pydantic import BaseModel, Extra

_TEXT_COLOR_MAPPING = {
    'blue': '36;1',
    'yellow': '33;1',
    'pink': '38;5;200',
    'green': '32;1',
    'red': '31;1',
}


def get_color_mapping(
    items: List[str], excluded_colors: Optional[List] = None
) -> Dict[str, str]:
    """Get mapping for items to a support color."""
    colors = list(_TEXT_COLOR_MAPPING.keys())
    if excluded_colors is not None:
        colors = [c for c in colors if c not in excluded_colors]
    color_mapping = {item: colors[i % len(colors)] for i, item in enumerate(items)}
    return color_mapping


class Output(BaseModel):
    """Output组件，用来控制输出"""

    @classmethod
    def initialize(cls, file_path: str = None):
        return file_path if file_path else ''


class Report(Chain):
    chains: Optional[List[Dict]]
    agents: Optional[List[Dict]]
    input_key: str = 'report_name'  #: :meta private:
    output_key: str = 'report_content'  #: :meta private:

    class Config:
        """Configuration for this pydantic object."""

        extra = Extra.forbid
        arbitrary_types_allowed = True

    @property
    def input_keys(self) -> List[str]:
        """Expect input key.
        :meta private:
        """
        return [self.input_key]

    @property
    def output_keys(self) -> List[str]:
        """Return output key.
        :meta private:
        """
        return [self.output_key]

    def validate_chains(cls, values: Dict) -> Dict:
        """Validate chains."""
        if values.get('chains'):
            for chain in values['chains']:
                chain_output_keys = chain['object'].output_keys
                if len(chain_output_keys) != 1:
                    raise ValueError(
                        'Chain used in Report should all have one output, got '
                        f"{chain['object']} with {len(chain_output_keys)} outputs."
                    )
            return values

    def validate_agents(cls, values: Dict) -> Dict:
        """Validate agents."""
        if values.get('agents'):
            for agent in values['agents']:
                agent_output_keys = agent['object'].output_keys
                if len(agent_output_keys) != 1:
                    raise ValueError(
                        'Agent used in Report should all have one output, got '
                        f"{agent['object']} with {len(agent_output_keys)} outputs."
                    )
            return values

    def _call(
        self,
        verbose: Optional[bool] = None,
        run_manager: Optional[CallbackManagerForChainRun] = None,
    ) -> Dict[str, str]:
        _run_manager = run_manager or CallbackManagerForChainRun.get_noop_manager()
        outputs = {}
        color_mapping = get_color_mapping([str(i) for i in range(len(self.chains))])
        if self.chains:
            for i, chain in enumerate(self.chains):
                if not isinstance(chain['object'], Chain):
                    raise TypeError(
                        f"{chain['object']} not be runnable Chain object"
                    )
                chain_outputs = chain['object'](chain['input'], callbacks=_run_manager.get_child(f'step_{i+1}'))
                _run_manager.on_text(
                    chain_outputs, color=color_mapping[str(i)], end='\n', verbose=verbose
                )
                outputs.update({chain['node_id']: chain_outputs.get('text')})

        if self.agents:
            for agent in self.agents:
                print(agent['object'])
                if not isinstance(agent['object'],  AgentExecutor):
                    raise TypeError(
                        f"{agent['object']} not be AgentExecutor object"
                    )
                agent_outputs = agent['object'](agent['input'], callbacks=run_manager)
                outputs.update({agent['node_id']: agent_outputs.get('output')})

        return {self.output_key: outputs}

    async def _acall(
        self,
        report_name: str,
        verbose: Optional[bool] = None,
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or AsyncCallbackManagerForChainRun.get_noop_manager()
        outputs = {}
        color_mapping = get_color_mapping([str(i) for i in range(len(self.chains))])
        for i, chain in enumerate(self.chains):
            chain_outputs = await chain['object'].arun(chain['input'],
                                                       callbacks=_run_manager.get_child(f'step_{i+1}'))
            await _run_manager.on_text(
                chain_outputs, color=color_mapping[str(i)], end='\n', verbose=verbose
            )
            outputs.update({chain['node_id']: chain_outputs})

        if self.agents:
            for agent in self.agents:
                if not isinstance(agent['object'],  AgentExecutor):
                    raise TypeError(
                        f"{agent['object']} not be AgentExecutor object"
                    )
                agent_outputs = await agent['object'].arun(agent['input'], callbacks=run_manager)
                outputs.update({agent['node_id']: agent_outputs})
        return {self.output_key: outputs, self.input_key: report_name}
