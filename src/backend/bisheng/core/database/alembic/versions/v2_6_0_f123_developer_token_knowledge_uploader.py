"""Add knowledge uploader user id to developer_token.

Revision ID: f123_developer_token_knowledge_uploader
Revises: f122_knowledge_upload_batch

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f123_developer_token_knowledge_uploader"
down_revision: str | Sequence[str] | None = "f122_knowledge_upload_batch"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("developer_token")}
    if "knowledge_uploader_user_id" not in columns:
        op.add_column(
            "developer_token",
            sa.Column(
                "knowledge_uploader_user_id",
                sa.Integer(),
                nullable=True,
                index=True,
                comment="知识上传人用户 ID（Filelib 未传 external_id 时写入知识文件的上传人）",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {col["name"] for col in inspector.get_columns("developer_token")}
    if "knowledge_uploader_user_id" in columns:
        with op.batch_alter_table("developer_token") as batch:
            batch.drop_column("knowledge_uploader_user_id")
