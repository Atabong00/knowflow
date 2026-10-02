"""add search indexes with pg_trgm

Revision ID: 002
Revises: 001
Create Date: 2026-08-16 09:35:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_title_trgm ON documents USING GIN (title gin_trgm_ops)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_documents_content_trgm ON documents USING GIN (content gin_trgm_ops)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_documents_content_trgm")
    op.execute("DROP INDEX IF EXISTS ix_documents_title_trgm")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
