"""add forward tracking to inbound_emails

Revision ID: xxxx
Revises: <prev_revision_id>
Create Date: 2025-08-29
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'xxxx'
down_revision = '<prev_revision_id>'
branch_labels = None
depends_on = None

def upgrade() -> None:
    op.add_column('inbound_emails', sa.Column('forwarded_to', sa.String(), nullable=True))
    op.add_column('inbound_emails', sa.Column('forward_sg_message_id', sa.String(), nullable=True))
    op.add_column('inbound_emails', sa.Column('forward_status', sa.String(), nullable=True))
    op.add_column('inbound_emails', sa.Column('forwarded_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column('inbound_emails', 'forwarded_to')
    op.drop_column('inbound_emails', 'forward_sg_message_id')
    op.drop_column('inbound_emails', 'forward_status')
    op.drop_column('inbound_emails', 'forwarded_at')