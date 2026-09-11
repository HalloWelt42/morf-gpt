"""Stufe Quelle abgleichen: Kanalvideos der Quelle in die Bibliothek übernehmen.

Nutzt den Abgleichdienst (dienste/quellen/abgleich.py); danach bekommen neu
ausgewählte Videos bei aktiver Automatik ihren ersten Auftrag.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from ...config import einstellungen
from ...db.engine import sitzung
from ...db.modelle import Quelle, Video
from ...dienste.ereignisse import bus
from ...domaene.fliessband import Auftragsart, Stufe
from ..auftraege import stufen
from ..auftraege.laeufer import auftrag_fuer_naechste_stufe
from ..quellen import abgleich

if TYPE_CHECKING:
    from ..auftraege.laeufer import AuftragKontext


@stufen.registriere(Auftragsart.QUELLE_ABGLEICH)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis: die Zähler des Abgleichs plus die Zahl neu angelegter Aufträge."""
    quelle_id = str(parameter.get("quelle_id") or "")
    if not quelle_id:
        raise RuntimeError("Der Abgleich braucht eine Quelle (parameter.quelle_id)")

    async with sitzung() as s:
        quelle = await s.get(Quelle, quelle_id)
        if quelle is None:
            raise RuntimeError("Die Quelle existiert nicht mehr")
        if not quelle.aktiv:
            raise RuntimeError(f"Die Quelle '{quelle.name}' ist deaktiviert")
        videoquelle = abgleich.baue_quelle(quelle.typ, quelle.basis_url, quelle.kanal_id, k.werte)
        try:
            zaehler = await abgleich.abgleichen(
                quelle,
                videoquelle,
                abgleich.Videobestand(s),
                k.werte,
                einstellungen.miniaturen_verzeichnis,
                fortschritt=k.fortschritt,
                protokoll=k.protokoll,
                abbruch=k.abbruch,
            )
        finally:
            await videoquelle.schliessen()

        angelegt = 0
        if k.werte.get("band.automatik", True):
            videos = (
                (
                    await s.execute(
                        select(Video).where(Video.quelle_id == quelle.id, Video.ausgewaehlt.is_(True), Video.stufe != Stufe.EINGEBETTET)
                    )
                )
                .scalars()
                .all()
            )
            for v in videos:
                if await auftrag_fuer_naechste_stufe(s, v) is not None:
                    angelegt += 1
            await s.commit()
            if angelegt:
                await k.protokoll(f"{angelegt} Folgeaufträge für Videos im Umfang angelegt")

    bus.veroeffentliche("quelle", aktion="abgeglichen", quelle_id=quelle_id, **zaehler.als_dict())
    bus.veroeffentliche("video", aktion="abgleich", quelle_id=quelle_id)
    return {**zaehler.als_dict(), "auftraege_angelegt": angelegt}
