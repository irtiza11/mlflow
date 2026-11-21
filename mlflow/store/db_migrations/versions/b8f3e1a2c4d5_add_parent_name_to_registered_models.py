"""add parent_name to registered models (sub-model hierarchy)

Revision ID: b8f3e1a2c4d5
Revises: f5a4f2784254
Create Date: 2026-11-21 00:00:00.000000

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "b8f3e1a2c4d5"
down_revision = "f5a4f2784254"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("registered_models", schema=None) as batch_op:
        batch_op.add_column(sa.Column("parent_name", sa.String(256), nullable=True, default=None))
        batch_op.create_index("index_registered_models_parent_name", ["parent_name"], unique=False)


def downgrade():
    with op.batch_alter_table("registered_models", schema=None) as batch_op:
        batch_op.drop_index("index_registered_models_parent_name")
        batch_op.drop_column("parent_name")
