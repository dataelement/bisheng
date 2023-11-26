from typing import Any, Dict, List, Optional

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
    # ```
    # chain Dict:
    #    object: langchain_object
    #    node_id: object_key prefix
    #    input: triger query
    # variables Dict:
    #    variable_name: name
    #    variable_value: value
    # `
    chains: Optional[List[Dict]]
    variables: Optional[List[Dict]]
    report_name: str

    input_key: str = 'report_name'  #: :meta private:
    output_key: str = 'text'  #: :meta private:

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

    def _call(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[CallbackManagerForChainRun] = None,
        verbose: Optional[bool] = None,
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
                preset_question = chain['input']
                for k, v in preset_question.items():
                    if isinstance(v, str):
                        chain_outputs = chain['object'](preset_question,
                                                        callbacks=_run_manager.get_child(f'step_{i+1}'))
                        result = (chain_outputs.get(chain['object'].output_keys[0])
                                  if isinstance(chain_outputs, dict) else chain_outputs)
                        outputs.update({chain['node_id']: result})
                    else:
                        for question in v:
                            question_dict = {k: question}
                            chain_outputs = chain['object'](question_dict,
                                                            callbacks=_run_manager.get_child(f'step_{i+1}'))
                            result = (chain_outputs.get(chain['object'].output_keys[0])
                                      if isinstance(chain_outputs, dict) else chain_outputs)
                            outputs.update({chain['node_id'] + '_' + question: result})
                # log print
                _run_manager.on_text(
                    chain_outputs, color=color_mapping[str(i)], end='\n', verbose=verbose
                )
            # variables
            if self.variables:
                for name, value in self.variables:
                    outputs.update({'var_'+name: value})
        return {self.output_key: outputs, self.input_key: self.report_name}

    async def _acall(
        self,
        inputs: Dict[str, Any],
        run_manager: Optional[AsyncCallbackManagerForChainRun] = None,
        verbose: Optional[bool] = None,
    ) -> Dict[str, Any]:
        _run_manager = run_manager or AsyncCallbackManagerForChainRun.get_noop_manager()
        outputs = {}
        color_mapping = get_color_mapping([str(i) for i in range(len(self.chains))])
        if self.chains:
            for i, chain in enumerate(self.chains):
                if not isinstance(chain['object'], Chain):
                    raise TypeError(
                        f"{chain['object']} not be runnable Chain object"
                    )
                preset_question = chain['input']
                for k, v in preset_question.items():
                    if isinstance(v, str):
                        chain_outputs = await chain['object'].arun(preset_question,
                                                                   callbacks=_run_manager.get_child(f'step_{i+1}'))
                        result = (chain_outputs.get(chain['object'].output_keys[0])
                                  if isinstance(chain_outputs, dict) else chain_outputs)
                        outputs.update({chain['node_id']: result})
                    else:
                        for question in v:
                            question_dict = {k: question}
                            chain_outputs = await chain['object'].arun(question_dict,
                                                                       callbacks=_run_manager.get_child(f'step_{i+1}'))
                            result = (chain_outputs.get(chain['object'].output_keys[0])
                                      if isinstance(chain_outputs, dict) else chain_outputs)
                            outputs.update({chain['node_id'] + '_' + question: result})
            await _run_manager.on_text(
                chain_outputs, color=color_mapping[str(i)], end='\n', verbose=verbose
            )

        # variables
        if self.variables:
            for name, value in self.variables:
                outputs.update({'var_'+name: value})

        return {self.output_key: outputs, self.input_key: self.report_name}
