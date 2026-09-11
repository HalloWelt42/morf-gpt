"""Von Hand gepflegte Videofelder

Revision ID: 2c4d7e9a1b03
Revises: 1b8150487827
Create Date: 2026-09-11 15:10:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "2c4d7e9a1b03"
down_revision = "1b8150487827"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "videos",
        sa.Column("felder_manuell", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
    )


def downgrade() -> None:
    op.drop_column("videos", "felder_manuell")
