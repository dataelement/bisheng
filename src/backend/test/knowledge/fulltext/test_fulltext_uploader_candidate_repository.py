from sqlalchemy import Column, String, text
from sqlmodel import Field, SQLModel

from bisheng.user.domain.repositories.implementations import user_repository_impl
from bisheng.user.domain.repositories.implementations.user_repository_impl import UserRepositoryImpl


class _UserFixture(SQLModel, table=True):
    """避免全局测试夹具对 User 模型的预加载替身污染当前仓储集成测试。"""

    __tablename__ = "user"
    __table_args__ = {"extend_existing": True}

    user_id: int | None = Field(default=None, primary_key=True)
    user_name: str = Field(sa_column=Column(String(255)))
    password: str = Field(default="x", sa_column=Column(String(255), nullable=False))
    delete: int = Field(default=0)


async def test_active_user_name_candidates_are_bounded_and_stable(
    async_db_session,
    monkeypatch,
):
    monkeypatch.setattr(user_repository_impl, "User", _UserFixture)
    await async_db_session.exec(
        text(
            """
            INSERT INTO user (user_id, user_name, password, "delete")
            VALUES (3, '张三', 'x', 0),
                   (2, '张安', 'x', 0),
                   (4, '张停用', 'x', 1),
                   (5, '李四', 'x', 0)
            """
        )
    )
    await async_db_session.commit()
    repository = UserRepositoryImpl(async_db_session)

    result = await repository.list_active_by_name(" 张 ", limit=2)

    assert [(item.user_id, item.user_name) for item in result] == [(3, "张三"), (2, "张安")]
