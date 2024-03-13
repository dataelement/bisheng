from typing import Any, Callable, Optional, Union

from bisheng.field_typing.range_spec import RangeSpec
from pydantic import BaseModel, ConfigDict, Field


class TemplateField(BaseModel):
    model_config = ConfigDict()
    field_type: str = Field(default='str', serialization_alias='type')
    """The type of field this is. Default is a string."""

    required: bool = False
    """Specifies if the field is required. Defaults to False."""

    placeholder: str = ''
    """A placeholder string for the field. Default is an empty string."""

    is_list: bool = Field(default=False, serialization_alias='list')
    """Defines if the field is a list. Default is False."""

    show: bool = True
    """Should the field be shown. Defaults to True."""

    multiline: bool = False
    """Defines if the field will allow the user to open a text editor. Default is False."""

    value: Any = ''
    """The value of the field. Default is None."""

    suffixes: list[str] = []

    fileTypes: list[str] = []
    file_types: list[str] = Field(default=[], serialization_alias='fileTypes')
    """List of file types associated with the field. Default is an empty list. (duplicate)"""

    file_path: Optional[str] = ''
    """The file path of the field if it is a file. Defaults to None."""

    password: bool = False
    """Specifies if the field is a password. Defaults to False."""

    options: Optional[Union[list[str], Callable]] = None
    """List of options for the field. Only used when is_list=True. Default is an empty list."""

    name: Optional[str] = None
    """Name of the field. Default is an empty string."""

    display_name: Optional[str] = None
    """Display name of the field. Defaults to None."""

    advanced: bool = False
    """Specifies if the field will an advanced parameter (hidden). Defaults to False."""

    input_types: Optional[list[str]] = None
    """List of input types for the handle when the field has more than one type. Default is an empty list."""

    dynamic: bool = False
    """Specifies if the field is dynamic. Defaults to False."""

    info: Optional[str] = ''
    """Additional information about the field to be shown in the tooltip. Defaults to an empty string."""

    refresh: Optional[bool] = None
    """Specifies if the field should be refreshed. Defaults to False."""

    range_spec: Optional[RangeSpec] = Field(default=None, serialization_alias='rangeSpec')
    """Range specification for the field. Defaults to None."""

    title_case: bool = True
    """Specifies if the field should be displayed in title case. Defaults to True."""

    def to_dict(self):
        result = self.dict()
        for key in list(result.keys()):
            if result[key] is None or result[key] == []:
                del result[key]
        result['type'] = result.pop('field_type')
        result['list'] = result.pop('is_list')

        if result.get('field_type') == 'float' and self.range_spec is None:
            self.range_spec = RangeSpec()

        if result.get('file_types'):
            result['fileTypes'] = result.pop('file_types')

        if self.field_type == 'file':
            result['file_path'] = self.file_path
        else:
            result['file_path'] = ''

        if result.get('display_name') is None:
            value = self.name.replace('_', ' ')
            if self.title_case:
                value = value.title()
            result['display_name'] = value
        return result
