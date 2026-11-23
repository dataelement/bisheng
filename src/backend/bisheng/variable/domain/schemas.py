"""Variable API inputs deliberately exclude persistence ownership fields."""

from pydantic import BaseModel, ConfigDict, Field


class VariableInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | None = Field(default=None, gt=0)
    flow_id: str = Field(min_length=1, max_length=32)
    version_id: int = Field(gt=0)
    node_id: str = Field(min_length=1)
    variable_name: str = Field(min_length=1, max_length=50)
    value_type: int = Field(ge=1, le=3)
    is_option: int = Field(default=1, ge=0, le=1)
    value: str
