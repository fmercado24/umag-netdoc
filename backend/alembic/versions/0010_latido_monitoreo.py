"""Latido de las herramientas de monitoreo

Los avisos de Zabbix y Alertmanager llegan solo cuando algo cambia: para
saber que una herramienta dejó de informar, se guarda cuándo se supo de ella
por última vez (requisito RNF5, SOP 11.3).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-19 15:00:00.000000
"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010'
down_revision: Union[str, None] = '0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('latido_monitoreo',
    sa.Column('fuente', sa.String(length=40), nullable=False),
    sa.Column('ultimo_contacto', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('fuente', name=op.f('pk_latido_monitoreo'))
    )


def downgrade() -> None:
    op.drop_table('latido_monitoreo')
