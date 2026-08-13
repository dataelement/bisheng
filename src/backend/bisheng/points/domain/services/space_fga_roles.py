"""知识空间 OpenFGA owner/manager 解析（积分月奖与 P7 共用）。

口径：
- 所有者 = FGA relation ``owner``（仅 ``user:*`` 主体）
- 管理员 = FGA relation ``manager``（仅 ``user:*`` 主体）
- FGA 无 owner tuple 时，用 DB ``knowledge.user_id``（创建人）兜底进所有者集合
- OpenFGA 不可用时抛 ``SpaceFgaRolesError``，由调用方决定失败告警策略（不回退成员表）
"""

from __future__ import annotations

import logging
import re

from bisheng.core.openfga.exceptions import FGAConnectionError

logger = logging.getLogger(__name__)

_USER_SUBJECT_RE = re.compile(r"^user:(\d+)$")


class SpaceFgaRolesError(RuntimeError):
    """OpenFGA 不可用或读取失败，无法解析空间 owner/manager。"""


def _user_ids_from_tuples(tuples: list[dict] | None) -> set[int]:
    """从 FGA tuple 列表提取直接 user 主体 ID。"""
    result: set[int] = set()
    for item in tuples or []:
        user_str = str(item.get("user") or "")
        match = _USER_SUBJECT_RE.match(user_str)
        if not match:
            continue
        result.add(int(match.group(1)))
    return result


async def read_space_owner_manager_ids(space_id: int) -> tuple[set[int], set[int]]:
    """读取单个知识空间的 FGA owner / manager 用户 ID。

    参数:
        space_id: 知识空间 ID。

    返回:
        (owners, managers) 用户 ID 集合；owners 含创建人兜底。

    副作用:
        无写库；失败抛 ``SpaceFgaRolesError``。
    """
    sid = int(space_id)
    if sid <= 0:
        return set(), set()

    from bisheng.permission.domain.services.permission_service import PermissionService

    try:
        fga = await PermissionService._aget_fga()
    except Exception as exc:
        raise SpaceFgaRolesError(f"openfga_client_failed space_id={sid}") from exc
    if fga is None:
        raise SpaceFgaRolesError(f"openfga_unavailable space_id={sid}")

    obj = f"knowledge_space:{sid}"
    try:
        owner_tuples = await fga.read_tuples(relation="owner", object=obj)
        manager_tuples = await fga.read_tuples(relation="manager", object=obj)
    except FGAConnectionError as exc:
        raise SpaceFgaRolesError(f"openfga_unreachable space_id={sid}") from exc
    except Exception as exc:
        raise SpaceFgaRolesError(f"openfga_read_failed space_id={sid}") from exc

    owners = _user_ids_from_tuples(owner_tuples)
    managers = _user_ids_from_tuples(manager_tuples)

    # 与鉴权一致：FGA 缺 owner 时 DB 创建人仍视为所有者
    try:
        creator_id = await PermissionService._get_resource_creator("knowledge_space", str(sid))
        if creator_id is not None:
            owners.add(int(creator_id))
    except Exception:
        logger.exception("points.space_fga.creator_fallback_failed space_id=%s", sid)

    return owners, managers


async def resolve_space_owner_manager_ids(*space_ids: int) -> frozenset[int]:
    """汇总多个空间的 owner∪manager（含创建人兜底），供 P7 跳过库管发分。

    OpenFGA 失败时记 ERROR 告警，并对失败空间仅保留创建人兜底（不回退成员表 admin）。
    """
    managers: set[int] = set()
    for raw in space_ids:
        try:
            sid = int(raw)
        except (TypeError, ValueError):
            continue
        if sid <= 0:
            continue
        try:
            owners, mgrs = await read_space_owner_manager_ids(sid)
            managers |= owners
            managers |= mgrs
        except SpaceFgaRolesError:
            logger.error(
                "points.space_fga.unavailable_for_p7 space_id=%s; creator_fallback_only",
                sid,
            )
            try:
                from bisheng.permission.domain.services.permission_service import PermissionService

                creator_id = await PermissionService._get_resource_creator("knowledge_space", str(sid))
                if creator_id is not None:
                    managers.add(int(creator_id))
            except Exception:
                logger.exception("points.space_fga.p7_creator_fallback_failed space_id=%s", sid)
        except Exception:
            logger.exception("points.space_fga.resolve_failed space_id=%s", sid)
    return frozenset(managers)
