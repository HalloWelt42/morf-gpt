"""Stufe Stückeln: Absätze der aktuellen Korrektur (sonst Rohsegmente) zu Chunks."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from ...db.engine import sitzung
from ...db.modelle import Chunk, Korrektur, Transkript
from ...domaene.fliessband import Auftragsart
from ..auftraege import stufen
from ..ereignisse import bus
from ..stueckelung import stueckler

if TYPE_CHECKING:
    from ..auftraege.laeufer import AuftragKontext


async def stuecke_fuer_video(video_id: str, ziel_zeichen: int, ueberlappung: int) -> tuple[list[stueckler.Stueck], str | None, str]:
    """Stückt das Video und gibt (Stücke, Korrektur-Kennung oder None, Quelle) zurück."""
    async with sitzung() as s:
        korrektur = (
            await s.execute(
                select(Korrektur)
                .where(Korrektur.video_id == video_id, Korrektur.aktuell.is_(True))
                .order_by(Korrektur.erstellt.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if korrektur is not None and korrektur.absaetze:
            absaetze = stueckler.absaetze_aus_dicts(korrektur.absaetze)
            themen = stueckler.themen_aus_dicts(korrektur.themen)
            quelle = "korrektur"
            korrektur_id: str | None = korrektur.id
        else:
            transkript = (
                await s.execute(
                    select(Transkript)
                    .where(Transkript.video_id == video_id, Transkript.aktuell.is_(True))
                    .order_by(Transkript.erstellt.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if transkript is None:
                raise RuntimeError("Weder Korrektur noch Transkript vorhanden - erst transkribieren")
            absaetze = stueckler.absaetze_aus_segmenten(transkript.segmente, ziel_zeichen)
            themen = []
            quelle = "transkript"
            korrektur_id = None
    if not absaetze:
        raise RuntimeError("Kein Text zum Stückeln vorhanden")
    return stueckler.stueckeln(absaetze, themen, ziel_zeichen, ueberlappung), korrektur_id, quelle


async def stuecke_speichern(video_id: str, stuecke: list[stueckler.Stueck], korrektur_id: str | None) -> int:
    """Ersetzt alle Chunks des Videos (Einbettungen fallen per Kaskade mit)."""
    async with sitzung() as s:
        await s.execute(delete(Chunk).where(Chunk.video_id == video_id))
        for st in stuecke:
            s.add(
                Chunk(
                    video_id=video_id,
                    korrektur_id=korrektur_id,
                    reihenfolge=st.reihenfolge,
                    text=st.text,
                    start_s=st.start_s,
                    end_s=st.end_s,
                    zeichen=st.zeichen,
                    thema=st.thema,
                    ueberlappung_vor=st.ueberlappung_vor,
                    ueberlappung_nach=st.ueberlappung_nach,
                )
            )
        await s.commit()
    return len(stuecke)


@stufen.registriere(Auftragsart.STUECKELUNG)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis: anzahl, zeichen_gesamt, quelle (korrektur|transkript)."""
    if not k.video_id:
        raise RuntimeError("Die Stufe Stückelung braucht ein Video")
    ziel = int(k.wert("stueckelung.ziel_zeichen"))
    ueberlappung = int(k.wert("stueckelung.ueberlappung_zeichen"))
    await k.fortschritt(0.1, f"Stücke zu etwa {ziel} Zeichen mit {ueberlappung} Zeichen Überlappung")
    stuecke, korrektur_id, quelle = await stuecke_fuer_video(k.video_id, ziel, ueberlappung)
    await k.fortschritt(0.7, f"{len(stuecke)} Stücke gebildet, werden gespeichert")
    anzahl = await stuecke_speichern(k.video_id, stuecke, korrektur_id)
    zeichen = sum(st.zeichen for st in stuecke)
    await k.protokoll(
        f"{anzahl} Stücke aus {'der Korrektur' if quelle == 'korrektur' else 'dem Rohtranskript'}, "
        f"{zeichen} Zeichen, mittlere Größe {zeichen // max(1, anzahl)} Zeichen"
    )
    bus.veroeffentliche("chunks", aktion="neu", video_id=k.video_id, anzahl=anzahl)
    return {"anzahl": anzahl, "zeichen_gesamt": zeichen, "quelle": quelle}
