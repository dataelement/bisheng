"""Tests for Group and UserGroup DAO operations (F003).

Uses a self-contained SQLite engine with raw SQL helpers to avoid
premock conflicts with bisheng.database.models.group (which is in
PREMOCK_MODULES). Follows the factories.py pattern.
"""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session


@pytest.fixture(scope='module')
def dao_engine():
    """SQLite engine with Group/UserGroup/User tables."""
    engine = create_engine(
        'sqlite://',
        connect_args={'check_same_thread': False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS "group" (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_name VARCHAR(255),
                remark VARCHAR(512),
                tenant_id INTEGER NOT NULL DEFAULT 1,
                visibility VARCHAR(16) NOT NULL DEFAULT 'public',
                create_user INTEGER,
                update_user INTEGER,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                UNIQUE(tenant_id, group_name)
            )
        '''))
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS usergroup (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                group_id INTEGER,
                is_group_admin INTEGER DEFAULT 0,
                tenant_id INTEGER NOT NULL DEFAULT 1,
                remark VARCHAR(512),
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        '''))
        conn.execute(text('''
            CREATE TABLE IF NOT EXISTS user (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_name VARCHAR(255) UNIQUE,
                password VARCHAR(255) NOT NULL DEFAULT 'hashed',
                "delete" INTEGER DEFAULT 0,
                create_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL,
                password_update_time DATETIME DEFAULT CURRENT_TIMESTAMP NOT NULL
            )
        '''))
    yield engine
    engine.dispose()


@pytest.fixture()
def session(dao_engine):
    """Transactional session that rolls back after each test."""
    connection = dao_engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    if transaction.is_active:
        transaction.rollback()
    connection.close()


# ---------------------------------------------------------------------------
# Raw SQL helpers (avoid ORM import / premock conflicts)
# ---------------------------------------------------------------------------

def _create_group(session, group_name, tenant_id=1, visibility='public', create_user=1):
    session.execute(text(
        'INSERT INTO "group" (group_name, tenant_id, visibility, create_user) '
        'VALUES (:name, :tid, :vis, :cu)'
    ), {'name': group_name, 'tid': tenant_id, 'vis': visibility, 'cu': create_user})
    session.flush()
    row = session.execute(text(
        'SELECT * FROM "group" WHERE group_name = :name AND tenant_id = :tid'
    ), {'name': group_name, 'tid': tenant_id}).mappings().one()
    return dict(row)


def _create_user(session, user_name):
    session.execute(text(
        "INSERT INTO user (user_name, password) VALUES (:name, 'hashed')"
    ), {'name': user_name})
    session.flush()
    row = session.execute(text(
        'SELECT user_id FROM user WHERE user_name = :name'
    ), {'name': user_name}).one()
    return row[0]


def _add_member(session, user_id, group_id, is_admin=0, tenant_id=1):
    session.execute(text(
        'INSERT INTO usergroup (user_id, group_id, is_group_admin, tenant_id) '
        'VALUES (:uid, :gid, :admin, :tid)'
    ), {'uid': user_id, 'gid': group_id, 'admin': is_admin, 'tid': tenant_id})
    session.flush()


# =========================================================================
# Group table tests
# =========================================================================

