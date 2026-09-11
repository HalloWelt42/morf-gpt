"""TubeVault-Adresse zentral in den Einstellungen

Revision ID: 4e6f9a1c2d35
Revises: 3d5e8f0b2c14
Create Date: 2026-09-11 19:20:00

Übernimmt die Adresse der ersten TubeVault-Quelle in die Einstellung quelle.tubevault_api
(falls dort noch nichts steht) und leert das Feld an den TubeVault-Quellen: die Adresse hat
fortan genau einen Ort.
"""

from alembic import op
import sqlalchemy as sa

revision = "4e6f9a1c2d35"
down_revision = "3d5e8f0b2c14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO einstellungen (schluessel, wert, aktualisiert)
            SELECT 'quelle.tubevault_api', to_jsonb(rtrim(basis_url, '/')), now()
            FROM quellen
            WHERE typ = 'tubevault' AND basis_url <> ''
            ORDER BY erstellt
            LIMIT 1
            ON CONFLICT (schluessel) DO NOTHING
            """
        )
    )
    op.execute(sa.text("UPDATE quellen SET basis_url = '' WHERE typ = 'tubevault'"))


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE quellen SET basis_url = COALESCE((SELECT wert #>> '{}' FROM einstellungen WHERE schluessel = 'quelle.tubevault_api'), '')
            WHERE typ = 'tubevault'
            """
        )
    )
