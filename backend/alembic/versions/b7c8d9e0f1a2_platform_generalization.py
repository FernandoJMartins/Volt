"""generaliza x_accounts/monitored_accounts/source_posts/scheduled_posts/
post_stats/content_candidates pra suportar mais de uma plataforma (campo
platform, "x" ou "threads") — ver plano de integracao Threads.

Revision ID: b7c8d9e0f1a2
Revises: a2b3c4d5e6f7
Create Date: 2026-09-02 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- x_accounts -> accounts ----
    op.rename_table('x_accounts', 'accounts')
    op.add_column(
        'accounts',
        sa.Column('platform', sa.String(length=16), nullable=False, server_default='x'),
    )
    # Mesma regra de negocio que ja existia via settings.MEDIA_REQUIRED (global);
    # agora e' por conta, semeada com o comportamento antigo (exigia sempre).
    op.add_column(
        'accounts',
        sa.Column('media_required', sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute('ALTER INDEX ix_x_accounts_user_id RENAME TO ix_accounts_user_id')
    op.execute('ALTER INDEX ix_x_accounts_x_user_id RENAME TO ix_accounts_x_user_id')
    op.execute('ALTER INDEX uq_user_xaccount RENAME TO uq_user_account')

    # ---- monitored_accounts: so' ganha platform (nome da tabela ja' generico) ----
    op.add_column(
        'monitored_accounts',
        sa.Column('platform', sa.String(length=16), nullable=False, server_default='x'),
    )

    # ---- source_posts: platform + rename x_post_id -> platform_post_id ----
    op.add_column(
        'source_posts',
        sa.Column('platform', sa.String(length=16), nullable=False, server_default='x'),
    )
    op.alter_column('source_posts', 'x_post_id', new_column_name='platform_post_id')
    op.execute('ALTER INDEX ix_source_posts_x_post_id RENAME TO ix_source_posts_platform_post_id')

    # ---- content_candidates.target_x_account_id -> target_account_id ----
    op.alter_column('content_candidates', 'target_x_account_id', new_column_name='target_account_id')
    op.execute(
        'ALTER INDEX ix_content_candidates_target_x_account_id '
        'RENAME TO ix_content_candidates_target_account_id'
    )

    # ---- scheduled_posts.x_account_id -> account_id ----
    op.alter_column('scheduled_posts', 'x_account_id', new_column_name='account_id')
    op.execute('ALTER INDEX ix_scheduled_posts_x_account_id RENAME TO ix_scheduled_posts_account_id')

    # ---- post_stats.x_account_id -> account_id ----
    op.alter_column('post_stats', 'x_account_id', new_column_name='account_id')
    op.execute('ALTER INDEX ix_post_stats_x_account_id RENAME TO ix_post_stats_account_id')

    # retweet_jobs fica de fora de proposito (conceito e' X-only por ora); as FKs
    # dela pra x_accounts continuam validas automaticamente apos o rename_table.


def downgrade() -> None:
    op.execute('ALTER INDEX ix_post_stats_account_id RENAME TO ix_post_stats_x_account_id')
    op.alter_column('post_stats', 'account_id', new_column_name='x_account_id')

    op.execute('ALTER INDEX ix_scheduled_posts_account_id RENAME TO ix_scheduled_posts_x_account_id')
    op.alter_column('scheduled_posts', 'account_id', new_column_name='x_account_id')

    op.execute(
        'ALTER INDEX ix_content_candidates_target_account_id '
        'RENAME TO ix_content_candidates_target_x_account_id'
    )
    op.alter_column('content_candidates', 'target_account_id', new_column_name='target_x_account_id')

    op.execute('ALTER INDEX ix_source_posts_platform_post_id RENAME TO ix_source_posts_x_post_id')
    op.alter_column('source_posts', 'platform_post_id', new_column_name='x_post_id')
    op.drop_column('source_posts', 'platform')

    op.drop_column('monitored_accounts', 'platform')

    op.execute('ALTER INDEX uq_user_account RENAME TO uq_user_xaccount')
    op.execute('ALTER INDEX ix_accounts_x_user_id RENAME TO ix_x_accounts_x_user_id')
    op.execute('ALTER INDEX ix_accounts_user_id RENAME TO ix_x_accounts_user_id')
    op.drop_column('accounts', 'media_required')
    op.drop_column('accounts', 'platform')
    op.rename_table('accounts', 'x_accounts')
