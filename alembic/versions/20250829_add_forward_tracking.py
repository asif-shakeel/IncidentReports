"""add forward tracking columns to inbound_emails

Revision ID: 20250829_add_forward_tracking
Revises: 2e35ba2f77b5
Create Date: 2025-08-29
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = '20250829_add_forward_tracking'
down_revision = ' 2e35ba2f77b5'
branch_labels = None
depends_on = None

def upgrade():
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = [c['name'] for c in inspector.get_columns('inbound_emails')]

    if 'forwarded_to' not in cols:
        op.add_column("inbound_emails", sa.Column("forwarded_to", sa.String(), nullable=True))
    if 'forward_status' not in cols:
        op.add_column("inbound_emails", sa.Column("forward_status", sa.String(), nullable=True))
    if 'forwarded_at' not in cols:
        op.add_column("inbound_emails", sa.Column("forwarded_at", sa.DateTime(timezone=True), nullable=True))
    if 'forward_sg_message_id' not in cols:
        op.add_column("inbound_emails", sa.Column("forward_sg_message_id", sa.String(), nullable=True))

def downgrade():
    # Only drop if exists, safe rollback
    conn = op.get_bind()
    inspector = inspect(conn)
    cols = [c['name'] for c in inspector.get_columns('inbound_emails')]

    if 'forwarded_to' in cols:
        op.drop_column("inbound_emails", "forwarded_to")
    if 'forward_status' in cols:
        op.drop_column("inbound_emails", "forward_status")
    if 'forwarded_at' in cols:
        op.drop_column("inbound_emails", "forwarded_at")
    if 'forward_sg_message_id' in cols:
        op.drop_column("inbound_emails", "forward_sg_message_id")