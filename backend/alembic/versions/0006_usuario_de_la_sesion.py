"""usuario de la sesión

Cada sesión guarda de quién es: además del administrador puede haber otros
usuarios, algunos limitados a un edificio.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-12 10:20:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0006'
down_revision: Union[str, None] = '0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Las sesiones abiertas no dicen de quién son: se cierran y hay que volver a ingresar.
    op.execute("DELETE FROM sesion_acceso")
    with op.batch_alter_table('sesion_acceso', schema=None) as batch_op:
        batch_op.add_column(sa.Column('usuario', sa.String(length=100), nullable=False))
        batch_op.create_index(batch_op.f('ix_sesion_acceso_usuario'), ['usuario'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('sesion_acceso', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_sesion_acceso_usuario'))
        batch_op.drop_column('usuario')
