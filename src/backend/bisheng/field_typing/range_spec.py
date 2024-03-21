from pydantic import BaseModel, validator


class RangeSpec(BaseModel):
    min: float = -1.0
    max: float = 1.0
    step: float = 0.1

    @validator('max')
    @classmethod
    def max_must_be_greater_than_min(cls, v, values, **kwargs):
        if 'min' in values.data and v <= values.data['min']:
            raise ValueError('max must be greater than min')
        return v

    @validator('step')
    @classmethod
    def step_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError('step must be positive')
        return v
