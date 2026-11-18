"""lectura de los recintos de cada plano

Los planos que se cargan desde el visor se leen con OCR en segundo plano:
``lectura_recintos`` dice en qué va y ``lectura_aviso`` cómo terminó. Los
planos vigentes que aún no tienen recintos quedan pendientes, para que el
sistema los lea al arrancar.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-18 10:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008'
down_revision: Union[str, None] = '0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('plano', schema=None) as batch_op:
        batch_op.add_column(sa.Column('lectura_recintos', sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column('lectura_aviso', sa.String(length=300), nullable=True))

    plano = sa.table(
        'plano',
        sa.column('id', sa.Integer),
        sa.column('vigente', sa.Boolean),
        sa.column('lectura_recintos', sa.String),
    )
    recinto = sa.table('recinto', sa.column('plano_id', sa.Integer))
    op.execute(
        plano.update()
        .where(
            plano.c.vigente == sa.true(),
            ~sa.exists().where(recinto.c.plano_id == plano.c.id),
        )
        .values(lectura_recintos='pendiente')
    )


def downgrade() -> None:
    with op.batch_alter_table('plano', schema=None) as batch_op:
        batch_op.drop_column('lectura_aviso')
        batch_op.drop_column('lectura_recintos')
