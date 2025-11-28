from pydantic import BaseModel


class DeleteUserMetadataReq(BaseModel):
    knowledge_file_id: int
    field_names: list[str]
