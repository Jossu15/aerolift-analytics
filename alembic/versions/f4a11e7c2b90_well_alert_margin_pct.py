"""per-well alert threshold (alert_margin_pct, fase 1.5)

Revision ID: f4a11e7c2b90
Revises: 1f4d2a7c9e30
Create Date: 2026-08-28 12:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4a11e7c2b90'
down_revision: Union[str, None] = '1f4d2a7c9e30'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'wells',
        sa.Column('alert_margin_pct', sa.Float(), nullable=False,
                  server_default='20.0'))


def downgrade() -> None:
    op.drop_column('wells', 'alert_margin_pct')