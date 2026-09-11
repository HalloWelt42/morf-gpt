"""Dokumente importieren: Datei oder eigener Text -> Dokument mit Abschnitten in der Datenbank.

Die Originaldatei wird unter data/dokumente/<kennung>.<endung> abgelegt (Teil des Werks, damit
sie später neu gelesen und beim Umzug mitgenommen werden kann). Bei aktiver Automatik bekommt
das Dokument sofort den Auftrag Stückeln; Einbettung folgt über das Fließband.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import einstellungen
from ...db.modelle import Dokument, DokumentAbschnitt, neue_id
from ...domaene.fliessband import Auftragsart, Dokumentstufe
from ..auftraege.laeufer import auftrag_anlegen
from . import epub, markdown
from .basis import ART_EPUB, ART_MARKDOWN, ART_TEXT, DokumentFehler, Dokumentinhalt, art_aus_dateiname

HOECHSTENS_BYTES = 200 * 1024 * 1024


def lese_inhalt(art: str, roh: bytes, dateiname: str = "") -> Dokumentinhalt:
    """Der Leser zur Art. Unbekannte Arten sind ein sprechender Fehler."""
    vorgabe = Path(dateiname).stem.replace("_", " ").strip() or "Dokument"
    if art == ART_EPUB:
        return epub.lese_epub(roh, vorgabe)
    if art == ART_MARKDOWN:
        return markdown.lese_markdown(roh.decode("utf-8", errors="replace"), vorgabe)
    if art == ART_TEXT:
        return markdown.lese_text(roh.decode("utf-8", errors="replace"), vorgabe)
    raise DokumentFehler(f"Die Art '{art}' kann noch nicht gelesen werden")


def datei_pfad(dokument_id: str, dateiname: str, art: str) -> Path:
    endung = Path(dateiname).suffix.lower() or {ART_EPUB: ".epub", ART_MARKDOWN: ".md", ART_TEXT: ".txt"}.get(art, ".bin")
    return einstellungen.dokumente_verzeichnis / f"{dokument_id}{endung}"


def _abschnitte_anlegen(dokument: Dokument, inhalt: Dokumentinhalt) -> None:
    position = 0
    for nr, a in enumerate(inhalt.abschnitte, start=1):
        dokument.abschnitte.append(
            DokumentAbschnitt(
                id=neue_id(),
                reihenfolge=nr,
                ebene=a.ebene,
                titel=a.titel,
                text=a.text,
                zeichen=a.zeichen,
                anker=a.anker,
                seite_von=a.seite_von,
                seite_bis=a.seite_bis,
                position_von=position,
            )
        )
        position += a.zeichen + 2


async def anlegen(
    s: AsyncSession, *, art: str, roh: bytes, dateiname: str, titel: str = "", autor: str = "", automatik: bool = True
) -> Dokument:
    """Liest die Datei, legt Dokument und Abschnitte an, legt die Datei ab, startet die Stückelung."""
    if not roh:
        raise DokumentFehler("Die Datei ist leer")
    if len(roh) > HOECHSTENS_BYTES:
        raise DokumentFehler(f"Die Datei ist größer als {HOECHSTENS_BYTES // (1024 * 1024)} Megabyte")
    inhalt = lese_inhalt(art, roh, dateiname)
    dokument = Dokument(
        id=neue_id(),
        titel=(titel.strip() or inhalt.titel)[:500],
        autor=(autor.strip() or inhalt.autor)[:300],
        art=art,
        sprache=inhalt.sprache or "de",
        beschreibung=inhalt.beschreibung,
        veroeffentlicht=inhalt.veroeffentlicht,
        dateiname=dateiname[:300],
        groesse_bytes=len(roh),
        zeichen=inhalt.zeichen,
        metadaten_original=inhalt.metadaten,
        felder_manuell=[],
        notizen="",
        stufe=Dokumentstufe.IMPORTIERT,
        fehler="",
        prioritaet=0,
        erstellt=datetime.now(UTC),
        aktualisiert=datetime.now(UTC),
    )
    _abschnitte_anlegen(dokument, inhalt)
    pfad = datei_pfad(dokument.id, dateiname, art)
    pfad.parent.mkdir(parents=True, exist_ok=True)
    pfad.write_bytes(roh)
    dokument.datei_pfad = str(pfad)
    s.add(dokument)
    await s.flush()
    if automatik:
        await auftrag_anlegen(s, Auftragsart.STUECKELUNG, None, dokument_id=dokument.id)
    return dokument


async def anlegen_aus_datei(s: AsyncSession, dateiname: str, roh: bytes, *, titel: str = "", automatik: bool = True) -> Dokument:
    return await anlegen(s, art=art_aus_dateiname(dateiname), roh=roh, dateiname=dateiname, titel=titel, automatik=automatik)


async def anlegen_aus_text(
    s: AsyncSession, titel: str, text: str, *, autor: str = "", art: str = ART_MARKDOWN, automatik: bool = True
) -> Dokument:
    """Eigener Text aus der Oberfläche; als Markdown-Datei abgelegt."""
    if art not in (ART_MARKDOWN, ART_TEXT):
        raise DokumentFehler("Eigene Texte sind Markdown oder reiner Text")
    sicherer_name = "".join(c if c.isalnum() or c in "-_ " else "" for c in titel).strip().replace(" ", "_")[:80] or "eigener_text"
    dateiname = f"{sicherer_name}.md" if art == ART_MARKDOWN else f"{sicherer_name}.txt"
    return await anlegen(s, art=art, roh=text.encode("utf-8"), dateiname=dateiname, titel=titel, autor=autor, automatik=automatik)
