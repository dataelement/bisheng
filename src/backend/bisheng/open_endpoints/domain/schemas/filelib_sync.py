from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class BusinessDomainStrategy(str, Enum):
    RESPONSIBLE_DEPARTMENT = "responsible_department"
    FIXED = "fixed"


class TargetSpaceStrategy(str, Enum):
    MAIN_DEPARTMENT = "main_department"
    RESPONSIBLE_DEPARTMENT = "responsible_department"
    FIXED_PUBLIC = "fixed_public"
    FIXED_DEPARTMENT = "fixed_department"


@dataclass(frozen=True)
class FilelibSyncRule:
    endpoint_code: str
    category_name: str
    subcategory_name: str
    business_domain_strategy: BusinessDomainStrategy
    target_space_strategy: TargetSpaceStrategy
    fixed_business_domain_name: str | None = None
    fixed_space_name: str | None = None
    fixed_department_name: str | None = None


FILELIB_SYNC_RULES: dict[str, FilelibSyncRule] = {
    "03": FilelibSyncRule(
        endpoint_code="03",
        category_name="政策制度",
        subcategory_name="管理政策",
        business_domain_strategy=BusinessDomainStrategy.RESPONSIBLE_DEPARTMENT,
        target_space_strategy=TargetSpaceStrategy.MAIN_DEPARTMENT,
    ),
    "04": FilelibSyncRule(
        endpoint_code="04",
        category_name="技术规程与诊断",
        subcategory_name="精益项目",
        business_domain_strategy=BusinessDomainStrategy.RESPONSIBLE_DEPARTMENT,
        target_space_strategy=TargetSpaceStrategy.RESPONSIBLE_DEPARTMENT,
    ),
    "05": FilelibSyncRule(
        endpoint_code="05",
        category_name="技术规程与诊断",
        subcategory_name="快速改善",
        business_domain_strategy=BusinessDomainStrategy.RESPONSIBLE_DEPARTMENT,
        target_space_strategy=TargetSpaceStrategy.RESPONSIBLE_DEPARTMENT,
    ),
    "06": FilelibSyncRule(
        endpoint_code="06",
        category_name="技术规程与诊断",
        subcategory_name="管理参数",
        business_domain_strategy=BusinessDomainStrategy.RESPONSIBLE_DEPARTMENT,
        target_space_strategy=TargetSpaceStrategy.RESPONSIBLE_DEPARTMENT,
    ),
    "07": FilelibSyncRule(
        endpoint_code="07",
        category_name="技术规程与诊断",
        subcategory_name="合理化建议",
        business_domain_strategy=BusinessDomainStrategy.RESPONSIBLE_DEPARTMENT,
        target_space_strategy=TargetSpaceStrategy.RESPONSIBLE_DEPARTMENT,
    ),
    "09": FilelibSyncRule(
        endpoint_code="09",
        category_name="报告",
        subcategory_name="经营管理成果",
        business_domain_strategy=BusinessDomainStrategy.FIXED,
        target_space_strategy=TargetSpaceStrategy.FIXED_PUBLIC,
        fixed_business_domain_name="信息",
        fixed_space_name="信息库",
    ),
    "10": FilelibSyncRule(
        endpoint_code="10",
        category_name="政策制度",
        subcategory_name="管理政策",
        business_domain_strategy=BusinessDomainStrategy.FIXED,
        target_space_strategy=TargetSpaceStrategy.FIXED_PUBLIC,
        fixed_business_domain_name="信息",
        fixed_space_name="信息库",
    ),
    "11": FilelibSyncRule(
        endpoint_code="11",
        category_name="报告",
        subcategory_name="经营管理成果",
        business_domain_strategy=BusinessDomainStrategy.FIXED,
        target_space_strategy=TargetSpaceStrategy.FIXED_PUBLIC,
        fixed_business_domain_name="采购",
        fixed_space_name="采购库",
    ),
    "12": FilelibSyncRule(
        endpoint_code="12",
        category_name="标准规范",
        subcategory_name="产品成果",
        business_domain_strategy=BusinessDomainStrategy.FIXED,
        target_space_strategy=TargetSpaceStrategy.FIXED_DEPARTMENT,
        fixed_business_domain_name="营销",
        fixed_department_name="营销中心",
    ),
    "14": FilelibSyncRule(
        endpoint_code="14",
        category_name="案例",
        subcategory_name="故障诊断/协作案例",
        business_domain_strategy=BusinessDomainStrategy.FIXED,
        target_space_strategy=TargetSpaceStrategy.FIXED_DEPARTMENT,
        fixed_business_domain_name="营销",
        fixed_department_name="营销中心",
    ),
    "15": FilelibSyncRule(
        endpoint_code="15",
        category_name="政策制度",
        subcategory_name="国家/行业法规",
        business_domain_strategy=BusinessDomainStrategy.FIXED,
        target_space_strategy=TargetSpaceStrategy.FIXED_DEPARTMENT,
        fixed_business_domain_name="安全",
        fixed_department_name="安全部",
    ),
}


class FilelibSyncParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    external_file_id: str = Field(min_length=1, max_length=255)
    file_name: str = Field(min_length=1, max_length=200)
    department: str | None = None
    department_id: int | None = Field(default=None, gt=0)
    responsible_person: str | None = None
    responsible_person_id: int | None = Field(default=None, gt=0)

    @field_validator("external_file_id", "file_name", mode="before")
    @classmethod
    def normalize_required_text(cls, value: Any) -> str:
        return str(value or "").strip()

    @field_validator("department", "responsible_person", mode="before")
    @classmethod
    def normalize_optional_text(cls, value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @field_validator("department_id", "responsible_person_id", mode="before")
    @classmethod
    def normalize_optional_id(cls, value: Any) -> int | None:
        if value is None or value == "":
            return None
        if isinstance(value, bool):
            raise ValueError("id must be an integer")
        return int(value)


class FilelibSyncResponseData(BaseModel):
    external_file_id: str
    file_id: int
    file_encoding: str
    knowledge_id: int
    knowledge_name: str
    status: int
