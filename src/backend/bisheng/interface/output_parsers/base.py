from typing import Dict, List, Optional, Type

from bisheng.interface.base import LangChainTypeCreator
from bisheng.interface.importing.utils import import_class
from bisheng.settings import settings
from bisheng.template.frontend_node.output_parsers import OutputParserFrontendNode
from bisheng.utils.logger import logger
from bisheng.utils.util import build_template_from_class, build_template_from_method
from langchain import output_parsers


class OutputParserCreator(LangChainTypeCreator):
    type_name: str = 'output_parsers'
    from_method_nodes = {
        'StructuredOutputParser': 'from_response_schemas',
    }

    @property
    def frontend_node_class(self) -> Type[OutputParserFrontendNode]:
        return OutputParserFrontendNode

    @property
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            self.type_dict = {
                output_parser_name: import_class(
                    f'langchain.output_parsers.{output_parser_name}'
                )
                # if output_parser_name is not lower case it is a class
                for output_parser_name in output_parsers.__all__
            }

            self.type_dict = {
                name: output_parser
                for name, output_parser in self.type_dict.items()
                if name in settings.output_parsers or settings.dev
            }
        return self.type_dict

    def get_signature(self, name: str) -> Optional[Dict]:
        try:
            if name in self.from_method_nodes:
                return build_template_from_method(
                    name,
                    type_to_cls_dict=self.type_to_loader_dict,
                    method_name=self.from_method_nodes[name],
                )
            # elif name in get_custom_nodes(self.type_name).keys():
            #     return get_custom_nodes(self.type_name)[name]
            else:
                return build_template_from_class(
                    name,
                    type_to_cls_dict=self.type_to_loader_dict,
                )
        except ValueError as exc:
            # raise ValueError("OutputParser not found") from exc
            logger.error(f'OutputParser {name} not found: {exc}')
        except AttributeError as exc:
            logger.error(f'OutputParser {name} not loaded: {exc}')
        return None

    def to_list(self) -> List[str]:
        return list(self.type_to_loader_dict.keys())


output_parser_creator = OutputParserCreator()
