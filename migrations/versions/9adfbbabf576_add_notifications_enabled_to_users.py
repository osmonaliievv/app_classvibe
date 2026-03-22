"""add notifications_enabled to users

Revision ID: 9adfbbabf576
Revises: b1978d86f0ab
Create Date: 2026-03-17 05:39:45.493423

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9adfbbabf576'
down_revision: Union[str, Sequence[str], None] = 'b1978d86f0ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ✅ Сначала добавляем с NULL разрешённым
    op.add_column('users', sa.Column('notifications_enabled', sa.Boolean(), nullable=True))

    # ✅ Заполняем существующие строки значением True
    op.execute("UPDATE users SET notifications_enabled = TRUE WHERE notifications_enabled IS NULL")

    # ✅ Теперь делаем NOT NULL
    op.alter_column('users', 'notifications_enabled', nullable=False)


def downgrade() -> None:
    op.drop_column('users', 'notifications_enabled')