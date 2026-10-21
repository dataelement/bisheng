"""Generated titles cannot replace a concurrent rename or another tenant's row."""

from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine
from sqlmodel import Session

from bisheng.core.context.tenant import bypass_tenant_filter
from bisheng.database.models import session as session_module


@pytest.mark.parametrize(
    "existing_name,write_tenant,expected",
    [
        (None, 1, "Generated title"),
        ("", 1, "Generated title"),
        ("New Chat", 1, "Generated title"),
        ("My chosen title", 1, "My chosen title"),
        ("", 2, ""),
    ],
)
def test_generated_title_only_updates_default_name_in_own_tenant(monkeypatch, existing_name, write_tenant, expected):
    engine = create_engine("sqlite://")
    session_module.MessageSession.__table__.create(engine)

    @contextmanager
    def database_session():
        with Session(engine) as session:
            yield session

    monkeypatch.setattr(session_module, "get_sync_db_session", database_session)
    try:
        with bypass_tenant_filter():
            with Session(engine) as session:
                session.add(
                    session_module.MessageSession(
                        chat_id="generated-title", name=existing_name, tenant_id=1, flow_type=10, user_id=3
                    )
                )
                session.commit()
            updated = session_module.MessageSessionDao.update_session_name_sync(
                "generated-title", "Generated title", only_if_default=True, tenant_id=write_tenant
            )
            with Session(engine) as session:
                assert session.get(session_module.MessageSession, "generated-title").name == expected
            assert updated is (expected == "Generated title")
    finally:
        engine.dispose()
