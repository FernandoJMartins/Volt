"""pool manual de textos: separa por plataforma (x/threads)

Revision ID: d4e5f6a7b8c9
Revises: e5f6a7b8c9d0
Create Date: 2026-09-09 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'e5f6a7b8c9d0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'manual_source_texts',
        sa.Column('platform', sa.String(length=16), nullable=False, server_default='x'),
    )


def downgrade() -> None:
    op.drop_column('manual_source_texts', 'platform')
