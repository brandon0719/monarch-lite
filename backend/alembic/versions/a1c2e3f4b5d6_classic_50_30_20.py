"""classic 50/30/20: rent counts in needs

Revision ID: a1c2e3f4b5d6
Revises: 745c340b56e1
Create Date: 2026-10-16 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1c2e3f4b5d6'
down_revision: Union[str, Sequence[str], None] = '745c340b56e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE categories SET bucket = 'needs' WHERE bucket = 'rent'")
    with op.batch_alter_table('budget_settings') as batch:
        batch.drop_column('rent_cents')


def downgrade() -> None:
    with op.batch_alter_table('budget_settings') as batch:
        batch.add_column(sa.Column('rent_cents', sa.Integer(), nullable=True))
    op.execute("UPDATE categories SET bucket = 'rent' WHERE name = 'Rent'")
