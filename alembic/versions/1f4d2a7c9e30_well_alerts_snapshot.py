"""well alerts snapshot table (alert engine, fase 1)

Revision ID: 1f4d2a7c9e30
Revises: 6f3cb4ae9f25
Create Date: 2026-08-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '1f4d2a7c9e30'
down_revision: Union[str, None] = '6f3cb4ae9f25'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('well_alerts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('well_id', sa.Integer(), nullable=False),
    sa.Column('computed_at', sa.DateTime(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('severity', sa.String(length=8), nullable=False),
    sa.Column('status', sa.String(length=16), nullable=False),
    sa.Column('message', sa.String(length=512), nullable=False),
    sa.Column('margin_pct', sa.Float(), nullable=True),
    sa.Column('days_to_risk', sa.Integer(), nullable=True),
    sa.Column('v_actual_ft_s', sa.Float(), nullable=True),
    sa.Column('v_crit_ft_s', sa.Float(), nullable=True),
    sa.Column('q_crit_mscfd', sa.Float(), nullable=True),
    sa.Column('metastable_regime', sa.String(length=16), nullable=True),
    sa.Column('q_min_stable_mscfd', sa.Float(), nullable=True),
    sa.Column('last_notified_severity', sa.String(length=8), nullable=True),
    sa.ForeignKeyConstraint(['well_id'], ['wells.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_well_alerts_computed_at'), 'well_alerts',
                    ['computed_at'], unique=False)
    op.create_index(op.f('ix_well_alerts_well_id'), 'well_alerts',
                    ['well_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_well_alerts_well_id'), table_name='well_alerts')
    op.drop_index(op.f('ix_well_alerts_computed_at'), table_name='well_alerts')
    op.drop_table('well_alerts')