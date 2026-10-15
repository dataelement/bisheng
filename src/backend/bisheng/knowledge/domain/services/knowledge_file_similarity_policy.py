"""相似推荐的元数据分组与公司资格, 不承担资源授权。"""

from typing import Literal

from bisheng.core.config.settings import FileSimilarityRuleConf, VersionManagementConf
from bisheng.knowledge.domain.models.knowledge_file import KnowledgeFile


def encoding_parts(file: KnowledgeFile) -> tuple[str, str, str]:
    parts = str(getattr(file, "file_encoding", None) or "").strip().upper().split("-")
    # 保留空段, 不能把缺失的分类误当作业务域或公司。
    company, category, domain = (part.strip() for part in [*parts, "", "", ""][:3])
    return company, category, domain


def has_company(file: KnowledgeFile) -> bool:
    encoding = str(getattr(file, "file_encoding", None) or "")
    return "-" in encoding and bool(encoding_parts(file)[0])


def same_company(source: KnowledgeFile, candidate: KnowledgeFile) -> bool:
    return has_company(source) and has_company(candidate) and encoding_parts(source)[0] == encoding_parts(candidate)[0]


def metadata_mode(source: KnowledgeFile, candidate: KnowledgeFile) -> Literal["same_metadata", "different_metadata"]:
    def metadata(file: KnowledgeFile) -> tuple[str, str, str]:
        _, category, domain = encoding_parts(file)
        subcategory = str(getattr(file, "file_subcategory_code", None) or "").strip().upper()
        return category, subcategory, domain

    source_metadata = metadata(source)
    candidate_metadata = metadata(candidate)
    return "same_metadata" if all(source_metadata) and source_metadata == candidate_metadata else "different_metadata"


def rule_for(
    config: VersionManagementConf | None, source: KnowledgeFile, candidate: KnowledgeFile
) -> FileSimilarityRuleConf:
    return (config or VersionManagementConf()).resolve_similarity_rule(
        metadata_mode(source, candidate) == "same_metadata"
    )
