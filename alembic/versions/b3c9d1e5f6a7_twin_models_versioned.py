"""versioned digital twin models (twin_models, fase 2.1)

Revision ID: b3c9d1e5f6a7
Revises: f4a11e7c2b90
Create Date: 2026-08-28 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c9d1e5f6a7'
down_revision: Union[str, None] = 'f4a11e7c2b90'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'twin_models',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('well_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('trained_at', sa.DateTime(), nullable=False),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('source', sa.String(length=16), nullable=False),
        sa.Column('n_points', sa.Integer(), nullable=False),
        sa.Column('mae_psi', sa.Float(), nullable=True),
        sa.Column('r2', sa.Float(), nullable=True),
        sa.Column('residual_mean_psi', sa.Float(), nullable=True),
        sa.Column('residual_std_psi', sa.Float(), nullable=True),
        sa.Column('features', sa.String(length=512), nullable=False),
        sa.Column('ml_path', sa.String(length=512), nullable=False),
        sa.ForeignKeyConstraint(['well_id'], ['wells.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('well_id', 'version',
                            name='uq_twin_well_version')
    )
    op.create_index(op.f('ix_twin_models_well_id'), 'twin_models',
                    ['well_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_twin_models_well_id'), table_name='twin_models')
    op.drop_table('twin_models')