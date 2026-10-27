"""审计用户反馈里的反馈意见按至少 1 条筛选."""

from sqlalchemy.dialects import mysql
from sqlmodel import select

from bisheng.database.models.session import MessageSession, feedback_opinion_count


def test_feedback_opinion_filter_requires_at_least_one_comment():
    statement = select(MessageSession.chat_id).where(feedback_opinion_count() > 0)
    sql = str(statement.compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "count(" in sql.lower()
    assert "> 0" in sql
    assert "break_answer" in sql
    assert "inaction" in sql
