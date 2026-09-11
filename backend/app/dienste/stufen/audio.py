"""Stufe "Audio beschaffen" (Auftragsart AUDIO).

Ablauf: Video und Quelle laden, Zielpfad `data/audio/<video_id>.m4a` bestimmen. Liegt dort
schon eine gültige Datei (ffprobe liest eine Dauer), wird sie wiederverwendet, sonst holt
der gewählte Bezugsweg (Einstellung `audio.bezugsweg`) die Datei. Danach wird die Zeile
in `audios` angelegt oder aktualisiert (genau eine je Video). Die Stufe des Videos setzt
allein der Auftragsläufer nach Erfolg.

Auftragsparameter: `erneut` (Schalter) erzwingt einen frischen Bezug trotz vorhandener Datei.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.engine import sitzung
from ...db.modelle import Audio, Quelle, Video
from ...domaene.fliessband import Auftragsart
from ..audio import bezug
from ..auftraege import stufen
from ..ereignisse import bus
from ..quellen import abgleich, lokal
from ..quellen.basis import QuellenFehler

if TYPE_CHECKING:
    from ..auftraege.laeufer import AuftragKontext


@dataclass(slots=True)
class VideoAngaben:
    """Das Nötigste über ein Video für den Bezug."""

    video_id: str
    extern_id: str
    titel: str
    quelle_typ: str
    basis_url: str
    dauer_s: float | None


@stufen.registriere(Auftragsart.AUDIO)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Beschafft die Audiodatei eines Videos. Ergebnis: pfad, dauer_s, groesse_bytes, bezugsweg."""
    if k.video_id is None:
        raise RuntimeError("Der Audio-Auftrag braucht ein Video")
    _abbruch_pruefen(k)
    angaben = await _video_angaben(k.video_id, k.werte)
    ziel = bezug.ziel_pfad(angaben.video_id)
    erneut = bool(parameter.get("erneut", False))

    eigenschaften = None if erneut else await _vorhandene_datei(ziel, k)
    bezugsweg: str | None = None
    if eigenschaften is None:
        ergebnis = await _beschaffen(k, angaben, ziel)
        eigenschaften = ergebnis.eigenschaften
        bezugsweg = ergebnis.bezugsweg
        await k.protokoll(
            f"Audio bereit: {bezug.megabyte_text(eigenschaften.groesse_bytes)} Megabyte, "
            f"Dauer {bezug.zeit_text(eigenschaften.dauer_s or 0.0)}"
        )

    zeile = await _audio_zeile_schreiben(angaben.video_id, ziel, eigenschaften, bezugsweg)
    await k.fortschritt(1.0, "Audio bereit")
    bus.veroeffentliche("audio", aktion="bereit", video_id=angaben.video_id, audio_id=zeile.id)
    return {
        "pfad": zeile.pfad,
        "dauer_s": zeile.dauer_s,
        "groesse_bytes": zeile.groesse_bytes,
        "bezugsweg": zeile.bezugsweg,
        "wiederverwendet": bezugsweg is None,
    }


def _abbruch_pruefen(k: AuftragKontext) -> None:
    if k.abbruch.is_set():
        raise asyncio.CancelledError()


async def _video_angaben(video_id: str, werte: dict[str, Any]) -> VideoAngaben:
    """TubeVault-Videos holen ihre Adresse zentral aus den Einstellungen, lokale aus dem Verzeichnis der Quelle."""
    async with sitzung() as s:
        video = await s.get(Video, video_id)
        if video is None:
            raise RuntimeError("Das Video existiert nicht mehr")
        if not video.extern_id:
            raise RuntimeError(f"Das Video '{video.titel}' hat keine externe Kennung")
        quelle = await s.get(Quelle, video.quelle_id) if video.quelle_id else None
        if quelle is None:
            raise RuntimeError(f"Das Video '{video.titel}' hat keine Quelle mehr")
        if quelle.typ == lokal.TYP_KENNUNG:
            basis_url = quelle.basis_url
            if not basis_url:
                raise RuntimeError(f"Die Quelle '{quelle.name}' hat kein Verzeichnis")
        else:
            try:
                basis_url = abgleich.tubevault_adresse(werte)
            except QuellenFehler as e:
                raise RuntimeError(str(e)) from e
        return VideoAngaben(
            video_id=video.id,
            extern_id=video.extern_id,
            titel=video.titel,
            quelle_typ=quelle.typ,
            basis_url=basis_url,
            dauer_s=float(video.dauer_s) if video.dauer_s else None,
        )


