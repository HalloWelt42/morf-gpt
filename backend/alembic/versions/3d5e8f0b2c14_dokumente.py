"""Dokumente als zweite Werkart

Revision ID: 3d5e8f0b2c14
Revises: 2c4d7e9a1b03
Create Date: 2026-09-11 16:30:00

"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "3d5e8f0b2c14"
down_revision = "2c4d7e9a1b03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dokumente",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("titel", sa.Text(), nullable=False, server_default=""),
        sa.Column("autor", sa.String(300), nullable=False, server_default=""),
        sa.Column("art", sa.String(16), nullable=False),
        sa.Column("sprache", sa.String(16), nullable=False, server_default="de"),
        sa.Column("beschreibung", sa.Text(), nullable=False, server_default=""),
        sa.Column("veroeffentlicht", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dateiname", sa.String(300), nullable=False, server_default=""),
        sa.Column("datei_pfad", sa.String(500), nullable=False, server_default=""),
        sa.Column("groesse_bytes", sa.Integer(), nullable=True),
        sa.Column("zeichen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadaten_original", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("felder_manuell", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("notizen", sa.Text(), nullable=False, server_default=""),
        sa.Column("stufe", sa.String(16), nullable=False, server_default="importiert"),
        sa.Column("fehler", sa.Text(), nullable=False, server_default=""),
        sa.Column("prioritaet", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("erstellt", sa.DateTime(timezone=True), nullable=False),
        sa.Column("aktualisiert", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "dokument_abschnitte",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("dokument_id", sa.String(32), sa.ForeignKey("dokumente.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reihenfolge", sa.Integer(), nullable=False),
        sa.Column("ebene", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("titel", sa.Text(), nullable=False, server_default=""),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("zeichen", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("anker", sa.String(500), nullable=False, server_default=""),
        sa.Column("seite_von", sa.Integer(), nullable=True),
        sa.Column("seite_bis", sa.Integer(), nullable=True),
        sa.Column("position_von", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("erstellt", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("dokument_id", "reihenfolge", name="uq_abschnitt_dokument_reihenfolge"),
    )
    op.create_index("ix_abschnitte_dokument", "dokument_abschnitte", ["dokument_id"])

    op.alter_column("chunks", "video_id", existing_type=sa.String(32), nullable=True)
    op.add_column("chunks", sa.Column("dokument_id", sa.String(32), nullable=True))
    op.add_column("chunks", sa.Column("abschnitt_id", sa.String(32), nullable=True))
    op.add_column("chunks", sa.Column("position_von", sa.Integer(), nullable=True))
    op.add_column("chunks", sa.Column("position_bis", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_chunks_dokument_id_dokumente", "chunks", "dokumente", ["dokument_id"], ["id"], ondelete="CASCADE")
    op.create_foreign_key(
        "fk_chunks_abschnitt_id_dokument_abschnitte", "chunks", "dokument_abschnitte", ["abschnitt_id"], ["id"], ondelete="SET NULL"
    )
    op.create_unique_constraint("uq_chunk_dokument_reihenfolge", "chunks", ["dokument_id", "reihenfolge"])
    op.create_index("ix_chunks_dokument", "chunks", ["dokument_id"])

    op.add_column("auftraege", sa.Column("dokument_id", sa.String(32), nullable=True))
    op.create_foreign_key("fk_auftraege_dokument_id_dokumente", "auftraege", "dokumente", ["dokument_id"], ["id"], ondelete="CASCADE")


def downgrade() -> None:
    op.drop_constraint("fk_auftraege_dokument_id_dokumente", "auftraege", type_="foreignkey")
    op.drop_column("auftraege", "dokument_id")
    op.drop_index("ix_chunks_dokument", table_name="chunks")
    op.drop_constraint("uq_chunk_dokument_reihenfolge", "chunks", type_="unique")
    op.drop_constraint("fk_chunks_abschnitt_id_dokument_abschnitte", "chunks", type_="foreignkey")
    op.drop_constraint("fk_chunks_dokument_id_dokumente", "chunks", type_="foreignkey")
    op.drop_column("chunks", "position_bis")
    op.drop_column("chunks", "position_von")
    op.drop_column("chunks", "abschnitt_id")
    op.drop_column("chunks", "dokument_id")
    op.alter_column("chunks", "video_id", existing_type=sa.String(32), nullable=False)
    op.drop_index("ix_abschnitte_dokument", table_name="dokument_abschnitte")
    op.drop_table("dokument_abschnitte")
    op.drop_table("dokumente")
