"""身份 SQL: bind 不改 A 用户; create 在 A 新建."""

from test.upgrade_ab_fusion._packutil import ensure_pack_path

ensure_pack_path()
from fusion.identity_sql import generate_identity_sql


def test_bind_has_no_update_user():
    sql, _alloc = generate_identity_sql(
        batch="b1",
        tenant_map=[{"b_tenant_id": "1", "a_tenant_id": "1", "action": "bind"}],
        user_map=[{"b_user_id": "7", "a_user_id": "100", "action": "bind", "note": "ok"}],
        b_users=[{"user_id": "7", "user_name": "bob"}],
        a_user_names={"alice"},
        next_user_id=200,
        dept_map=[],
        next_group_id=30,
        b_groups=[],
        b_usergroups=[],
        b_user_departments=[],
        role_map=[{"b_role_id": "1", "a_role_id": "1", "action": "bind"}],
        b_roles=[],
        b_userroles=[{"user_id": "7", "role_id": "1"}],
        next_role_id=40,
        a_tenant_id="1",
    )
    assert "UPDATE `user`" not in sql
    assert "INSERT INTO `user`" not in sql
    assert "fusion_map" in sql
    assert "userrole" in sql


def test_create_user_and_as_group_dept():
    sql, _alloc = generate_identity_sql(
        batch="b1",
        tenant_map=[{"b_tenant_id": "1", "a_tenant_id": "1", "action": "bind"}],
        user_map=[{"b_user_id": "7", "a_user_id": "", "action": "create"}],
        b_users=[{"user_id": "7", "user_name": "alice", "email": None}],
        a_user_names={"alice"},
        next_user_id=200,
        dept_map=[{"b_dept_pk": "3", "action": "as_group", "b_name": "本地科"}],
        next_group_id=30,
        b_groups=[],
        b_usergroups=[],
        b_user_departments=[{"user_id": "7", "department_id": "3", "is_primary": "1"}],
        role_map=[],
        b_roles=[],
        b_userroles=[],
        next_role_id=40,
        a_tenant_id="1",
    )
    assert "INSERT INTO `user`" in sql
    assert "user_id, 200" in sql or "200," in sql
    assert "[B迁移]" in sql
    assert ", '*'," in sql or ", '*'" in sql
    assert "usergroup" in sql


def test_create_drops_colliding_local_external_id():
    sql, _alloc = generate_identity_sql(
        batch="b1",
        tenant_map=[{"b_tenant_id": "1", "a_tenant_id": "1", "action": "bind"}],
        user_map=[{"b_user_id": "9", "a_user_id": "", "action": "create"}],
        b_users=[{"user_id": "9", "user_name": "wubing", "external_id": "wubing"}],
        a_user_names=set(),
        a_external_ids={"wubing"},
        next_user_id=300,
        dept_map=[],
        next_group_id=30,
        b_groups=[],
        b_usergroups=[],
        b_user_departments=[],
        role_map=[],
        b_roles=[],
        b_userroles=[],
        next_role_id=40,
        a_tenant_id="1",
    )
    assert "'wubing'" in sql
    assert ", NULL, NULL," in sql or "local', NULL," in sql


def test_create_drops_casefold_external_id():
    sql, _alloc = generate_identity_sql(
        batch="b1",
        tenant_map=[{"b_tenant_id": "1", "a_tenant_id": "1", "action": "bind"}],
        user_map=[{"b_user_id": "9", "a_user_id": "", "action": "create"}],
        b_users=[{"user_id": "9", "user_name": "test11", "external_id": "test11"}],
        a_user_names={"Test11"},
        a_external_ids={"Test11"},
        next_user_id=300,
        dept_map=[],
        next_group_id=30,
        b_groups=[],
        b_usergroups=[],
        b_user_departments=[],
        role_map=[],
        b_roles=[],
        b_userroles=[],
        next_role_id=40,
        a_tenant_id="1",
    )
    assert "[B迁移]" in sql
    assert "local', NULL," in sql or ", NULL, NULL," in sql


def test_create_copies_b_password_hash():
    sql, _alloc = generate_identity_sql(
        batch="b1",
        tenant_map=[{"b_tenant_id": "1", "a_tenant_id": "1", "action": "bind"}],
        user_map=[{"b_user_id": "7", "a_user_id": "", "action": "create"}],
        b_users=[
            {
                "user_id": "7",
                "user_name": "bob",
                "password": "5f4dcc3b5aa765d61d8327deb882cf99",
            }
        ],
        a_user_names=set(),
        next_user_id=200,
        dept_map=[],
        next_group_id=30,
        b_groups=[],
        b_usergroups=[],
        b_user_departments=[],
        role_map=[],
        b_roles=[],
        b_userroles=[],
        next_role_id=40,
        a_tenant_id="1",
    )
    assert "INSERT INTO `user`" in sql
    assert "'5f4dcc3b5aa765d61d8327deb882cf99'" in sql
    assert ", '*'," not in sql


def test_create_empty_password_stays_unusable():
    sql, _alloc = generate_identity_sql(
        batch="b1",
        tenant_map=[{"b_tenant_id": "1", "a_tenant_id": "1", "action": "bind"}],
        user_map=[{"b_user_id": "7", "a_user_id": "", "action": "create"}],
        b_users=[{"user_id": "7", "user_name": "bob", "password": "NULL"}],
        a_user_names=set(),
        next_user_id=200,
        dept_map=[],
        next_group_id=30,
        b_groups=[],
        b_usergroups=[],
        b_user_departments=[],
        role_map=[],
        b_roles=[],
        b_userroles=[],
        next_role_id=40,
        a_tenant_id="1",
    )
    assert ", '*'," in sql or ", '*'" in sql


def test_bind_does_not_copy_b_password():
    sql, _alloc = generate_identity_sql(
        batch="b1",
        tenant_map=[{"b_tenant_id": "1", "a_tenant_id": "1", "action": "bind"}],
        user_map=[{"b_user_id": "7", "a_user_id": "100", "action": "bind"}],
        b_users=[
            {
                "user_id": "7",
                "user_name": "bob",
                "password": "5f4dcc3b5aa765d61d8327deb882cf99",
            }
        ],
        a_user_names={"alice"},
        next_user_id=200,
        dept_map=[],
        next_group_id=30,
        b_groups=[],
        b_usergroups=[],
        b_user_departments=[],
        role_map=[{"b_role_id": "1", "a_role_id": "1", "action": "bind"}],
        b_roles=[],
        b_userroles=[],
        next_role_id=40,
        a_tenant_id="1",
    )
    assert "UPDATE `user`" not in sql
    assert "INSERT INTO `user`" not in sql
    assert "5f4dcc3b5aa765d61d8327deb882cf99" not in sql