class TestGroupModel:

    def test_create_group(self, session):
        g = _create_group(session, 'Alpha')
        assert g['id'] is not None
        assert g['group_name'] == 'Alpha'
        assert g['visibility'] == 'public'
        assert g['tenant_id'] == 1

    def test_create_group_private(self, session):
        g = _create_group(session, 'Secret', visibility='private')
        assert g['visibility'] == 'private'

    def test_name_unique_within_tenant(self, session):
        _create_group(session, 'Dup', tenant_id=1)
        from sqlalchemy.exc import IntegrityError
        with pytest.raises(IntegrityError):
            _create_group(session, 'Dup', tenant_id=1)
        session.rollback()

    def test_name_unique_across_tenants(self, session):
        """Same name in different tenants should succeed."""
        _create_group(session, 'CrossTenant', tenant_id=1)
        g2 = _create_group(session, 'CrossTenant', tenant_id=2)
        assert g2['id'] is not None
        assert g2['tenant_id'] == 2

    def test_update_group(self, session):
        g = _create_group(session, 'Updatable')
        session.execute(text(
            'UPDATE "group" SET group_name = :new WHERE id = :id'
        ), {'new': 'Updated', 'id': g['id']})
        session.flush()
        row = session.execute(text(
            'SELECT group_name FROM "group" WHERE id = :id'
        ), {'id': g['id']}).one()
        assert row[0] == 'Updated'

    def test_delete_group(self, session):
        g = _create_group(session, 'ToDelete')
        session.execute(text('DELETE FROM "group" WHERE id = :id'), {'id': g['id']})
        session.flush()
        row = session.execute(text(
            'SELECT * FROM "group" WHERE id = :id'
        ), {'id': g['id']}).mappings().first()
        assert row is None

    def test_query_by_visibility(self, session):
        _create_group(session, 'Pub1', visibility='public')
        _create_group(session, 'Priv1', visibility='private')
        _create_group(session, 'Pub2', visibility='public')
        rows = session.execute(text(
            "SELECT * FROM \"group\" WHERE visibility = 'public'"
        )).mappings().all()
        assert len(rows) >= 2

    def test_keyword_filter(self, session):
        _create_group(session, 'ProjectX')
        _create_group(session, 'ProjectY')
        _create_group(session, 'Other')
        rows = session.execute(text(
            "SELECT * FROM \"group\" WHERE group_name LIKE '%Project%'"
        )).mappings().all()
        assert len(rows) == 2

    def test_paged_query(self, session):
        """Pagination: page=1, limit=2 of 3 groups."""
        _create_group(session, 'Page1')
        _create_group(session, 'Page2')
        _create_group(session, 'Page3')
        rows = session.execute(text(
            'SELECT * FROM "group" WHERE tenant_id = 1 LIMIT 2 OFFSET 0'
        )).mappings().all()
        assert len(rows) == 2
        total = session.execute(text(
            'SELECT COUNT(*) FROM "group" WHERE tenant_id = 1'
        )).scalar()
        assert total == 3


# =========================================================================
# UserGroup (member/admin) tests
# =========================================================================

