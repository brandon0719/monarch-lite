"""manual accounts

Revision ID: 7ff41b267774
Revises: ceb50a8ccf06
Create Date: 2026-10-17 03:16:56.995050

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7ff41b267774'
down_revision: Union[str, Sequence[str], None] = 'ceb50a8ccf06'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain ADD COLUMN, never batch: a batch rebuild of `accounts` drops the table, and with foreign keys on that
    # cascades into transactions, balance_snapshots and rules. SQLite adds a column with a constant default in place.
    op.add_column('accounts', sa.Column('is_manual', sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    # Native DROP COLUMN (SQLite >= 3.35); no table rebuild.
    op.drop_column('accounts', 'is_manual')
