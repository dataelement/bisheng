"""批量投影的内存快照; 离开读取事务后不再隐式加载 ORM。"""

from dataclasses import dataclass, field

from bisheng.knowledge.domain.models.knowledge_document import KnowledgeDocument
from bisheng.knowledge.domain.models.knowledge_document_version import KnowledgeDocumentVersion
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


@dataclass
class ProjectionBatchContext:
    claimed: list[KnowledgeFile] = field(default_factory=list)
    entries: list[KnowledgeFile] = field(default_factory=list)
    documents: dict[int, KnowledgeDocument] = field(default_factory=dict)
    versions: dict[int, KnowledgeDocumentVersion] = field(default_factory=dict)
    files: dict[int, KnowledgeFile] = field(default_factory=dict)
