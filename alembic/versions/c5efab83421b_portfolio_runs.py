"""portfolio batch runs (portfolio_runs + portfolio_run_items, fase 3 rollout)

Revision ID: c5efab83421b
Revises: b3c9d1e5f6a7
Create Date: 2026-08-28 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c5efab83421b'
down_revision: Union[str, None] = 'b3c9d1e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'portfolio_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('owner_key_id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('gas_price_usd_mcf', sa.Float(), nullable=False),
        sa.Column('max_steps', sa.Integer(), nullable=False),
        sa.Column('wells_total', sa.Integer(), nullable=False),
        sa.Column('wells_actionable', sa.Integer(), nullable=False),
        sa.Column('summary_json', sa.JSON(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_key_id'], ['api_keys.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portfolio_runs_owner_key_id'),
                    'portfolio_runs', ['owner_key_id'], unique=False)

    op.create_table(
        'portfolio_run_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('run_id', sa.Integer(), nullable=False),
        sa.Column('well_id', sa.Integer(), nullable=False),
        sa.Column('tag', sa.String(length=64), nullable=False),
        sa.Column('at_risk', sa.Boolean(), nullable=False),
        sa.Column('q_nominal_mscfd', sa.Float(), nullable=True),
        sa.Column('actionable', sa.Boolean(), nullable=False),
        sa.Column('intervention', sa.String(length=32), nullable=True),
        sa.Column('label', sa.String(length=128), nullable=True),
        sa.Column('cost_usd', sa.Float(), nullable=True),
        sa.Column('npv_usd', sa.Float(), nullable=True),
        sa.Column('roi_pct', sa.Float(), nullable=True),
        sa.Column('payback_months', sa.Integer(), nullable=True),
        sa.Column('incremental_gas_mmscf', sa.Float(), nullable=True),
        sa.Column('life_extension_days', sa.Float(), nullable=True),
        sa.ForeignKeyConstraint(['run_id'], ['portfolio_runs.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_portfolio_run_items_run_id'),
                    'portfolio_run_items', ['run_id'], unique=False)
    op.create_index(op.f('ix_portfolio_run_items_well_id'),
                    'portfolio_run_items', ['well_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_portfolio_run_items_well_id'),
                  table_name='portfolio_run_items')
    op.drop_index(op.f('ix_portfolio_run_items_run_id'),
                  table_name='portfolio_run_items')
    op.drop_table('portfolio_run_items')
    op.drop_index(op.f('ix_portfolio_runs_owner_key_id'),
                  table_name='portfolio_runs')
    op.drop_table('portfolio_runs')