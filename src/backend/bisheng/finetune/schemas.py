from typing import Any, Literal

from pydantic import BaseModel, Field, SecretStr

from bisheng.finetune.domain.models.finetune import TrainMethod


class FinetuneCreateReq(BaseModel):
    server: int = Field(description="RelatedRTSERVICESID")
    base_model: int = Field(description="Foundation ModelID")
    model_name: str = Field(max_length=50, description="Model Name")
    method: TrainMethod = Field(description="Training Methods")
    extra_params: dict = Field(default_factory=dict, description="Additional parameters required for training tasks")
    train_data: list[dict] | None = Field(default=None, description="Personal training data")
    preset_data: list[dict] | None = Field(default=None, description="Preset training data")
    contract_version: int = Field(default=1, ge=1, le=2)
    data_type: Literal["text", "image_text", "video_text"] | None = None
    capability_id: str | None = None
    dataset_report: dict[str, Any] | None = None


class FinetunePreflightReq(BaseModel):
    server: int
    base_model: int
    capability_id: str
    data_type: Literal["text", "image_text", "video_text"]
    method: TrainMethod
    parameters: dict[str, Any] = Field(default_factory=dict)


class FinetuneInferenceReq(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    media_url: str | None = None
    generation: dict[str, Any] = Field(default_factory=dict)

    baseline: bool = False


class DatasetConnection(BaseModel):
    model_config = {"extra": "forbid", "hide_input_in_errors": True}
    endpoint: str = Field(min_length=1, max_length=512)
    username: str | None = Field(default=None, max_length=256)
    password: SecretStr | None = Field(default=None, exclude=True)
    access_key: SecretStr | None = Field(default=None, exclude=True)
    secret_key: SecretStr | None = Field(default=None, exclude=True)
    session_token: SecretStr | None = Field(default=None, exclude=True)
    bucket: str | None = Field(default=None, max_length=255)
    region: str | None = Field(default=None, max_length=128)
    tls: bool = False


class DatasetImportReq(BaseModel):
    model_config = {"extra": "forbid", "hide_input_in_errors": True}
    name: str = Field(min_length=1, max_length=100)
    data_type: Literal["text", "image_text", "video_text"]
    source: Literal["ftp", "s3"]
    connection: DatasetConnection = Field(repr=False, exclude=True)
    manifest_path: str | None = Field(default=None, max_length=2048)
    manifest_text: str | None = Field(default=None, max_length=20 * 1024 * 1024, repr=False, exclude=True)
    manifest_filename: str = Field(default="train.json", max_length=100)
    media_root: str = Field(default="", max_length=2048)
