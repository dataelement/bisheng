from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Type, Union

from bisheng.settings import settings
from bisheng.template.field.base import TemplateField
from bisheng.template.frontend_node.base import FrontendNode
from bisheng.template.template.base import Template
from bisheng.utils.logger import logger
from langchain.agents import AgentExecutor
from langchain.chains.base import Chain
from pydantic import BaseModel

# Assuming necessary imports for Field, Template, and FrontendNode classes
skip_llm = {'CombineDocsChain'}


class LangChainTypeCreator(BaseModel, ABC):
    type_name: str
    type_dict: Optional[Dict] = None
    name_docs_dict: Optional[Dict[str, str]] = None

    @property
    def frontend_node_class(self) -> Type[FrontendNode]:
        """The class type of the FrontendNode created in frontend_node."""
        return FrontendNode

    @property
    def docs_map(self) -> Dict[str, str]:
        """A dict with the name of the component as key and the documentation link as value."""
        if self.name_docs_dict is None:
            try:
                type_settings = getattr(settings, self.type_name)
                self.name_docs_dict = {
                    name: value_dict['documentation']
                    for name, value_dict in type_settings.items()
                }
            except AttributeError as exc:
                logger.error(exc)

                self.name_docs_dict = {}
        return self.name_docs_dict

    @property
    @abstractmethod
    def type_to_loader_dict(self) -> Dict:
        if self.type_dict is None:
            raise NotImplementedError
        return self.type_dict

    @abstractmethod
    def get_signature(
        self, name: str
    ) -> Union[Optional[Dict[Any, Any]], FrontendNode]:
        pass

    @abstractmethod
    def to_list(self) -> List[str]:
        pass

    def to_dict(self) -> Dict:
        result: Dict = {self.type_name: {}}

        for name in self.to_list():
            # frontend_node.to_dict() returns a dict with the following structure:
            # {name: {template: {fields}, description: str}}
            # so we should update the result dict
            node = self.frontend_node(name)
            if node is not None:
                node = node.to_dict()  # type: ignore
                result[self.type_name].update(node)

        return result

    def frontend_node(self, name) -> Union[FrontendNode, None]:
        signature = self.get_signature(name)
        if signature is None:
            logger.error(f'Node {name} not loaded')
            return signature
        if not isinstance(signature, FrontendNode):
            fields = [
                TemplateField(
                    name=key,
                    field_type=value['type'],
                    required=value.get('required', False),
                    placeholder=value.get('placeholder', ''),
                    is_list=value.get('list', False),
                    show=value.get('show', True),
                    multiline=value.get('multiline', False),
                    value=value.get('value', None),
                    suffixes=value.get('suffixes', []),
                    file_types=value.get('fileTypes', []),
                    file_path=value.get('file_path', None),
                ) for key, value in signature['template'].items()
                if key != '_type'
            ]
            template = Template(type_name=name, fields=fields)
            signature = self.frontend_node_class(
                template=template,
                description=signature.get('description', ''),
                base_classes=signature['base_classes'],
                name=name,
            )

        # #判断是否包含inputKeys
        if signature.name not in skip_llm:
            if name in self.type_to_loader_dict:
                class_tmp = self.type_to_loader_dict[name]
            else:
                for _, cls_ in self.type_to_loader_dict.items():
                    if hasattr(cls_, 'function_name') and cls_.function_name() == name:
                        class_tmp = cls_
                    elif cls_.__name__ == name:
                        class_tmp = cls_

            if class_tmp and hasattr(class_tmp, 'input_keys'):
                signature.template.add_field(
                    TemplateField(
                        field_type='input',
                        required=False,
                        show=True,
                        name='input_node',
                        display_name='Preset Question',
                    )
                )
        signature.add_extra_fields()
        signature.add_extra_base_classes()
        signature.set_documentation(self.docs_map.get(name, ''))
        return signature


class CustomChain(Chain, ABC):
    """Custom chain"""

    @staticmethod
    def function_name():
        return 'CustomChain'

    @classmethod
    def initialize(cls, *args, **kwargs):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)


class CustomAgentExecutor(AgentExecutor, ABC):
    """Custom chain"""

    @staticmethod
    def function_name():
        return 'CustomChain'

    @classmethod
    def initialize(cls, *args, **kwargs):
        pass

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def run(self, *args, **kwargs):
        return super().run(*args, **kwargs)
