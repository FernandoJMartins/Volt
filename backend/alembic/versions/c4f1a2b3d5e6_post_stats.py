"""post_stats (Fase 5 — analytics)

Revision ID: c4f1a2b3d5e6
Revises: 66dd00beb93a
Create Date: 2026-08-31 05:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c4f1a2b3d5e6'
down_revision: Union[str, None] = '66dd00beb93a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'post_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('scheduled_post_id', sa.Integer(), nullable=False),
        sa.Column('x_account_id', sa.Integer(), nullable=False),
        sa.Column('likes', sa.Integer(), nullable=False),
        sa.Column('reposts', sa.Integer(), nullable=False),
        sa.Column('replies', sa.Integer(), nullable=False),
        sa.Column('views', sa.Integer(), nullable=False),
        sa.Column('snapshots', sa.JSON(), nullable=False),
        sa.Column('first_collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_collected_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['scheduled_post_id'], ['scheduled_posts.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['x_account_id'], ['x_accounts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_post_stats_user_id', 'post_stats', ['user_id'])
    op.create_index('ix_post_stats_scheduled_post_id', 'post_stats', ['scheduled_post_id'], unique=True)
    op.create_index('ix_post_stats_x_account_id', 'post_stats', ['x_account_id'])


def downgrade() -> None:
    op.drop_index('ix_post_stats_x_account_id', table_name='post_stats')
    op.drop_index('ix_post_stats_scheduled_post_id', table_name='post_stats')
    op.drop_index('ix_post_stats_user_id', table_name='post_stats')
    op.drop_table('post_stats')
