"""QA Expert reference adapter - 查询 qa_expert 对字典键的引用情况.

该适配器用于隔离 dictionary 模块对 qa_expert 数据模型的直接依赖,
仅在需要校验字典键是否被专家信息引用时使用.
"""

from sqlalchemy import func, select

from bisheng.core.database import get_async_db_session
from bisheng.database.models.qa_expert import Expert

# 字典类型与 qa_expert 表字段的映射
_QA_EXPERT_DICT_FIELD_MAP: dict[str, str] = {
    "expert_major": "major",
    "expert_position": "position",
    "expert_job_family": "job_family",
    "expert_job_category": "job_category",
}


async def is_dict_key_in_use(dict_type: str, dict_key: str) -> bool:
    """检查指定字典键是否已被 qa_expert 表相关字段使用.

    Args:
        dict_type: 字典类型,如 expert_major/expert_position 等.
        dict_key: 字典键值.

    Returns:
        True 表示已有专家记录引用了该字典键,False 表示未使用或类型无需检查.
    """
    field = _QA_EXPERT_DICT_FIELD_MAP.get(dict_type)
    if not field or not dict_key:
        return False
    async with get_async_db_session() as session:
        stmt = select(func.count()).select_from(Expert).where(getattr(Expert, field) == dict_key)
        result = await session.execute(stmt)
        return (result.scalar() or 0) > 0
