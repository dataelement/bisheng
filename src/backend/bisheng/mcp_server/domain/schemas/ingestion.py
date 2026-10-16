from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from bisheng.mcp_server.domain.schemas.browse import ResourceId, StrictRequest

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_TEXT_BYTES = 10 * 1024 * 1024
MAX_BODY_BYTES = 80 * 1024 * 1024
MAX_BASE64_CHARS = ((MAX_FILE_BYTES + 2) // 3) * 4
FileName = Annotated[str, StringConstraints(min_length=1, max_length=200, pattern=r"^[^/\\\x00-\x1f\x7f]+$")]
DocumentText = Annotated[str, StringConstraints(min_length=1, max_length=MAX_TEXT_BYTES)]
FileBase64 = Annotated[str, StringConstraints(min_length=1, max_length=MAX_BASE64_CHARS)]
ClassificationCode = Annotated[str, StringConstraints(max_length=16)]
ManualTagIds = Annotated[list[ResourceId], Field(max_length=100)]
ManualTagNames = Annotated[list[Annotated[str, StringConstraints(min_length=1, max_length=200)]], Field(max_length=100)]


class IngestionRequest(StrictRequest):
    knowledge_id: ResourceId
    folder_id: ResourceId | None = None
    file_name: FileName
    file_category_code: ClassificationCode | None = None
    file_subcategory_code: ClassificationCode | None = None
    business_domain_code: ClassificationCode | None = None
    manual_tag_ids: ManualTagIds = Field(default_factory=list)
    manual_tag_names: ManualTagNames = Field(default_factory=list)


class CreateDocumentRequest(IngestionRequest):
    content: DocumentText
    content_format: Literal["text", "markdown"] = "markdown"

    @model_validator(mode="after")
    def validate_document(self) -> "CreateDocumentRequest":
        expected = ".md" if self.content_format == "markdown" else ".txt"
        if not self.file_name.lower().endswith(expected):
            raise ValueError("file extension must match document format")
        if len(self.content.encode("utf-8")) > MAX_TEXT_BYTES:
            raise ValueError("document exceeds UTF-8 byte limit")
        return self


class UploadFileRequest(IngestionRequest):
    content_base64: FileBase64


class WriteResponse(StrictRequest):
    file_id: int
    knowledge_id: int
    folder_id: int | None = None
    file_name: str
    status: int
    accepted: bool
    content_ready: bool
