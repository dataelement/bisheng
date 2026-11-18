
from pydantic import BaseModel


class CreateDatasetParam(BaseModel):
    name: str
    description: str
    file_url: str | None
    qa_list: list[str] | None
