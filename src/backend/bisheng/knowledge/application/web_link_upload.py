"""Pure material plans for initial web uploads; no IO or resource authority."""

from copy import deepcopy
from dataclasses import dataclass, field

from bisheng.knowledge.domain.services.knowledge_utils import KnowledgeUtils


@dataclass(frozen=True, slots=True)
class PreparedWebLink:
    file_name: str
    content_hash: str
    markdown_bytes: bytes = field(repr=False)
    html_snapshot_bytes: bytes = field(repr=False)
    split_rule: str = field(repr=False)
    user_metadata: dict = field(repr=False)

    def __post_init__(self):
        if (
            any(type(value) is not str for value in (self.file_name, self.content_hash, self.split_rule))
            or any(type(value) is not bytes for value in (self.markdown_bytes, self.html_snapshot_bytes))
            or type(self.user_metadata) is not dict
        ):
            raise TypeError("web upload materials require original strings, bytes and server metadata")
        object.__setattr__(self, "user_metadata", deepcopy(self.user_metadata))


@dataclass(frozen=True, slots=True)
class WebLinkObject:
    name: str
    content_type: str
    content: bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class WebLinkObjectPlan:
    objects: tuple[WebLinkObject, ...]
    user_metadata: dict = field(repr=False)


def build_web_link_objects(prepared: PreparedWebLink, *, file_id: int) -> WebLinkObjectPlan:
    if type(file_id) is not int or file_id <= 0:
        raise ValueError("web upload material requires a positive integer file ID")
    if type(prepared) is not PreparedWebLink:
        raise TypeError("actual prepared web upload material is required")
    markdown_key = KnowledgeUtils.get_knowledge_file_object_name(file_id, "web_link.md")
    html_key = f"preview/{file_id}.html"
    objects = (WebLinkObject(markdown_key, "text/markdown; charset=utf-8", prepared.markdown_bytes),)
    if prepared.html_snapshot_bytes:
        objects += (WebLinkObject(html_key, "text/html; charset=utf-8", prepared.html_snapshot_bytes),)
    metadata = deepcopy(prepared.user_metadata)
    # The historical path remains in metadata even when no HTML PUT is needed.
    metadata["html_snapshot_object_name"] = html_key
    return WebLinkObjectPlan(objects, metadata)