async def _vorhandene_datei(ziel: Path, k: AuftragKontext) -> bezug.AudioEigenschaften | None:
    """Gültige vorhandene Datei: liefert ihre Eigenschaften. Unbrauchbare Reste werden entfernt."""
    if not ziel.is_file() or ziel.stat().st_size == 0:
        return None
    try:
        eigenschaften = await bezug.ffprobe_eigenschaften(ziel)
    except bezug.AudioBezugFehler as e:
        await k.protokoll(f"Vorhandene Datei unbrauchbar, wird neu beschafft: {e}", "warn")
        bezug.loesche_leise(ziel)
        return None
    if not eigenschaften.dauer_s or eigenschaften.dauer_s <= 0:
        await k.protokoll("Vorhandene Datei ohne Dauer, wird neu beschafft", "warn")
        bezug.loesche_leise(ziel)
        return None
    dauer = bezug.zeit_text(eigenschaften.dauer_s)
    await k.protokoll(f"Vorhandene Audiodatei wird wiederverwendet (Dauer {dauer})")
    return eigenschaften


def _bezugsweg(k: AuftragKontext, angaben: VideoAngaben) -> bezug.AudioBezug:
    """Lokale Quellen wandeln ihre Datei direkt; alle anderen folgen der Einstellung audio.bezugsweg."""
    wandlung = bezug.Wandlung(abtastrate=int(k.wert("audio.abtastrate")), bitrate_kbit=int(k.wert("audio.bitrate_kbit")))
    ffmpeg = _wert_oder_vorgabe(k, "audio.ffmpeg_pfad", None) or None
    if angaben.quelle_typ == lokal.TYP_KENNUNG:
        endungen = abgleich.dateiendungen_aus(k.werte)
        return bezug.LokaleDatei(wandlung, lambda wurzel, kennung: lokal.datei_finden(wurzel, kennung, endungen), ffmpeg=ffmpeg)
    return bezug.waehle_bezug(
        str(k.wert("audio.bezugsweg")),
        wandlung,
        zeitgrenze_s=float(_wert_oder_vorgabe(k, "audio.zeitgrenze_s", bezug.ZEITGRENZE_S_VORGABE)),
        ffmpeg=ffmpeg,
    )


async def _beschaffen(k: AuftragKontext, angaben: VideoAngaben, ziel: Path) -> bezug.AudioErgebnis:
    weg = _bezugsweg(k, angaben)
    await k.protokoll(f"Bezug über '{weg.kennung}' von {angaben.basis_url} ({angaben.extern_id})")
    _abbruch_pruefen(k)
    return await weg.beschaffe(angaben.basis_url, angaben.extern_id, ziel, k.fortschritt, k.abbruch, angaben.dauer_s)


def _wert_oder_vorgabe(k: AuftragKontext, schluessel: str, vorgabe: Any) -> Any:
    """Einstellungen, die das Register noch nicht kennt (siehe Bericht), mit Modul-Vorgabe."""
    return k.werte.get(schluessel, vorgabe)


async def _audio_zeile_schreiben(video_id: str, ziel: Path, eigenschaften: bezug.AudioEigenschaften, bezugsweg: str | None) -> Audio:
    """Legt die Zeile in `audios` an oder aktualisiert sie. `bezugsweg=None` lässt den alten Wert stehen."""
    async with sitzung() as s:
        zeile = await _audio_zeile(s, video_id)
        if zeile is None:
            zeile = Audio(video_id=video_id, pfad=bezug.pfad_speicherform(ziel))
            s.add(zeile)
        zeile.pfad = bezug.pfad_speicherform(ziel)
        zeile.format = bezug.AUDIO_FORMAT
        zeile.dauer_s = eigenschaften.dauer_s
        zeile.groesse_bytes = eigenschaften.groesse_bytes
        zeile.abtastrate = eigenschaften.abtastrate
        zeile.kanaele = eigenschaften.kanaele
        if bezugsweg is not None:
            zeile.bezugsweg = bezugsweg
        await s.commit()
        return zeile


async def _audio_zeile(s: AsyncSession, video_id: str) -> Audio | None:
    return (await s.execute(select(Audio).where(Audio.video_id == video_id))).scalar_one_or_none()
