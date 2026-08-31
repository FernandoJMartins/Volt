"""posts_per_collect em monitored_accounts (quantidade por coleta)

Revision ID: e8f9a0b1c2d3
Revises: c4f1a2b3d5e6
Create Date: 2026-08-31 06:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'c4f1a2b3d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'monitored_accounts',
        sa.Column('posts_per_collect', sa.Integer(), nullable=False, server_default='15'),
    )


def downgrade() -> None:
    op.drop_column('monitored_accounts', 'posts_per_collect')
