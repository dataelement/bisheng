"""F006 RBAC→ReBAC migration end-to-end verification.

Seeds the 9 legacy MySQL tables with diverse mock data covering every path
in the migration (all 10 AccessType values, super-admin, SCM roles, flow
types, is_delete filter, folder hierarchy). Runs the full migration, then
uses both --verify mode and direct OpenFGA reads to confirm that every
step produced the expected tuples and that boundary cases (WEB_MENU,
admin-role access, PENDING members, is_delete=1, non-numeric paths) were
correctly skipped.

Usage (on any host with the backend venv + live MySQL/OpenFGA):

    cd src/backend
    .venv/bin/python ../../scripts/verify_f006_migration.py

    # Keep mock data after the run for UI inspection:
    .venv/bin/python ../../scripts/verify_f006_migration.py --skip-cleanup

Exit code 0 = PASS, 1 = FAIL. Script is idempotent: it refuses to start if
the 90000-ID range already holds mock data, and on failure it preserves
both MySQL rows and OpenFGA tuples for inspection.
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Allow running from repo root without setting PYTHONPATH.
_BACKEND = Path(__file__).resolve().parent.parent / 'src' / 'backend'
if _BACKEND.is_dir():
    sys.path.insert(0, str(_BACKEND))

from sqlalchemy import text

# ── Mock data ID ranges (segregated to avoid collisions) ───────────
MOCK_ID_LO, MOCK_ID_HI = 90000, 99999
MOCK_USER_IDS = list(range(90001, 90011))    # 10 users
MOCK_ROLE_IDS = list(range(90001, 90005))    # 4 non-admin roles
MOCK_GROUP_IDS = [90001, 90002]
MOCK_KB_IDS = [90001, 90002, 90003, 90004]
MOCK_TOOL_IDS = [90001, 90002, 90003, 90004]
MOCK_FLOW_IDS = [f'mock-flow-{i}' for i in range(90001, 90007)]
# 36-char UUID-shaped IDs to satisfy CHAR(36) columns on channel /
# space_channel_member.
MOCK_CHANNEL_IDS = ['mock-channel-90001-00000000000000000',   # 36 chars
                    'mock-channel-90002-00000000000000000']
MOCK_KF_IDS = list(range(90001, 90007))
MOCK_SCM_SPACE_IDS = ['mock-scm-sp-90001-000000000000000000',  # 36 chars
                      'mock-scm-sp-90002-000000000000000000']
MOCK_SCM_CHANNEL_IDS = ['mock-scm-ch-90001-000000000000000000']

# Admin role id (matches bisheng default data)
ADMIN_ROLE_ID = 1


# ── Expected outcomes ─────────────────────────────────────────────
@dataclass
class ExpectedSet:
    """Tuples the migration MUST produce from the mock data."""
    must_have: set[tuple[str, str, str]] = field(default_factory=set)
    must_not_have: set[tuple[str, str, str]] = field(default_factory=set)


# ── Helpers ───────────────────────────────────────────────────────

def _exec(session, sql: str, params: dict | None = None):
    return session.execute(text(sql), params or {})


def _print_banner(title: str):
    print()
    print('=' * 72)
    print(f' {title}')
    print('=' * 72)


def _print_row(label: str, value, ok: bool | None = None):
    mark = '' if ok is None else ('  ✓' if ok else '  ✗')
    print(f'  {label:<40s}{str(value):>20s}{mark}')


# ── Stage 1: Precheck ─────────────────────────────────────────────

def precheck(session) -> None:
    """Abort if mock ID range is already occupied."""
    _print_banner('Stage 1 — Precheck')
    checks = [
        ('user', f'user_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
        ('role', f'id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
        ('userrole', f'user_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
        ('usergroup', f'user_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
        ('roleaccess', f'role_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
        ('space_channel_member', "business_id LIKE 'mock-scm-%'"),
        ('flow', "id LIKE 'mock-flow-%'"),
        ('knowledge', f'id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
        ('t_gpts_tools', f'id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
        ('channel', "id LIKE 'mock-channel-%'"),
        ('knowledgefile', f'id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}'),
    ]
    dirty = []
    for table, where in checks:
        cnt = _exec(session, f'SELECT COUNT(*) FROM `{table}` WHERE {where}').scalar()
        _print_row(f'{table} mock rows', cnt, ok=(cnt == 0))
        if cnt:
            dirty.append((table, cnt))
    if dirty:
        raise SystemExit(f'Precheck failed: {dirty}. Run with --cleanup-only or clear manually.')
    print('  → ID range clean, safe to seed.')


# ── Stage 2: Seed ─────────────────────────────────────────────────

def seed(session) -> ExpectedSet:
    """Insert mock rows and return expected tuple set."""
    _print_banner('Stage 2 — Seed mock data')

    # --- users + roles + groups ---
    for uid in MOCK_USER_IDS:
        _exec(session,
              "INSERT INTO `user` (user_id, user_name, password, `delete`) "
              "VALUES (:uid, :name, :pwd, 0)",
              {'uid': uid, 'name': f'mock_user_{uid}', 'pwd': 'x'})
    for rid in MOCK_ROLE_IDS:
        _exec(session,
              "INSERT INTO `role` (id, role_name, tenant_id, role_type) "
              "VALUES (:rid, :name, 1, 'tenant')",
              {'rid': rid, 'name': f'mock_role_{rid}'})
    for gid in MOCK_GROUP_IDS:
        _exec(session,
              "INSERT INTO `group` (id, group_name, tenant_id, visibility) "
              "VALUES (:gid, :name, 1, 'public')",
              {'gid': gid, 'name': f'mock_group_{gid}'})

    # --- userrole ---
    # 90001-90003 → role 90001 (fan-out for Step 3)
    # 90004 → role 90002
    # 90005 → role 90003
    # 90006 → role 90004
    # 90007 → ADMIN (Step 1 super-admin)
    # 90008, 90009, 90010 → no role (isolated for Step 4/5 tests)
    user_role_pairs = [
        (90001, 90001), (90002, 90001), (90003, 90001),
        (90004, 90002),
        (90005, 90003),
        (90006, 90004),
        (90007, ADMIN_ROLE_ID),
    ]
    for uid, rid in user_role_pairs:
        _exec(session,
              "INSERT INTO userrole (user_id, role_id, tenant_id) "
              "VALUES (:uid, :rid, 1)",
              {'uid': uid, 'rid': rid})

    # --- usergroup ---
    # group 90001: 90002 admin + 90003 member
    # group 90002: 90004 admin + 90005 member + 90006 member
    user_group_rows = [
        (90002, 90001, 1),
        (90003, 90001, 0),
        (90004, 90002, 1),
        (90005, 90002, 0),
        (90006, 90002, 0),
    ]
    for uid, gid, is_admin in user_group_rows:
        _exec(session,
              "INSERT INTO usergroup (user_id, group_id, is_group_admin, tenant_id) "
              "VALUES (:uid, :gid, :admin, 1)",
              {'uid': uid, 'gid': gid, 'admin': is_admin})

    # --- roleaccess ---
    # Cover all 10 non-menu AccessType values × plus skip boundaries.
    # Resources use MOCK ids that match type semantics.
    role_access_rows = [
        # role 90001 on kb 90001: both viewer(1) + editor(3) → dedup to editor
        (90001, 'kb-90001', 1),
        (90001, 'kb-90001', 3),
        # AccessType 5/6: assistant
        (90001, 'mock-flow-90001', 5),
        (90002, 'mock-flow-90002', 6),
        # AccessType 7/8: tool
        (90002, 'tool-90001', 7),
        (90003, 'tool-90002', 8),
        # AccessType 9/10: workflow
        (90001, 'mock-flow-90003', 9),
        (90002, 'mock-flow-90004', 10),
        # AccessType 11/12: dashboard (resources don't exist; still must write tuple)
        (90003, 'dash-90001', 11),
        (90004, 'dash-90002', 12),
        # Cross-resource coverage for role 90004 — tool editor + kb viewer
        (90004, 'tool-90003', 8),
        (90004, 'kb-90002', 1),
        # SKIP boundary: type=99 (WEB_MENU) — must NOT produce tuple
        (90001, 'menu-settings', 99),
        # SKIP boundary: role_id=1 (admin) — must NOT produce tuple from Step 3
        (ADMIN_ROLE_ID, 'kb-admin-leak', 1),
    ]
    for rid, tid, atype in role_access_rows:
        _exec(session,
              "INSERT INTO roleaccess (role_id, third_id, type, tenant_id) "
              "VALUES (:rid, :tid, :atype, 1)",
              {'rid': rid, 'tid': tid, 'atype': atype})

    # --- space_channel_member ---
    # Enum values are uppercase in DB. Migration uses lowercase keys in its
    # mapping; if it doesn't lower() before lookup this stage will silently
    # skip. The script captures the discrepancy in the final report.
    scm_rows = [
        # space 90001: creator + admin + member, all ACTIVE
        (MOCK_SCM_SPACE_IDS[0], 'SPACE', 90001, 'CREATOR', 'ACTIVE'),
        (MOCK_SCM_SPACE_IDS[0], 'SPACE', 90002, 'ADMIN', 'ACTIVE'),
        (MOCK_SCM_SPACE_IDS[0], 'SPACE', 90003, 'MEMBER', 'ACTIVE'),
        # channel 90001: creator + member
        (MOCK_SCM_CHANNEL_IDS[0], 'CHANNEL', 90004, 'CREATOR', 'ACTIVE'),
        (MOCK_SCM_CHANNEL_IDS[0], 'CHANNEL', 90005, 'MEMBER', 'ACTIVE'),
        # space 90002: PENDING + REJECTED (skip) + ACTIVE member
        (MOCK_SCM_SPACE_IDS[1], 'SPACE', 90006, 'CREATOR', 'PENDING'),
        (MOCK_SCM_SPACE_IDS[1], 'SPACE', 90007, 'ADMIN', 'REJECTED'),
        (MOCK_SCM_SPACE_IDS[1], 'SPACE', 90008, 'MEMBER', 'ACTIVE'),
    ]
    for biz_id, biz_type, uid, role, status in scm_rows:
        _exec(session,
              "INSERT INTO space_channel_member "
              "(business_id, business_type, user_id, user_role, status, is_pinned) "
              "VALUES (:bid, :btype, :uid, :role, :status, 0)",
              {'bid': biz_id, 'btype': biz_type, 'uid': uid,
               'role': role, 'status': status})

    # --- flow ---
    # flow_type 5 = assistant, 10 = workflow (migrate); 15 = workstation (skip)
    flow_rows = [
        (MOCK_FLOW_IDS[0], 90001, 5),   # assistant owner 90001
        (MOCK_FLOW_IDS[1], 90002, 5),   # assistant owner 90002
        (MOCK_FLOW_IDS[2], 90001, 10),  # workflow owner 90001
        (MOCK_FLOW_IDS[3], 90003, 10),  # workflow owner 90003
        (MOCK_FLOW_IDS[4], 90004, 15),  # SKIP: workstation
        (MOCK_FLOW_IDS[5], 90005, 15),  # SKIP: workstation
    ]
    for fid, uid, ft in flow_rows:
        _exec(session,
              "INSERT INTO flow (id, name, user_id, flow_type, tenant_id) "
              "VALUES (:fid, :name, :uid, :ft, 1)",
              {'fid': fid, 'name': f'mock_flow_{fid}', 'uid': uid, 'ft': ft})

    # --- knowledge ---
    knowledge_rows = [(i, MOCK_USER_IDS[idx])
                      for idx, i in enumerate(MOCK_KB_IDS)]
    for kid, uid in knowledge_rows:
        _exec(session,
              "INSERT INTO knowledge (id, user_id, name, type, is_released, "
              "auth_type, tenant_id) VALUES (:kid, :uid, :name, 0, 1, "
              "'PRIVATE', 1)",
              {'kid': kid, 'uid': uid, 'name': f'mock_kb_{kid}'})

    # --- t_gpts_tools ---
    tool_rows = [
        (MOCK_TOOL_IDS[0], 90001, 0),   # active
        (MOCK_TOOL_IDS[1], 90002, 0),   # active
        (MOCK_TOOL_IDS[2], 90003, 0),   # active
        (MOCK_TOOL_IDS[3], 90004, 1),   # SKIP: deleted
    ]
    for tid, uid, is_del in tool_rows:
        _exec(session,
              "INSERT INTO t_gpts_tools (id, user_id, type, is_preset, "
              "is_delete, tenant_id) VALUES (:tid, :uid, 1, 0, :d, 1)",
              {'tid': tid, 'uid': uid, 'd': is_del})

    # --- channel ---
    for idx, cid in enumerate(MOCK_CHANNEL_IDS):
        _exec(session,
              "INSERT INTO channel (id, name, source_list, filter_rules, "
              "user_id, is_pinned, is_released, tenant_id) "
              "VALUES (:cid, :name, '[]', '{}', :uid, 0, 1, 1)",
              {'cid': cid, 'name': f'mock_channel_{idx}',
               'uid': MOCK_USER_IDS[idx]})

    # --- knowledgefile — folder hierarchy under kb 90003 ---
    # knowledge_space:90003
    #   └─ folder:90001 (file_level_path="")
    #      └─ folder:90002 (file_level_path="90001")
    #         └─ file:90003 (file_level_path="90001/90002")
    #   └─ file:90004  (file_level_path="")  # root-level file
    #   └─ folder:90005 (file_level_path="")
    #   └─ file:90006   (file_level_path="abc") # SKIP: non-numeric
    kf_rows = [
        (90001, 90003, 0, ''),         # folder at root
        (90002, 90003, 0, '90001'),    # folder under 90001
        (90003, 90003, 1, '90001/90002'),  # file under 90002
        (90004, 90003, 1, ''),         # file at root
        (90005, 90003, 0, ''),         # isolated folder
        (90006, 90003, 1, 'abc'),      # SKIP: non-numeric path
    ]
    for kid, kbid, ftype, path in kf_rows:
        _exec(session,
              "INSERT INTO knowledgefile (id, knowledge_id, file_name, "
              "file_type, file_level_path, tenant_id) "
              "VALUES (:id, :kb, :name, :ft, :path, 1)",
              {'id': kid, 'kb': kbid, 'name': f'mock_kf_{kid}',
               'ft': ftype, 'path': path})

    session.commit()
    print('  → All mock rows inserted (commit OK).')

    # Build expected tuple set from the seed above.
    expected = ExpectedSet()

    # Step 1: super_admin for user 90007
    expected.must_have.add(('user:90007', 'super_admin', 'system:global'))

    # Step 2: usergroup
    expected.must_have.update({
        ('user:90002', 'admin', 'user_group:90001'),
        ('user:90003', 'member', 'user_group:90001'),
        ('user:90004', 'admin', 'user_group:90002'),
        ('user:90005', 'member', 'user_group:90002'),
        ('user:90006', 'member', 'user_group:90002'),
    })

    # Step 3: role_access expansion × userrole fan-out
    # role 90001 holders: 90001, 90002, 90003
    # role 90002 holders: 90004
    # role 90003 holders: 90005
    # role 90004 holders: 90006
    # Expanded (before dedup): 10 role_access rows × holders
    for uid in (90001, 90002, 90003):
        # kb-90001: viewer+editor → editor (dedup)
        expected.must_have.add((f'user:{uid}', 'editor', 'knowledge_space:kb-90001'))
        expected.must_not_have.add((f'user:{uid}', 'viewer', 'knowledge_space:kb-90001'))
        # assistant viewer
        expected.must_have.add((f'user:{uid}', 'viewer', 'assistant:mock-flow-90001'))
        # workflow viewer
        expected.must_have.add((f'user:{uid}', 'viewer', 'workflow:mock-flow-90003'))
    for uid in (90002, 90003):
        pass  # handled above
    # role 90002 holder: 90004
    expected.must_have.update({
        ('user:90004', 'editor', 'assistant:mock-flow-90002'),  # type 6
        ('user:90004', 'viewer', 'tool:tool-90001'),             # type 7
        ('user:90004', 'editor', 'workflow:mock-flow-90004'),    # type 10
    })
    for uid in (90001, 90002, 90003):
        # role 90001 also held tool-90001 (type 7) via... no, tool-90001 is role 90002
        pass
    # role 90003 holder: 90005
    expected.must_have.update({
        ('user:90005', 'editor', 'tool:tool-90002'),             # type 8
        ('user:90005', 'viewer', 'dashboard:dash-90001'),        # type 11
    })
    # role 90004 holder: 90006
    expected.must_have.update({
        ('user:90006', 'editor', 'dashboard:dash-90002'),        # type 12
        ('user:90006', 'editor', 'tool:tool-90003'),             # type 8
        ('user:90006', 'viewer', 'knowledge_space:kb-90002'),    # type 1
    })
    # Role 90001 viewer on mock-flow-90001 as assistant (type 5)
    # already captured above for uids 90001/90002/90003
    # Boundaries:
    #   type 99 (menu-settings) → no tuple for any user
    expected.must_not_have.update({
        (f'user:{uid}', r, f'knowledge_space:menu-settings')
        for uid in (90001, 90002, 90003)
        for r in ('viewer', 'editor')
    })
    #   role_id=1 row (admin) → Step 3 skips, no tuple on kb-admin-leak
    expected.must_not_have.update({
        (f'user:{uid}', r, 'knowledge_space:kb-admin-leak')
        for uid in (90007,)  # user bound to admin role
        for r in ('viewer', 'editor')
    })

    # Step 4: space_channel_member ACTIVE only
    # NOTE: DB enum is UPPERCASE; migration mapping is lowercase.
    # These "must_have" are the intent if mapping handles casing;
    # if it doesn't, report will show them as FAIL → new bug discovered.
    space_id = MOCK_SCM_SPACE_IDS[0]
    channel_id = MOCK_SCM_CHANNEL_IDS[0]
    expected.must_have.update({
        ('user:90001', 'owner', f'knowledge_space:{space_id}'),
        ('user:90002', 'manager', f'knowledge_space:{space_id}'),
        ('user:90003', 'viewer', f'knowledge_space:{space_id}'),
        ('user:90004', 'owner', f'channel:{channel_id}'),
        ('user:90005', 'viewer', f'channel:{channel_id}'),
        # space-90002 ACTIVE member 90008
        ('user:90008', 'viewer', f'knowledge_space:{MOCK_SCM_SPACE_IDS[1]}'),
    })
    # PENDING/REJECTED must not produce tuples
    expected.must_not_have.update({
        ('user:90006', 'owner', f'knowledge_space:{MOCK_SCM_SPACE_IDS[1]}'),
        ('user:90007', 'manager', f'knowledge_space:{MOCK_SCM_SPACE_IDS[1]}'),
    })

    # Step 5: resource owners
    for idx, kid in enumerate(MOCK_KB_IDS):
        expected.must_have.add((f'user:{MOCK_USER_IDS[idx]}', 'owner',
                                 f'knowledge_space:{kid}'))
    expected.must_have.update({
        ('user:90001', 'owner', f'assistant:{MOCK_FLOW_IDS[0]}'),
        ('user:90002', 'owner', f'assistant:{MOCK_FLOW_IDS[1]}'),
        ('user:90001', 'owner', f'workflow:{MOCK_FLOW_IDS[2]}'),
        ('user:90003', 'owner', f'workflow:{MOCK_FLOW_IDS[3]}'),
        # Tools (is_delete=0 only)
        ('user:90001', 'owner', f'tool:{MOCK_TOOL_IDS[0]}'),
        ('user:90002', 'owner', f'tool:{MOCK_TOOL_IDS[1]}'),
        ('user:90003', 'owner', f'tool:{MOCK_TOOL_IDS[2]}'),
        # Channels
        ('user:90001', 'owner', f'channel:{MOCK_CHANNEL_IDS[0]}'),
        ('user:90002', 'owner', f'channel:{MOCK_CHANNEL_IDS[1]}'),
    })
    # is_delete=1 tool + flow_type=15 must not have owner tuples
    expected.must_not_have.update({
        ('user:90004', 'owner', f'tool:{MOCK_TOOL_IDS[3]}'),
        ('user:90004', 'owner', f'assistant:{MOCK_FLOW_IDS[4]}'),
        ('user:90005', 'owner', f'workflow:{MOCK_FLOW_IDS[5]}'),
    })

    # Step 6: folder hierarchy
    expected.must_have.update({
        # root-level folder + file + isolated folder
        ('knowledge_space:90003', 'parent', 'folder:90001'),
        ('knowledge_space:90003', 'parent', 'knowledge_file:90004'),
        ('knowledge_space:90003', 'parent', 'folder:90005'),
        # nested
        ('folder:90001', 'parent', 'folder:90002'),
        ('folder:90002', 'parent', 'knowledge_file:90003'),
    })
    # Non-numeric path (kf 90006) must not produce any parent tuple
    expected.must_not_have.add(('knowledge_space:90003', 'parent',
                                'knowledge_file:90006'))

    return expected


# ── Stage 3: Reset checkpoint + invoke migration ──────────────────

async def reset_and_migrate() -> 'MigrationStats':
    """Delete checkpoint file then run the migrator in-process."""
    from bisheng.permission.migration.migrate_rbac_to_rebac import (
        RBACToReBACMigrator, _CHECKPOINT_FILENAME,
    )
    _print_banner('Stage 3 — Reset checkpoint + execute migration')

    # Locate checkpoint file next to the migration module.
    module_dir = Path(sys.modules[
        'bisheng.permission.migration.migrate_rbac_to_rebac'
    ].__file__).parent
    ckpt = module_dir / _CHECKPOINT_FILENAME
    if ckpt.exists():
        ckpt.unlink()
        print(f'  → Removed stale checkpoint: {ckpt}')
    else:
        print('  → No existing checkpoint.')

    migrator = RBACToReBACMigrator(dry_run=False)
    stats = await migrator.run()
    print(f'  → Migration completed; MigrationStats.total = {stats.total}')
    return stats


# ── Stage 4: --verify mode ────────────────────────────────────────

async def run_verify() -> 'VerifyReport':
    from bisheng.permission.migration.migrate_rbac_to_rebac import (
        RBACToReBACMigrator,
    )
    _print_banner('Stage 4 — Built-in --verify (old vs new permission parity)')
    migrator = RBACToReBACMigrator(dry_run=True, verify_only=True)
    report = await migrator.run()
    _print_row('checks total', report.total)
    _print_row('match', report.match, ok=(report.match == report.total))
    _print_row('regression (critical)', report.regression,
               ok=(report.regression == 0))
    _print_row('expansion', report.expansion)
    return report


# ── Stage 5: Reconcile FGA tuples against expected set ────────────

async def reconcile(expected: ExpectedSet) -> tuple[int, int]:
    """Query OpenFGA for each expected tuple; return (missing, leaked)."""
    from bisheng.core.openfga.manager import get_fga_client

    _print_banner('Stage 5 — Reconcile expected vs actual OpenFGA tuples')
    fga = get_fga_client()
    if fga is None:
        raise SystemExit('OpenFGA client not initialized.')

    missing = 0
    for user, relation, obj in sorted(expected.must_have):
        # read_tuples with all three fields is effectively a precise existence check
        tuples = await fga.read_tuples(user=user, relation=relation, object=obj)
        if tuples:
            continue
        missing += 1
        print(f'  ✗ MISSING: {user} {relation} {obj}')

    leaked = 0
    for user, relation, obj in sorted(expected.must_not_have):
        tuples = await fga.read_tuples(user=user, relation=relation, object=obj)
        if not tuples:
            continue
        leaked += 1
        print(f'  ✗ LEAKED:  {user} {relation} {obj}')

    _print_row('must_have present',
               f'{len(expected.must_have) - missing}/{len(expected.must_have)}',
               ok=(missing == 0))
    _print_row('must_not_have absent',
               f'{len(expected.must_not_have) - leaked}/{len(expected.must_not_have)}',
               ok=(leaked == 0))
    return missing, leaked


# ── Stage 6: Cleanup ──────────────────────────────────────────────

async def cleanup(session) -> None:
    from bisheng.core.openfga.manager import get_fga_client

    _print_banner('Stage 6 — Cleanup mock data')

    # MySQL rows (order matters only if there are FKs; these tables don't enforce)
    sql_deletes = [
        ("knowledgefile", f"id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
        ("channel",       "id LIKE 'mock-channel-%'"),
        ("t_gpts_tools",  f"id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
        ("knowledge",     f"id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
        ("flow",          "id LIKE 'mock-flow-%'"),
        ("space_channel_member", "business_id LIKE 'mock-scm-%'"),
        ("roleaccess",    f"(role_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}) "
                          f"OR (role_id = {ADMIN_ROLE_ID} AND third_id = 'kb-admin-leak') "
                          f"OR third_id LIKE 'kb-9000%' OR third_id LIKE 'mock-flow-%' "
                          f"OR third_id LIKE 'tool-9000%' OR third_id LIKE 'dash-9000%' "
                          f"OR third_id = 'menu-settings'"),
        ("usergroup",     f"user_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
        ("userrole",      f"user_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
        ("role",          f"id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
        ("group",         f"id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
        ("user",          f"user_id BETWEEN {MOCK_ID_LO} AND {MOCK_ID_HI}"),
    ]
    total_rows = 0
    for table, where in sql_deletes:
        res = _exec(session, f"DELETE FROM `{table}` WHERE {where}")
        total_rows += res.rowcount
        _print_row(f'{table} deleted', res.rowcount)
    session.commit()

    # OpenFGA tuples: delete every tuple that references a mock entity.
    # OpenFGA rejects read_tuples with only `user` (no object type), so we
    # enumerate all candidate objects — mock resources + system:global for
    # Step 1 super_admin.
    fga = get_fga_client()
    deleted = 0
    for obj in _collect_mock_object_refs():
        existing = await fga.read_tuples(object=obj)
        if not existing:
            continue
        await fga.write_tuples(deletes=[
            {'user': t['user'], 'relation': t['relation'], 'object': t['object']}
            for t in existing
        ])
        deleted += len(existing)

    # Step 1 super_admin lives on system:global; only delete mock-user entries.
    super_admin_tuples = await fga.read_tuples(
        relation='super_admin', object='system:global',
    )
    mock_super_admins = [
        t for t in super_admin_tuples
        if t['user'] in {f'user:{uid}' for uid in MOCK_USER_IDS}
    ]
    if mock_super_admins:
        await fga.write_tuples(deletes=mock_super_admins)
        deleted += len(mock_super_admins)
    _print_row('OpenFGA tuples deleted', deleted)
    _print_row('MySQL rows deleted total', total_rows)


def _collect_mock_object_refs() -> list[str]:
    """All OpenFGA object IDs that mock data could produce tuples for."""
    objs: list[str] = []
    # knowledge_space
    for kid in MOCK_KB_IDS:
        objs.append(f'knowledge_space:{kid}')
    # knowledge_space (from Step 4 space ids + Step 6 parent link)
    objs.extend(f'knowledge_space:{s}' for s in MOCK_SCM_SPACE_IDS)
    # roleaccess third_ids referenced by Step 3
    for tid in ('kb-90001', 'kb-90002', 'kb-admin-leak', 'menu-settings'):
        objs.append(f'knowledge_space:{tid}')
    for fid in MOCK_FLOW_IDS:
        objs.append(f'assistant:{fid}')
        objs.append(f'workflow:{fid}')
    for tid in MOCK_TOOL_IDS:
        objs.append(f'tool:{tid}')
    objs.extend(['tool:tool-90001', 'tool:tool-90002', 'tool:tool-90003'])
    objs.extend(['dashboard:dash-90001', 'dashboard:dash-90002'])
    for cid in MOCK_CHANNEL_IDS:
        objs.append(f'channel:{cid}')
    objs.extend(f'channel:{s}' for s in MOCK_SCM_CHANNEL_IDS)
    # folders & files
    for kf in MOCK_KF_IDS:
        objs.append(f'folder:{kf}')
        objs.append(f'knowledge_file:{kf}')
    # user_group (Step 2)
    for gid in MOCK_GROUP_IDS:
        objs.append(f'user_group:{gid}')
    return objs


# ── Orchestrator ──────────────────────────────────────────────────

async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--skip-cleanup', action='store_true',
                        help='Keep mock data in MySQL + FGA after the run')
    parser.add_argument('--cleanup-only', action='store_true',
                        help='Only run Stage 6 and exit (recover from failed run)')
    args = parser.parse_args()

    # Initialize app context: DB, Redis, OpenFGA, etc.
    from bisheng.common.services.config_service import settings
    from bisheng.core.context import initialize_app_context
    await initialize_app_context(config=settings)

    from bisheng.core.database import get_sync_db_session
    from bisheng.core.context.tenant import bypass_tenant_filter

    if args.cleanup_only:
        with get_sync_db_session() as session, bypass_tenant_filter():
            await cleanup(session)
        return 0

    expected: ExpectedSet | None = None
    try:
        with get_sync_db_session() as session, bypass_tenant_filter():
            precheck(session)
            expected = seed(session)

        stats = await reset_and_migrate()
        verify_report = await run_verify()
        missing, leaked = await reconcile(expected)

        _print_banner('Summary')
        _print_row('Migration tuples written', stats.total)
        _print_row('  Step 1 super_admin', stats.step1_super_admin)
        _print_row('  Step 2 user_group', stats.step2_user_group)
        _print_row('  Step 3 role_access', stats.step3_role_access)
        _print_row('  Step 4 SCM', stats.step4_space_channel)
        _print_row('  Step 5 owners', stats.step5_resource_owners)
        _print_row('  Step 6 folder', stats.step6_folder_hierarchy)
        _print_row('--verify regression', verify_report.regression,
                   ok=(verify_report.regression == 0))
        _print_row('must_have missing', missing, ok=(missing == 0))
        _print_row('must_not_have leaked', leaked, ok=(leaked == 0))

        passed = (verify_report.regression == 0 and missing == 0 and leaked == 0)
        print()
        print('=== OVERALL: {} ==='.format('PASS' if passed else 'FAIL'))

        if passed and not args.skip_cleanup:
            with get_sync_db_session() as session, bypass_tenant_filter():
                await cleanup(session)
        elif not passed:
            print('  → Mock data preserved for inspection. Run with '
                  '--cleanup-only when done.')

        return 0 if passed else 1

    except Exception:
        print('  → Exception raised; mock data left in place for inspection.')
        raise


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
