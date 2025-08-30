"""add forward tracking

Revision ID: 2e35ba2f77b5
Revises: ac7d469eb461
Create Date: 2025-08-29 23:48:38.993658

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e35ba2f77b5'
down_revision: Union[str, Sequence[str], None] = 'ac7d469eb461'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
