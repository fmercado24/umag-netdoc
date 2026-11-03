"""acceso

Sesiones del administrador e intentos de ingreso, que limitan los que puede
hacer cada equipo.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-03 11:02:14.310882
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005'
down_revision: Union[str, None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('intento_ingreso',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cliente', sa.String(length=45), nullable=False),
    sa.Column('ocurrido_en', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_intento_ingreso'))
    )
    with op.batch_alter_table('intento_ingreso', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_intento_ingreso_cliente'), ['cliente'], unique=False)
        batch_op.create_index(batch_op.f('ix_intento_ingreso_ocurrido_en'), ['ocurrido_en'], unique=False)

    op.create_table('sesion_acceso',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('cliente', sa.String(length=45), nullable=False),
    sa.Column('creada_en', sa.Float(), nullable=False),
    sa.Column('ultimo_uso', sa.Float(), nullable=False),
    sa.Column('vence_en', sa.Float(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sesion_acceso')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_sesion_acceso_token_hash'))
    )


def downgrade() -> None:
    op.drop_table('sesion_acceso')
    with op.batch_alter_table('intento_ingreso', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_intento_ingreso_ocurrido_en'))
        batch_op.drop_index(batch_op.f('ix_intento_ingreso_cliente'))

    op.drop_table('intento_ingreso')
