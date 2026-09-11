
from pydantic import BaseModel, Field


class OpenCitationResponse(BaseModel):
    file_id: int | None = Field(default=None, description='Knowledge file ID')
    file_name: str | None = Field(default=None, description='Knowledge file name')
    file_type: str | None = Field(default=None, description='Knowledge file type')
    knowledge_name: str | None = Field(default=None, description='Knowledge base name')
    download_url: str | None = Field(default=None, description='File download URL')
    preview_url: str | None = Field(default=None, description='File preview URL')
    bbox: str | None = Field(default=None, description='Bounding box information')
