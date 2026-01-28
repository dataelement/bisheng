from typing import Dict, Optional, List

from pydantic import BaseModel, Field

from bisheng.finetune.domain.models.finetune import TrainMethod


class FinetuneCreateReq(BaseModel):
    server: int = Field(description='RelatedRTSERVICESID')
    base_model: int = Field(description='Foundation ModelID')
    model_name: str = Field(max_length=50, description='Model Name')
    method: TrainMethod = Field(description='Training Methods')
    extra_params: Dict = Field(default_factory=dict, description='Additional parameters required for training tasks')
    train_data: Optional[List[Dict]] = Field(default=None, description='Personal training data')
    preset_data: Optional[List[Dict]] = Field(default=None, description='Preset training data')
