from typing import Callable, Optional, Union

from bisheng.template.field.base import TemplateField
from bisheng.utils.constants import DIRECT_TYPES
from pydantic import BaseModel


class Template(BaseModel):
    type_name: str
    fields: list[TemplateField]

    def process_fields(
            self,
            name: Optional[str] = None,
            format_field_func: Union[Callable, None] = None,
    ):
        if format_field_func:
            for field in self.fields:
                format_field_func(field, name)

    def sort_fields(self):
        # first sort alphabetically
        # then sort fields so that fields that have .field_type in DIRECT_TYPES are first
        self.fields.sort(key=lambda x: x.name)
        self.fields.sort(key=lambda x: x.field_type in DIRECT_TYPES, reverse=False)

    def to_dict(self, format_field_func=None):
        self.process_fields(self.type_name, format_field_func)
        self.sort_fields()
        result = {field.name: field.to_dict() for field in self.fields}
        result['_type'] = self.type_name  # type: ignore
        return result

    def add_field(self, field: TemplateField) -> None:
        self.fields.append(field)

    def get_field(self, field_name: str) -> TemplateField:
        """Returns the field with the given name."""
        field = next((field for field in self.fields if field.name == field_name), None)
        if field is None:
            raise ValueError(f'Field {field_name} not found in template {self.type_name}')
        return field

    def update_field(self, field_name: str, field: TemplateField) -> None:
        """Updates the field with the given name."""
        for idx, template_field in enumerate(self.fields):
            if template_field.name == field_name:
                self.fields[idx] = field
                return
        raise ValueError(f'Field {field_name} not found in template {self.type_name}')

    def upsert_field(self, field_name: str, field: TemplateField) -> None:
        """Updates the field with the given name or adds it if it doesn't exist."""
        try:
            self.update_field(field_name, field)
        except ValueError:
            self.add_field(field)
