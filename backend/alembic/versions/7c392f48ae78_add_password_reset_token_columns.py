"""add password reset token columns

Revision ID: 7c392f48ae78
Revises: ff52363fd06d
Create Date: 2026-08-28 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7c392f48ae78'
down_revision: Union[str, Sequence[str], None] = 'ff52363fd06d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Both columns are nullable with no default -- existing rows (every
    # account that already signed up) simply get NULL, meaning "no reset in
    # progress." No backfill needed, no risk to existing accounts/data.
    op.add_column('users', sa.Column('reset_token_hash', sa.String(), nullable=True))
    op.add_column('users', sa.Column('reset_token_expires_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('users', 'reset_token_expires_at')
    op.drop_column('users', 'reset_token_hash')
