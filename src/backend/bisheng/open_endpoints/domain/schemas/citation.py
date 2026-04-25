from typing import Optional

from pydantic import BaseModel, Field


class OpenCitationResponse(BaseModel):
    file_id: Optional[int] = Field(default=None, description='Knowledge file ID')
    file_name: Optional[str] = Field(default=None, description='Knowledge file name')
    file_type: Optional[str] = Field(default=None, description='Knowledge file type')
    knowledge_name: Optional[str] = Field(default=None, description='Knowledge base name')
    download_url: Optional[str] = Field(default=None, description='File download URL')
    preview_url: Optional[str] = Field(default=None, description='File preview URL')
    bbox: Optional[str] = Field(default=None, description='Bounding box information')
