from collections.abc import Sequence

from bisheng.knowledge.domain.models.knowledge import Knowledge, KnowledgeTypeEnum


def needs_legacy_file_cleanup(
    knowledge: Knowledge | None,
    file_ids: Sequence[int],
    *,
    clear_minio: bool = True,
    pdf_artifact_snapshots: Sequence[dict] | None = None,
    knowledge_file_snapshots: Sequence[dict] | None = None,
) -> bool:
    """判断旧文件清理任务是否有可执行的向量或对象清理工作."""
    if clear_minio and (knowledge_file_snapshots or pdf_artifact_snapshots):
        return True
    # SPACE 向量由文档投影清理; 旧任务只能处理其随消息携带的对象快照.
    return bool(file_ids) and knowledge is not None and knowledge.type != KnowledgeTypeEnum.SPACE.value
