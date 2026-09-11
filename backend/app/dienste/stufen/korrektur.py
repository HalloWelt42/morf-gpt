"""Stufe Korrigieren: aktuelles Transkript laden, Engine ausführen, Korrektur speichern."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from ...db.engine import sitzung
from ...db.modelle import Korrektur, Transkript, Video
from ...domaene.fliessband import Auftragsart
from ..anbieter import dienst as anbieter_dienst
from ..auftraege import stufen
from ..ereignisse import bus
from ..korrektur import engine

if TYPE_CHECKING:
    from ..auftraege.laeufer import AuftragKontext


async def aktuelles_transkript(video_id: str) -> Transkript:
    async with sitzung() as s:
        t = (
            await s.execute(
                select(Transkript)
                .where(Transkript.video_id == video_id, Transkript.aktuell.is_(True))
                .order_by(Transkript.erstellt.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if t is None:
            raise RuntimeError("Kein aktuelles Transkript vorhanden - erst transkribieren")
        return t


@stufen.registriere(Auftragsart.KORREKTUR)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis: korrektur_id, bloecke, verworfen, aehnlichkeit, themen, dauer_verarbeitung_s."""
    if not k.video_id:
        raise RuntimeError("Die Stufe Korrektur braucht ein Video")
    transkript = await aktuelles_transkript(k.video_id)
    async with sitzung() as s:
        video = await s.get(Video, k.video_id)
        titel = video.titel if video else ""
        anbieter_zeile = await anbieter_dienst.anbieter_fuer_rolle(s, "korrektur")
        anbieter = anbieter_dienst.baue_sprachmodell(anbieter_zeile)
        anbieter_name = anbieter_zeile.name

    p = engine.Korrekturparameter.aus_werten(k.werte)
    await k.fortschritt(0.02, f"Korrektur mit {anbieter_name} ({anbieter.info.modell})")
    start = time.monotonic()
    ergebnis = await engine.korrigiere(
        anbieter,
        transkript.segmente,
        p,
        video_titel=titel,
        fortschritt=k.fortschritt,
        protokoll=k.protokoll,
        abbruch=k.abbruch,
    )
    dauer = time.monotonic() - start

    async with sitzung() as s:
        await s.execute(update(Korrektur).where(Korrektur.video_id == k.video_id).values(aktuell=False))
        zeile = Korrektur(
            video_id=k.video_id,
            transkript_id=transkript.id,
            engine="sprachmodell",
            anbieter=anbieter_name,
            modell=anbieter.info.modell,
            absaetze=[a.als_dict() for a in ergebnis.absaetze],
            themen=[t.als_dict() for t in ergebnis.themen],
            zusammenfassung=ergebnis.zusammenfassung,
            aehnlichkeit=ergebnis.aehnlichkeit,
            bloecke_gesamt=len(ergebnis.bloecke),
            bloecke_verworfen=ergebnis.verworfen,
            dauer_verarbeitung_s=round(dauer, 1),
            aktuell=True,
        )
        # Blockergebnisse (Roh je Block, Vorschlag bei Verwerfen) wandern in die Absätze
        # des Blocks: erster Absatz eines Blocks trägt Ähnlichkeit, Grund und Vorschlag.
        je_block = {b.index: b for b in ergebnis.bloecke}
        gesehen: set[int] = set()
        for a in zeile.absaetze:
            b = je_block.get(int(a["block"]))
            if b is None or b.index in gesehen:
                continue
            gesehen.add(b.index)
            a["aehnlichkeit"] = round(b.aehnlichkeit, 4)
            if b.verworfen:
                a["grund"] = b.grund
                a["vorschlag"] = b.vorschlag
        s.add(zeile)
        await s.commit()
        korrektur_id = zeile.id

    await k.protokoll(
        f"Korrektur gespeichert: {len(ergebnis.absaetze)} Absätze aus {len(ergebnis.bloecke)} Blöcken, "
        f"{ergebnis.verworfen} verworfen, Ähnlichkeit {ergebnis.aehnlichkeit or 0:.2f}, {len(ergebnis.themen)} Themen"
    )
    bus.veroeffentliche("korrektur", aktion="angelegt", video_id=k.video_id, korrektur_id=korrektur_id)
    return {
        "korrektur_id": korrektur_id,
        "bloecke": len(ergebnis.bloecke),
        "verworfen": ergebnis.verworfen,
        "aehnlichkeit": round(ergebnis.aehnlichkeit or 0.0, 4),
        "themen": len(ergebnis.themen),
        "themen_fehler": ergebnis.themen_fehler,
        "dauer_verarbeitung_s": round(dauer, 1),
    }
