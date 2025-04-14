from pydantic import field_validator, BaseModel, model_validator


class RangeSpec(BaseModel):
    min: float = -1.0
    max: float = 1.0
    step: float = 0.1

    @model_validator(mode='before')
    @classmethod
    def max_must_be_greater_than_min(cls, values):
        if 'min' in values and values['max'] <= values['min']:
            raise ValueError('max must be greater than min')
        return values

    @field_validator('step')
    @classmethod
    def step_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('step must be positive')
        return v
