"""piloto automatico por conta (auto_pilot, content_mode)

Revision ID: a2b3c4d5e6f7
Revises: f1a2b3c4d5e6
Create Date: 2026-09-01 01:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'x_accounts',
        sa.Column('auto_pilot', sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        'x_accounts',
        sa.Column('content_mode', sa.String(length=8), nullable=False, server_default='ai'),
    )


def downgrade() -> None:
    op.drop_column('x_accounts', 'content_mode')
    op.drop_column('x_accounts', 'auto_pilot')
