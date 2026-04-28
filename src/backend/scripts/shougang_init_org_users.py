#!/usr/bin/env python3
"""首钢组织与人员初始化脚本（Excel → BiSheng）

约定（与 PRD 对齐）：
- 部门：BM.xlsx 中 SID、上级组织 SID、组织全称；部门 ``external_id`` = str(SID)。
- 仅导入以 SID=203（北京首钢股份有限公司）为根的子树（含 203）。
- 部门在库中挂在平台默认根部门（Tenant.root_dept_id，一般为「默认组织」）之下，203 为其直接子部门。
- 人员：RY.xlsx 登录 ID、中文姓名、手机、邮箱、组织机构 SID、有效标志；初始密码 = 手机号的 MD5（与平台本地用户一致）。

运行前（在 src/backend 目录）::
    set config=config.yaml
    .venv\\Scripts\\python scripts/shougang_init_org_users.py --bm "C:/path/BM.xlsx" --ry "C:/path/RY.xlsx"

可选：--dry-run 只统计不入库；--skip-users 只建部门。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow `python scripts/shougang_init_org_users.py` from src/backend without PYTHONPATH.
_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set

import pandas as pd

# ---------------------------------------------------------------------------
# Column names (UTF-8, must match Excel header row)
# ---------------------------------------------------------------------------
BM_SID = "SID"
BM_PARENT_SID = "上级组织SID"
BM_NAME = "组织全称"

RY_LOGIN = "登录ID"
RY_NAME = "中文姓名"
RY_PHONE = "手机号"
RY_EMAIL = "邮箱"
RY_ORG_SID = "组织机构SID"
RY_VALID = "有效标志0-禁用1-有效"

DEPT_SOURCE = "shougang"
USER_SOURCE = "local"
ROOT_SID = 203


def _cell_sid(v: Any) -> Optional[int]:
    if pd.isna(v):
        return None
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _norm_str(v: Any) -> str:
    if pd.isna(v):
        return ""
    s = str(v).strip()
    return s if s and s.lower() != "nan" else ""


def _phone_plain(v: Any) -> str:
    if pd.isna(v):
        return ""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if float(v).is_integer():
            return str(int(v))
        return str(v).strip()
    return str(v).strip()


def _bm_index(df: pd.DataFrame) -> Dict[int, pd.Series]:
    out: Dict[int, pd.Series] = {}
    for _, row in df.iterrows():
        sid = _cell_sid(row.get(BM_SID))
        if sid is not None:
            out[sid] = row
    return out


def _bfs_subtree_sids(root: int, bm_by_sid: Dict[int, pd.Series]) -> List[int]:
    """204... order: breadth-first starting at root_sid."""
    children: Dict[int, List[int]] = defaultdict(list)
    for sid, row in bm_by_sid.items():
        p = _cell_sid(row.get(BM_PARENT_SID))
        if p is None:
            continue
        children[p].append(sid)

    order: List[int] = []
    q: deque[int] = deque([root])
    seen: Set[int] = {root}
    while q:
        s = q.popleft()
        order.append(s)
        for c in sorted(children.get(s, [])):
            if c not in seen:
                seen.add(c)
                q.append(c)
    return order


async def _run(args: argparse.Namespace) -> int:
    """Load Excel without DB first; dry-run exits before app context."""

    try:
        bm = pd.read_excel(args.bm, sheet_name=0)
        ry = pd.read_excel(args.ry, sheet_name=0)
    except Exception as e:
        print(f"Failed to read Excel: {e}", file=sys.stderr)
        return 1

    bm_by_sid = _bm_index(bm)
    if ROOT_SID not in bm_by_sid:
        print(f"BM.xlsx has no row with {BM_SID}={ROOT_SID}.", file=sys.stderr)
        return 1

    subtree_sids = _bfs_subtree_sids(ROOT_SID, bm_by_sid)
    subtree_set = set(subtree_sids)

    print(
        f"BM rows indexed={len(bm_by_sid)}, "
        f"subtree from SID {ROOT_SID} (inclusive)={len(subtree_set)} departments",
        flush=True,
    )

    ry_users = ry

    if args.dry_run:
        ry_ok = sum(
            1
            for _, r in ry_users.iterrows()
            if _cell_sid(r.get(RY_ORG_SID)) in subtree_set
            and _norm_str(r.get(RY_LOGIN))
            and _phone_plain(r.get(RY_PHONE))
        )
        print(f"Dry-run: would import ~{ry_ok} users (with phone).", flush=True)
        return 0

    from bisheng.common.services.config_service import settings
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.core.context.tenant import (
        DEFAULT_TENANT_ID,
        bypass_tenant_filter,
        current_tenant_id,
        set_current_tenant_id,
    )
    from bisheng.database.constants import DefaultRole
    from bisheng.database.models.tenant import TenantDao
    from bisheng.database.models.department import Department, DepartmentDao, UserDepartmentDao
    from bisheng.user.domain.models.user import User, UserDao
    from bisheng.department.domain.services.department_change_handler import (
        DepartmentChangeHandler,
    )
    from bisheng.permission.domain.services.legacy_rbac_sync_service import (
        LegacyRBACSyncService,
    )
    from bisheng.utils import md5_hash

    await initialize_app_context(config=settings)

    token = None
    try:
        with bypass_tenant_filter():
            token = set_current_tenant_id(DEFAULT_TENANT_ID)
            tenant = await TenantDao.aget_by_id(DEFAULT_TENANT_ID)
            if tenant is None or tenant.root_dept_id is None:
                print(
                    "Default tenant or root_dept_id missing. Run BiSheng init first.",
                    file=sys.stderr,
                )
                return 1

            plat_root = await DepartmentDao.aget_by_id(int(tenant.root_dept_id))
            if plat_root is None:
                print("Platform root department not found.", file=sys.stderr)
                return 1

            ts = int(time.time())
            sid_to_dept: Dict[int, Department] = {}

            for n_i, sid in enumerate(subtree_sids, start=1):
                if n_i == 1 or n_i % 200 == 0 or n_i == len(subtree_sids):
                    print(
                        f"Departments {n_i}/{len(subtree_sids)} (SID={sid}) ...",
                        flush=True,
                    )
                row = bm_by_sid[sid]
                name = _norm_str(row.get(BM_NAME)) or f"部门{sid}"
                if len(name) < 2:
                    name = f"部门{sid}"

                if sid == ROOT_SID:
                    parent_dept = plat_root
                else:
                    p_sid = _cell_sid(row.get(BM_PARENT_SID))
                    if p_sid is None or p_sid not in subtree_set:
                        p_sid = ROOT_SID
                    parent_dept = sid_to_dept.get(p_sid)
                    if parent_dept is None:
                        p_sid = ROOT_SID
                        parent_dept = sid_to_dept[ROOT_SID]

                path_arg = (parent_dept.path or "/").strip()
                if not path_arg.startswith("/"):
                    path_arg = "/" + path_arg
                if not path_arg.endswith("/"):
                    path_arg = path_arg + "/"

                d = await DepartmentDao.aupsert_by_external_id(
                    source=DEPT_SOURCE,
                    external_id=str(sid),
                    name=name[:128],
                    parent_id=int(parent_dept.id),
                    path=path_arg,
                    sort_order=0,
                    last_sync_ts=ts,
                )
                refreshed = await DepartmentDao.aget_by_id(int(d.id))
                if refreshed is None:
                    print(f"Failed to refresh department sid={sid}", file=sys.stderr)
                    return 1
                sid_to_dept[sid] = refreshed

                ops = DepartmentChangeHandler.on_created(
                    int(refreshed.id), int(parent_dept.id),
                )
                await DepartmentChangeHandler.execute_async(ops)

            print(f"Departments upserted: {len(sid_to_dept)}", flush=True)

            if not args.skip_users:
                created_u = 0
                skipped_u = 0

                for _, row in ry_users.iterrows():
                    org_sid = _cell_sid(row.get(RY_ORG_SID))
                    if org_sid is None or org_sid not in subtree_set:
                        skipped_u += 1
                        continue

                    login_id = _norm_str(row.get(RY_LOGIN))
                    display_name = _norm_str(row.get(RY_NAME))
                    phone = _phone_plain(row.get(RY_PHONE))
                    email = _norm_str(row.get(RY_EMAIL)) or None

                    if not login_id or not display_name:
                        skipped_u += 1
                        continue
                    if not phone:
                        print(
                            f"Skip user {login_id}: empty phone (password required).",
                        )
                        skipped_u += 1
                        continue

                    existing = await UserDao.aget_by_source_external_id(
                        USER_SOURCE, login_id,
                    )
                    if existing is not None:
                        print(
                            "Skip existing user "
                            f"source={USER_SOURCE} external_id={login_id}",
                        )
                        skipped_u += 1
                        continue

                    valid = _cell_sid(row.get(RY_VALID))
                    del_flag = 1 if (valid is not None and valid == 0) else 0

                    pwd = md5_hash(phone)
                    user = User(
                        user_name=display_name[:128],
                        password=pwd,
                        source=USER_SOURCE,
                        external_id=login_id[:255],
                        email=email,
                        phone_number=phone[:128],
                        delete=del_flag,
                    )

                    try:
                        user = await UserDao.add_user_and_default_role(user)
                    except Exception as e:
                        print(f"User create failed {login_id}: {e}", file=sys.stderr)
                        skipped_u += 1
                        continue

                    await LegacyRBACSyncService.sync_user_auth_created(
                        int(user.user_id), [DefaultRole],
                    )

                    try:
                        from bisheng.user.domain.services.user import UserService

                        await UserService._ensure_user_default_tenant_association(
                            int(user.user_id),
                        )
                    except Exception:
                        pass

                    dept = sid_to_dept.get(org_sid)
                    if dept is None:
                        print(
                            f"User {login_id}: org sid {org_sid} missing dept, skip UD.",
                        )
                        skipped_u += 1
                        continue

                    await UserDepartmentDao.aadd_member(
                        int(user.user_id),
                        int(dept.id),
                        is_primary=1,
                        source=USER_SOURCE,
                    )
                    mops = DepartmentChangeHandler.on_members_added(
                        int(dept.id), [int(user.user_id)],
                    )
                    await DepartmentChangeHandler.execute_async(mops)

                    created_u += 1

                print(
                    f"Users created: {created_u}, skipped rows: {skipped_u}",
                    flush=True,
                )

    finally:
        if token is not None:
            current_tenant_id.reset(token)
        await close_app_context()

    return 0


def main() -> None:
    p = argparse.ArgumentParser(description="Shougang BM/RY → BiSheng org & users")
    p.add_argument(
        "--bm",
        default=r"c:\Users\30388\Desktop\BM.xlsx",
        help="Path to BM.xlsx (departments)",
    )
    p.add_argument(
        "--ry",
        default=r"c:\Users\30388\Desktop\RY.xlsx",
        help="Path to RY.xlsx (users)",
    )
    p.add_argument("--dry-run", action="store_true", help="Count only, no DB writes")
    p.add_argument("--skip-users", action="store_true", help="Only import departments")
    args = p.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
