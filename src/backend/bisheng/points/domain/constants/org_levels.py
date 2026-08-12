"""积分组织四级标签常量与相对深度映射。"""

ORG_LEVEL_COMPANY = "company"
ORG_LEVEL_DEPT = "dept"
ORG_LEVEL_OFFICE = "office"
ORG_LEVEL_SQUAD = "squad"

ORG_LEVELS = (
    ORG_LEVEL_COMPANY,
    ORG_LEVEL_DEPT,
    ORG_LEVEL_OFFICE,
    ORG_LEVEL_SQUAD,
)


def path_depth(path: str | None) -> int:
    """统计 materialized path 段数（`/1/2/3/` → 3）。"""
    if not path:
        return 0
    return len([part for part in str(path).strip("/").split("/") if part])


def relative_depth(company_path: str | None, node_path: str | None) -> int | None:
    """计算节点相对公司根的深度；不在子树内返回 None。"""
    if not company_path or not node_path:
        return None
    company = str(company_path)
    node = str(node_path)
    if not node.startswith(company):
        return None
    return path_depth(node) - path_depth(company)


def org_level_for_relative_depth(rel: int) -> str:
    """相对深度 → 标签：0 company / 1 dept / 2 office / ≥3 squad。"""
    if rel <= 0:
        return ORG_LEVEL_COMPANY
    if rel == 1:
        return ORG_LEVEL_DEPT
    if rel == 2:
        return ORG_LEVEL_OFFICE
    return ORG_LEVEL_SQUAD
