#!/usr/bin/env python3
"""Import experts into qa_expert from an Excel file.

Usage (from src/backend):

    .venv/bin/python scripts/shougang_execute_expert.py \
        --file scripts/expert_by_user_id.xlsx

Logic:
1. Read the Excel file. Expected columns: 序号, user_id, 姓名, 性别, 年龄,
   单位, 岗位, 职务, 职位族, 职位类.
2. If ``user_id`` is present, use it directly; otherwise look up the user
   by ``姓名`` in the ``user`` table. Skip the row if no unique user is found.
3. Resolve ``单位`` by name in the ``department`` table and store the
   department ``id`` (as a string) in ``depart_ment``. Set ``None`` when the
   unit name is empty or no department matches.
4. Skip rows whose ``user_id`` already exists in ``qa_expert`` to keep the
   import idempotent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

_backend_root = Path(__file__).resolve().parents[1]
if str(_backend_root) not in sys.path:
    sys.path.insert(0, str(_backend_root))

import pandas as pd  # noqa: E402


# ---------------------------------------------------------------------------
# Column mapping (Excel header -> internal key)
# ---------------------------------------------------------------------------
COL_USER_ID = "user_id"
COL_NAME = "姓名"
COL_UNIT = "单位"
COL_POSITION = "岗位"
COL_TITLE = "职务"
COL_JOB_FAMILY = "职位族"
COL_JOB_CATEGORY = "职位类"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _norm_str(value: Any) -> str:
    """Return a stripped string or empty string for missing values."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    return "" if text.lower() in {"nan", "none", "null"} else text


def _parse_user_id(value: Any) -> int | None:
    """Parse a user_id cell into an integer."""
    if value is None or pd.isna(value):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None



async def _run(args: argparse.Namespace) -> int:
    file_path = Path(args.file)
    if not file_path.exists():
        print(f"[expert_import] File not found: {file_path}", file=sys.stderr)
        return 1

    try:
        df = pd.read_excel(file_path, sheet_name=0)
    except Exception as exc:
        print(f"[expert_import] Failed to read Excel: {exc}", file=sys.stderr)
        return 1

    rows = df.to_dict(orient="records")
    print(f"[expert_import] Loaded {len(rows)} rows from {file_path}", flush=True)

    inserted = 0
    skipped_no_user = 0
    skipped_duplicate = 0
    skipped_ambiguous_name = 0
    skipped_empty_name = 0
    empty_unit = 0

    from bisheng.common.services.config_service import settings
    from bisheng.core.context.tenant import (  # noqa: E402
        DEFAULT_TENANT_ID,
        bypass_tenant_filter,
        current_tenant_id,
        set_current_tenant_id,
    )
    from bisheng.database.models.department import DepartmentDao  # noqa: E402
    from bisheng.database.models.qa_expert import Expert  # noqa: E402
    from bisheng.user.domain.models.user import UserDao  # noqa: E402
    from bisheng.core.context.manager import close_app_context, initialize_app_context
    from bisheng.qa_expert.domain.repositories import ExpertRepository


    tenant_token = None
    await initialize_app_context(config=settings)
    try:
        with bypass_tenant_filter():
            tenant_token = set_current_tenant_id(DEFAULT_TENANT_ID)

            experts_to_insert: list[Expert] = []
            for idx, row in enumerate(rows):
                user_id = _norm_str(row.get(COL_USER_ID))
                name = _norm_str(row.get(COL_NAME))

                if not name:
                    skipped_empty_name += 1
                    continue

                if user_id is None:
                    matches = await UserDao.aget_users_by_username(name)
                    if len(matches) > 0:
                        print(
                            f"[expert_import] Skip row {idx + 1}: "
                            f"ambiguous name '{name}' matches {len(matches)} users.",
                            file=sys.stderr,
                        )
                        skipped_ambiguous_name += 1
                    else:
                        print(
                            f"[expert_import] Skip row {idx + 1}: user not found for name '{name}'.",
                            file=sys.stderr,
                        )
                        skipped_no_user += 1
                        continue
                    user_id = matches[0].user_id

                # existing = UserDao.get_user_by_ids([user_id])
                if user_id is None or user_id == "":
                    skipped_duplicate += 1
                    continue

                unit_name = _norm_str(row.get(COL_UNIT))
                if unit_name:
                    deptments = await DepartmentDao.aget_all_active()
                    matched_dept = next(
                        (dept for dept in deptments if dept.name == unit_name), None
                    )
                    if matched_dept is None:
                        print(
                            f"[expert_import] Row {idx + 1}: "
                            f"department not found for unit '{unit_name}', "
                            "setting depart_ment to None.",
                            file=sys.stderr,
                        )
                        empty_unit += 1
                        depart_ment = None
                    else:
                        depart_ment = str(matched_dept.id)
                else:
                    depart_ment = None

                expert = Expert(
                    user_id=user_id,
                    expert_name=name,
                    depart_ment=depart_ment,
                    position=_norm_str(row.get(COL_POSITION)) or None,
                    major=_norm_str(row.get(COL_TITLE)) or None,
                    job_family=_norm_str(row.get(COL_JOB_FAMILY)) or None,
                    job_category=_norm_str(row.get(COL_JOB_CATEGORY)) or None,
                )
                experts_to_insert.append(expert)

            if not args.dry_run:
                expertRepository = ExpertRepository()
                for expert in experts_to_insert:
                    await expertRepository.create(expert)
                inserted = len(experts_to_insert)
            else:
                inserted = len(experts_to_insert)
                print("[expert_import] Dry-run mode: no rows written.", flush=True)

        print(
            f"[expert_import] Summary: inserted={inserted}, "
            f"skipped_no_user={skipped_no_user}, "
            f"skipped_duplicate={skipped_duplicate}, "
            f"skipped_ambiguous_name={skipped_ambiguous_name}, "
            f"skipped_empty_name={skipped_empty_name}, "
            f"unit_not_found={empty_unit}.",
            flush=True,
        )
    finally:
        if tenant_token is not None:
            current_tenant_id.reset(tenant_token)
        await close_app_context()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--file",
        default="scripts/expert_by_user_id.xlsx",
        help="Path to the expert Excel file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and report counts without writing to the database",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
