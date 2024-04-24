from bisheng import CustomComponent
from bisheng.field_typing import Data


class Component(CustomComponent):
    documentation: str = 'http://docs.bisheng.org/components/custom'

    def build_config(self):
        return {'param': {'display_name': 'Parameter'}}

    def build(self, param: Data) -> Data:
        return param
