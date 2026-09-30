from sqlalchemy import Column, ForeignKey, Integer, event
from sqlalchemy.orm import declarative_base, relationship
from sqlmodel import Session, create_engine

from bisheng.user.domain.repositories.implementations import user_repository_impl as module


def test_user_batch_loads_relations_without_per_user_queries(monkeypatch):
    base = declarative_base()

    class BatchUser(base):
        __tablename__ = "batch_user"
        user_id = Column(Integer, primary_key=True)

    for name in ("groups", "roles", "departments"):
        child = type(
            name,
            (base,),
            {
                "__tablename__": f"batch_{name}",
                "id": Column(Integer, primary_key=True),
                "user_id": Column(Integer, ForeignKey("batch_user.user_id")),
            },
        )
        setattr(BatchUser, name, relationship(child))
    engine = create_engine("sqlite://")
    statements = []
    try:
        base.metadata.create_all(engine)
        with Session(engine) as session:
            session.add_all(BatchUser(user_id=uid) for uid in range(1, 101))
            session.commit()
        monkeypatch.setattr(module, "User", BatchUser)
        event.listen(
            engine, "before_cursor_execute", lambda conn, cursor, statement, *args: statements.append(statement)
        )
        with Session(engine) as session:
            users = module.UserRepositoryImpl(session).get_users_with_groups_and_roles_by_ids_sync([*range(1, 101), 1])
        assert len(users) == 100
        assert all(user.groups == user.roles == user.departments == [] for user in users)
        assert len(statements) == 4
    finally:
        engine.dispose()
