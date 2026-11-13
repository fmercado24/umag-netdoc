"""versión del elemento

Un contador que sube en cada cambio del elemento: permite avisarle a quien lo
está editando que otra persona lo modificó entretanto.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-13 09:40:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0007'
down_revision: Union[str, None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('elemento', schema=None) as batch_op:
        batch_op.add_column(sa.Column('version', sa.Integer(), server_default='1', nullable=False))


def downgrade() -> None:
    with op.batch_alter_table('elemento', schema=None) as batch_op:
        batch_op.drop_column('version')
