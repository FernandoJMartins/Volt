"""proxy dedicado por conta do X (isolamento de IP)

Revision ID: f1a2b3c4d5e6
Revises: e8f9a0b1c2d3
Create Date: 2026-08-31 21:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'x_accounts',
        sa.Column('proxy_url_encrypted', sa.Text(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('x_accounts', 'proxy_url_encrypted')
