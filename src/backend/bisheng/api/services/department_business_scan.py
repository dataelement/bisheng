"""SQL-only structural prefilter; does not read FGA for healthy CURRENT rows."""

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.permission.domain.services.department_recovery_plan import RecoveryRuntimeError


def structural_candidates(rows, selected):
    result = set()
    for identity in selected:
        row = rows[identity]
        if row["status"] != "active":
            continue
        chain, seen, current = [], set(), identity
        while current is not None:
            if current in seen or current not in rows or len(chain) >= 100:
                result.add(identity)
                break
            seen.add(current)
            item = rows[current]
            if item["status"] != "active" or item["deleted"]:
                result.add(identity)
                break
            chain.append(item)
            current = item["parent_id"]
        else:
            path = "/"
            for item in reversed(chain):
                path += f"{item['id']}/"
                if item["path"] != path:
                    result.add(identity)
                    break
    return result


async def load_structural_candidates(repository, upper, page_size):
    rows, cursor = {}, 0
    while cursor < upper:
        page = await repository.page(cursor, upper, page_size)
        if not page:
            break
        rows.update((row["id"], row) for row in page)
        cursor = page[-1]["id"]
        if len(rows) > 200000:
            raise RecoveryRuntimeError("SQL_STRUCTURE_SCAN_LIMIT_200000")
    selected = set(rows)
    # Follow only known external ancestry, e.g. tenant mount edges; not a full
    # cross-tenant scan and never an IAM root query.
    missing = {row["parent_id"] for row in rows.values() if row["parent_id"] is not None} - rows.keys()
    attempted = set()
    with bypass_tenant_filter():
        while missing:
            current = missing.pop()
            if current in attempted:
                continue
            attempted.add(current)
            if len(attempted) > 10000:
                raise RecoveryRuntimeError("SQL_EXTERNAL_ANCESTRY_LIMIT_10000")
            row = await repository.get(current)
            if row is not None:
                rows[current] = row
                if row["parent_id"] is not None and row["parent_id"] not in rows:
                    missing.add(row["parent_id"])
    candidates = structural_candidates(rows, selected)
    inactive = getattr(repository, "inactive_membership_departments", None)
    if inactive is not None:
        candidates.update((await inactive()) & selected)
    return candidates
