from typing import ClassVar, Dict, List, Optional

from bisheng.custom.customs import get_custom_nodes
from bisheng.interface.agents.custom import CUSTOM_AGENTS
from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.importing.utils import import_class
from bisheng.settings import settings
from bisheng.template.frontend_node.agents import AgentFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class, build_template_from_method
from bisheng_langchain import agents as bisheng_agents
from langchain.agents import types


class AgentCreator(LangChainTypeCreator):
    type_name: str = 'agents'

    from_method_nodes: ClassVar[Dict] = {
        'ZeroShotAgent': 'from_llm_and_tools',
        'CSVAgent': 'from_toolkit_and_llm',
        'SQLAgent': 'from_toolkit_and_llm',
        'ChatglmFunctionsAgent': 'from_llm_and_tools',
        'LLMFunctionsAgent': 'from_llm_and_tools',
    }

    @property
    def frontend_node_class(self) -> type[AgentFrontendNode]:
        return AgentFrontendNode

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            self.type_dict = types.AGENT_TO_CLASS
            # Add JsonAgent to the list of agents
            for name, agent in CUSTOM_AGENTS.items():
                # TODO: validate AgentType
                self.type_dict[name] = agent  # type: ignore
            bisheng = {
                chain_name: import_class(f'bisheng_langchain.agents.{chain_name}')
                for chain_name in bisheng_agents.__all__
            }
            self.type_dict.update(bisheng)
        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        try:
            if name in get_custom_nodes(self.type_name).keys():
                return get_custom_nodes(self.type_name)[name]
            elif name in self.from_method_nodes:
                return build_template_from_method(
                    name,
                    type_to_cls_dict=self.type_to_loader_dict,
                    add_function=True,
                    method_name=self.from_method_nodes[name],
                )
            return build_template_from_class(name, self.type_to_loader_dict, add_function=True)
        except ValueError as exc:
            raise ValueError('Agent not found') from exc
        except AttributeError as exc:
            logger.error(f'Agent {name} not loaded: {exc}')
            return None

    # Now this is a generator
    def to_list(self) -> List[str]:
        names = []
        for _, agent in self.type_to_loader_dict.items():
            agent_name = (agent.function_name()
                          if hasattr(agent, 'function_name') else agent.__name__)
            if agent_name in settings.agents or settings.dev:
                names.append(agent_name)
        return names


agent_creator = AgentCreator()
