"""Stufe Stückeln: Absätze der aktuellen Korrektur (sonst Rohsegmente) zu Chunks.

Bei Dokumenten sind die Abschnitte (Kapitel) die Eingabe: gestückelt wird je Kapitel, ein
Stück überschreitet nie eine Kapitelgrenze, der Titel des Abschnitts wird das Thema des
Stücks. Statt Zeitfenstern tragen Dokumentstücke Zeichenpositionen im Dokument.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import delete, select

from ...db.engine import sitzung
from ...db.modelle import Chunk, DokumentAbschnitt, Korrektur, Transkript
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


# ---------------------------------------------------------------- Dokumente
def kapitel_gruppen(abschnitte: list[DokumentAbschnitt]) -> list[list[DokumentAbschnitt]]:
    """Ein Kapitel (Ebene 1) mit seinen Unterabschnitten; Text vor dem ersten Kapitel bildet eine eigene Gruppe."""
    gruppen: list[list[DokumentAbschnitt]] = []
    for a in abschnitte:
        if a.ebene <= 1 or not gruppen:
            gruppen.append([a])
        else:
            gruppen[-1].append(a)
    return gruppen


def absaetze_und_themen(
    gruppe: list[DokumentAbschnitt],
) -> tuple[list[stueckler.Absatz], list[stueckler.Thema], dict[str, tuple[int, int]]]:
    """Absätze mit Zeichenpositionen (statt Zeiten) und je Abschnitt ein Thema über seinen Bereich.

    Der Titel eines Abschnitts steht als erster Absatz im Text, damit jedes Stück seinen Kontext
    trägt. Gibt zusätzlich je Abschnitt (Kennung) den Positionsbereich zurück.
    """
    absaetze: list[stueckler.Absatz] = []
    themen: list[stueckler.Thema] = []
    bereiche: dict[str, tuple[int, int]] = {}
    for a in gruppe:
        start = a.position_von
        pos = start
        teile = ([a.titel] if a.titel else []) + [t for t in a.text.split("\n\n") if t.strip()]
        for t in teile:
            t = t.strip()
            absaetze.append(stueckler.Absatz(text=t, start_s=float(pos), end_s=float(pos + len(t))))
            pos += len(t) + 2
        ende = max(pos, start + 1)
        themen.append(stueckler.Thema(titel=a.titel, start_s=float(start), end_s=float(ende)))
        bereiche[a.id] = (start, ende)
    return absaetze, themen, bereiche


def _abschnitt_fuer(bereiche: dict[str, tuple[int, int]], mitte: float) -> str | None:
    for kennung, (von, bis) in bereiche.items():
        if von <= mitte < bis:
            return kennung
    return next(iter(bereiche), None)


async def stuecke_fuer_dokument(dokument_id: str, ziel_zeichen: int, ueberlappung: int) -> list[tuple[stueckler.Stueck, str | None]]:
    """Stückt jedes Kapitel für sich; die Reihenfolge zählt über das ganze Dokument durch."""
    async with sitzung() as s:
        abschnitte = list(
            (
                await s.execute(
                    select(DokumentAbschnitt).where(DokumentAbschnitt.dokument_id == dokument_id).order_by(DokumentAbschnitt.reihenfolge)
                )
            )
            .scalars()
            .all()
        )
    if not abschnitte:
        raise RuntimeError("Das Dokument hat keine Abschnitte - erst importieren")
    aus: list[tuple[stueckler.Stueck, str | None]] = []
    nr = 0
    for gruppe in kapitel_gruppen(abschnitte):
        absaetze, themen, bereiche = absaetze_und_themen(gruppe)
        if not absaetze:
            continue
        for st in stueckler.stueckeln(absaetze, themen, ziel_zeichen, ueberlappung):
            nr += 1
            st.reihenfolge = nr
            aus.append((st, _abschnitt_fuer(bereiche, (st.start_s + st.end_s) / 2)))
    if not aus:
        raise RuntimeError("Kein Text zum Stückeln vorhanden")
    return aus


async def stuecke_speichern_dokument(dokument_id: str, stuecke: list[tuple[stueckler.Stueck, str | None]]) -> int:
    """Ersetzt alle Chunks des Dokuments (Einbettungen fallen per Kaskade mit)."""
    async with sitzung() as s:
        await s.execute(delete(Chunk).where(Chunk.dokument_id == dokument_id))
        for st, abschnitt_id in stuecke:
            s.add(
                Chunk(
                    video_id=None,
                    dokument_id=dokument_id,
                    abschnitt_id=abschnitt_id,
                    korrektur_id=None,
                    reihenfolge=st.reihenfolge,
                    text=st.text,
                    start_s=0.0,
                    end_s=0.0,
                    position_von=int(st.start_s),
                    position_bis=int(st.end_s),
                    zeichen=st.zeichen,
                    thema=st.thema,
                    ueberlappung_vor=st.ueberlappung_vor,
                    ueberlappung_nach=st.ueberlappung_nach,
                )
            )
        await s.commit()
    return len(stuecke)


async def _dokument_stueckeln(k: AuftragKontext, ziel: int, ueberlappung: int) -> dict[str, Any]:
    assert k.dokument_id is not None
    stuecke = await stuecke_fuer_dokument(k.dokument_id, ziel, ueberlappung)
    await k.fortschritt(0.7, f"{len(stuecke)} Stücke gebildet, werden gespeichert")
    anzahl = await stuecke_speichern_dokument(k.dokument_id, stuecke)
    zeichen = sum(st.zeichen for st, _ in stuecke)
    await k.protokoll(
        f"{anzahl} Stücke aus den Abschnitten des Dokuments, {zeichen} Zeichen, mittlere Größe {zeichen // max(1, anzahl)} Zeichen"
    )
    bus.veroeffentliche("chunks", aktion="neu", dokument_id=k.dokument_id, anzahl=anzahl)
    return {"anzahl": anzahl, "zeichen_gesamt": zeichen, "quelle": "dokument"}


@stufen.registriere(Auftragsart.STUECKELUNG)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis: anzahl, zeichen_gesamt, quelle (korrektur|transkript|dokument)."""
    if k.dokument_id:
        ziel = int(k.wert("stueckelung.ziel_zeichen"))
        ueberlappung = int(k.wert("stueckelung.ueberlappung_zeichen"))
        await k.fortschritt(0.1, f"Stücke zu etwa {ziel} Zeichen mit {ueberlappung} Zeichen Überlappung, je Kapitel")
        return await _dokument_stueckeln(k, ziel, ueberlappung)
    if not k.video_id:
        raise RuntimeError("Die Stufe Stückelung braucht ein Video oder ein Dokument")
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