class TestUserGroupModel:

    def test_add_member(self, session):
        g = _create_group(session, 'MemberTest')
        uid = _create_user(session, 'member_u1')
        _add_member(session, uid, g['id'])
        row = session.execute(text(
            'SELECT * FROM usergroup WHERE user_id = :uid AND group_id = :gid'
        ), {'uid': uid, 'gid': g['id']}).mappings().one()
        assert row['is_group_admin'] == 0

    def test_add_admin(self, session):
        g = _create_group(session, 'AdminTest')
        uid = _create_user(session, 'admin_u1')
        _add_member(session, uid, g['id'], is_admin=1)
        row = session.execute(text(
            'SELECT is_group_admin FROM usergroup WHERE user_id = :uid AND group_id = :gid'
        ), {'uid': uid, 'gid': g['id']}).one()
        assert row[0] == 1

    def test_member_count_excludes_admin(self, session):
        g = _create_group(session, 'CountTest')
        u1 = _create_user(session, 'cnt_u1')
        u2 = _create_user(session, 'cnt_u2')
        u3 = _create_user(session, 'cnt_u3')
        _add_member(session, u1, g['id'])
        _add_member(session, u2, g['id'])
        _add_member(session, u3, g['id'])
        _add_member(session, u1, g['id'], is_admin=1)  # admin row, not counted

        count = session.execute(text(
            'SELECT COUNT(*) FROM usergroup '
            'WHERE group_id = :gid AND is_group_admin = 0'
        ), {'gid': g['id']}).scalar()
        assert count == 3

    def test_remove_member(self, session):
        g = _create_group(session, 'RemoveTest')
        uid = _create_user(session, 'remove_u1')
        _add_member(session, uid, g['id'])

        session.execute(text(
            'DELETE FROM usergroup '
            'WHERE user_id = :uid AND group_id = :gid AND is_group_admin = 0'
        ), {'uid': uid, 'gid': g['id']})
        session.flush()

        count = session.execute(text(
            'SELECT COUNT(*) FROM usergroup '
            'WHERE user_id = :uid AND group_id = :gid'
        ), {'uid': uid, 'gid': g['id']}).scalar()
        assert count == 0

    def test_check_members_exist(self, session):
        g = _create_group(session, 'ExistTest')
        u1 = _create_user(session, 'exist_u1')
        u2 = _create_user(session, 'exist_u2')
        _add_member(session, u1, g['id'])

        rows = session.execute(text(
            'SELECT user_id FROM usergroup '
            'WHERE group_id = :gid AND user_id IN (:u1, :u2)'
        ), {'gid': g['id'], 'u1': u1, 'u2': u2}).all()
        existing_ids = {r[0] for r in rows}
        assert u1 in existing_ids
        assert u2 not in existing_ids

    def test_admins_detail_with_join(self, session):
        g = _create_group(session, 'AdminDetailTest')
        u1 = _create_user(session, 'adm_d_u1')
        u2 = _create_user(session, 'adm_d_u2')
        _add_member(session, u1, g['id'], is_admin=1)
        _add_member(session, u2, g['id'], is_admin=1)

        rows = session.execute(text(
            'SELECT ug.user_id, u.user_name '
            'FROM usergroup ug '
            'JOIN user u ON ug.user_id = u.user_id '
            'WHERE ug.group_id = :gid AND ug.is_group_admin = 1'
        ), {'gid': g['id']}).all()
        assert len(rows) == 2
        names = {r[1] for r in rows}
        assert 'adm_d_u1' in names
        assert 'adm_d_u2' in names

    def test_set_admins_batch_diff(self, session):
        """Replace admins: {u1,u2} → {u2,u3}."""
        g = _create_group(session, 'AdminBatchTest')
        u1 = _create_user(session, 'batch_u1')
        u2 = _create_user(session, 'batch_u2')
        u3 = _create_user(session, 'batch_u3')

        _add_member(session, u1, g['id'], is_admin=1)
        _add_member(session, u2, g['id'], is_admin=1)

        # Remove u1, add u3
        session.execute(text(
            'DELETE FROM usergroup '
            'WHERE group_id = :gid AND user_id = :uid AND is_group_admin = 1'
        ), {'gid': g['id'], 'uid': u1})
        session.execute(text(
            'INSERT INTO usergroup (user_id, group_id, is_group_admin, tenant_id) '
            'VALUES (:uid, :gid, 1, 1)'
        ), {'uid': u3, 'gid': g['id']})
        session.flush()

        rows = session.execute(text(
            'SELECT user_id FROM usergroup '
            'WHERE group_id = :gid AND is_group_admin = 1'
        ), {'gid': g['id']}).all()
        admin_ids = {r[0] for r in rows}
        assert admin_ids == {u2, u3}

    def test_user_visible_group_ids(self, session):
        g1 = _create_group(session, 'Vis1')
        g2 = _create_group(session, 'Vis2')
        _create_group(session, 'Vis3')  # not a member
        uid = _create_user(session, 'vis_user')
        _add_member(session, uid, g1['id'])
        _add_member(session, uid, g2['id'])

        rows = session.execute(text(
            'SELECT group_id FROM usergroup WHERE user_id = :uid'
        ), {'uid': uid}).all()
        group_ids = {r[0] for r in rows}
        assert group_ids == {g1['id'], g2['id']}

    def test_members_paged_with_join(self, session):
        g = _create_group(session, 'PagedMembersTest')
        for i in range(5):
            uid = _create_user(session, f'paged_u{i}')
            _add_member(session, uid, g['id'])

        # Page 1, limit 2
        rows = session.execute(text(
            'SELECT ug.user_id, u.user_name '
            'FROM usergroup ug '
            'JOIN user u ON ug.user_id = u.user_id '
            'WHERE ug.group_id = :gid AND ug.is_group_admin = 0 AND u."delete" = 0 '
            'LIMIT 2 OFFSET 0'
        ), {'gid': g['id']}).all()
        assert len(rows) == 2

        total = session.execute(text(
            'SELECT COUNT(*) FROM usergroup '
            'WHERE group_id = :gid AND is_group_admin = 0'
        ), {'gid': g['id']}).scalar()
        assert total == 5
