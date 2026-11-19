"""N° de Inventario UMAG

Además del número de serie del fabricante, cada equipo lleva la etiqueta de
activo fijo de la universidad: un número, que se guarda como texto por los
ceros iniciales.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-18 15:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009'
down_revision: Union[str, None] = '0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('elemento', schema=None) as batch_op:
        batch_op.add_column(sa.Column('numero_inventario', sa.String(length=30), nullable=True))
        batch_op.create_index(batch_op.f('ix_elemento_numero_inventario'), ['numero_inventario'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('elemento', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_elemento_numero_inventario'))
        batch_op.drop_column('numero_inventario')
