from typing import Dict, List, Optional, Type

from bisheng.custom.customs import get_custom_nodes
from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.importing.utils import import_class
from bisheng.settings import settings
from bisheng.template.frontend_node.utilities import UtilitiesFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class
from langchain import utilities
from langchain.utilities.sql_database import SQLDatabase


class UtilityCreator(LangChainTypeCreator):
    type_name: str = 'utilities'

    @property
    def frontend_node_class(self) -> Type[UtilitiesFrontendNode]:
        return UtilitiesFrontendNode

    @property
    def type_to_loader_dict(self) -> Dict:
        """
        Returns a dictionary mapping utility names to their corresponding loader classes.
        If the dictionary has not been created yet, it is created by importing all utility classes
        from the langchain.chains module and filtering them according to the settings.utilities list.
        """
        if self.type_dict is None:
            self.type_dict = {
                utility_name: import_class(f'langchain.utilities.{utility_name}')
                for utility_name in utilities.__all__
            }
            self.type_dict['SQLDatabase'] = SQLDatabase
            # Filter according to settings.utilities
            self.type_dict = {
                name: utility
                for name, utility in self.type_dict.items()
                if name in settings.utilities or settings.dev
            }

        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        """Get the signature of a utility."""
        try:
            custom_nodes = get_custom_nodes(self.type_name)
            if name in custom_nodes.keys():
                return custom_nodes[name]
            return build_template_from_class(name, self.type_to_loader_dict)
        except ValueError as exc:
            raise ValueError(f'Utility {name} not found') from exc

        except AttributeError as exc:
            logger.error(f'Utility {name} not loaded: {exc}')
            return None

    def to_list(self) -> List[str]:
        return list(self.type_to_loader_dict.keys())


utility_creator = UtilityCreator()
