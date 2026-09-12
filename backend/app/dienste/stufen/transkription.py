"""Stufe Transkription: das Audio eines Videos an die gewählte Engine geben, Transkript speichern.

Der Dienst blockiert bis zum Ende (lange Videos: viele Minuten). Darum läuft der Aufruf
als eigene Task; daneben schickt die Stufe im Takt ein Lebenszeichen an den Auftrag, prüft
den Abbruchwunsch und hält die Meldung in der Oberfläche frisch. Beim eigenen Dienst fragt
sie dabei den echten Zwischenstand ab (verarbeitete Sekunden des Audios, Warteposition)
und rechnet ihn in den Fortschrittsanteil um; bei fremden Diensten bleibt der Anteil
ehrlich stehen - geraten wird nicht.

Die Video-Stufe setzt allein der Läufer nach Erfolg.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from ...config import einstellungen
from ...db.engine import sitzung
from ...db.modelle import Audio, Transkript, Video, neue_id
from ...domaene.fliessband import Auftragsart
from ..auftraege import stufen
from ..ereignisse import bus
from ..transkription import register
from ..transkription.basis import TranskriptErgebnis, TranskriptionsFehler
from ..transkription.eigener_dienst import EigenerDienst

if TYPE_CHECKING:
    from ..auftraege.laeufer import AuftragKontext


# Vorgabewert, bis das Einstellungsregister den Schlüssel transkription.herzschlag_takt_s
# kennt (vorgeschlagen: ganzzahl, 30 Sekunden, 5 bis 300). Sobald er existiert, greift er
# über werte.get(...) automatisch. Er muss unter band.herzschlag_frist_s (mindestens 60) liegen.
HERZSCHLAG_TAKT_S_VORGABE: float = 30.0

# Fortschrittsanteile: feste Marken für Start, Warten und Speichern; dazwischen der echte Anteil des Dienstes.
ANTEIL_GESTARTET: float = 0.05
ANTEIL_WARTEND: float = 0.10
ANTEIL_SPEICHERN: float = 0.95
# So oft wird der Zwischenstand beim eigenen Dienst nachgefragt
FORTSCHRITT_TAKT_S: float = 5.0


@stufen.registriere(Auftragsart.TRANSKRIPTION)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis: transkript_id, segmente (Anzahl), zeichen, dauer_verarbeitung_s."""
    if not k.video_id:
        raise RuntimeError("Die Stufe Transkription braucht ein Video")
    audio = await _audio_laden(k.video_id)
    pfad = _audiopfad(audio)
    engine = register.engine_aus_werten(k.werte)
    await _arbeiter_anpassen(k, engine)
    sprache = str(k.wert("transkription.sprache"))
    zeitgrenze_s = float(k.wert("transkription.zeitgrenze_s"))
    takt_s = float(k.werte.get("transkription.herzschlag_takt_s", HERZSCHLAG_TAKT_S_VORGABE))

    await k.fortschritt(
        ANTEIL_GESTARTET,
        f"Audio ({_megabyte(pfad)} Megabyte, {_dauer_text(audio.dauer_s)}) geht an {register.titel_fuer(engine.kennung)}",
    )
    start = time.monotonic()
    if isinstance(engine, EigenerDienst):
        # Der eigene Dienst zeigt den Auftrag unter diesem Namen (Karte, Protokoll), nicht als Dateikennung,
        # und liefert unter der Auftragskennung den echten Zwischenstand
        aufruf = engine.transkribiere(pfad, sprache, zeitgrenze_s, anzeige=await _videotitel(k.video_id), kennung=k.auftrag_id)
        ergebnis = await _mit_lebenszeichen(k, aufruf, takt_s, zwischenstand=_zwischenstand_abfrage(engine, k.auftrag_id))
    else:
        ergebnis = await _mit_lebenszeichen(k, engine.transkribiere(pfad, sprache, zeitgrenze_s), takt_s)
    dauer_s = time.monotonic() - start

    if not ergebnis.text.strip():
        raise RuntimeError(f"{register.titel_fuer(engine.kennung)} lieferte keinen Text für dieses Audio")

    await k.fortschritt(ANTEIL_SPEICHERN, "Transkript wird gespeichert")
    transkript_id = await _transkript_speichern(k.video_id, ergebnis, dauer_s)
    await k.protokoll(
        f"Transkript gespeichert: {len(ergebnis.segmente)} Segmente, {ergebnis.zeichen} Zeichen, "
        f"Modell '{ergebnis.modell or 'unbekannt'}', Dauer {_dauer_text(dauer_s)}"
        + (f", transkribiert von {ergebnis.arbeiter}" if ergebnis.arbeiter else "")
    )
    bus.veroeffentliche("transkript", aktion="angelegt", video_id=k.video_id, transkript_id=transkript_id)
    return {
        "transkript_id": transkript_id,
        "segmente": len(ergebnis.segmente),
        "zeichen": ergebnis.zeichen,
        "dauer_verarbeitung_s": round(dauer_s, 1),
    }


# ---------------------------------------------------------------- Arbeiter des eigenen Dienstes


async def _arbeiter_anpassen(k: AuftragKontext, engine: Any) -> None:
    """Beim eigenen Dienst die Zahl der Arbeiter auf die Einstellung bringen (er prüft den Speicher) und den Stand protokollieren."""
    if not isinstance(engine, EigenerDienst):
        return
    gewuenscht = int(k.werte.get("transkription.arbeiter", 1))
    try:
        stand = await engine.arbeiter_setzen(gewuenscht)
    except TranskriptionsFehler as e:
        await k.protokoll(f"Arbeiter des Transkriptionsdienstes nicht anpassbar: {e}", "warn")
        return
    for hinweis in stand.get("hinweise", []):
        await k.protokoll(str(hinweis), "warn")
    bereit = [a for a in stand.get("arbeiter", []) if a.get("zustand") in ("bereit", "beschaeftigt")]
    if gewuenscht > 1 or len(bereit) != 1:
        speicher = stand.get("speicher", {})
        await k.protokoll(
            f"{len(bereit)} Arbeiter beim Transkriptionsdienst ({stand.get('engine')}, {stand.get('modell')}); "
            f"verfügbarer Speicher {speicher.get('verfuegbar_gb', '?')} GB"
        )


# ---------------------------------------------------------------- Warten mit Lebenszeichen


Zwischenstand = Callable[[], Coroutine[Any, Any, tuple[float, str] | None]]


def _zwischenstand_abfrage(engine: EigenerDienst, kennung: str) -> Zwischenstand:
    """Fragt den eigenen Dienst nach dem Stand des Auftrags und formt Anteil und Meldung daraus."""

    async def abfrage() -> tuple[float, str] | None:
        try:
            stand = await engine.fortschritt(kennung)
        except TranskriptionsFehler:
            return None
        if stand.get("zustand") == "laeuft":
            anteil = float(stand.get("anteil") or 0.0)
            audio_s = float(stand.get("audio_s") or 0.0)
            wo = f"Arbeiter {stand.get('arbeiter')}"
            if audio_s:
                text = f"{_dauer_text(float(stand.get('verarbeitet_s') or 0.0))} von {_dauer_text(audio_s)} transkribiert ({wo})"
            else:
                text = f"Transkription beginnt ({wo})"
            return ANTEIL_WARTEND + (ANTEIL_SPEICHERN - ANTEIL_WARTEND) * anteil, text
        if stand.get("zustand") == "wartet":
            return ANTEIL_WARTEND, f"wartet auf einen freien Arbeiter (Platz {stand.get('position')} von {stand.get('wartend')})"
        return None

    return abfrage


async def _mit_lebenszeichen[T](
    k: AuftragKontext, aufruf: Coroutine[Any, Any, T], takt_s: float, zwischenstand: Zwischenstand | None = None
) -> T:
    """Führt den blockierenden Aufruf als Task aus und meldet sich im Takt beim Auftrag.

    Mit `zwischenstand` wird alle paar Sekunden der echte Stand abgefragt und als Anteil und
    Meldung gemeldet; ohne bleibt der Anteil stehen und nur die Laufzeit wandert. Bei gesetztem
    Abbruchwunsch (oder Abbruch dieser Task von außen) wird der innere Aufruf abgebrochen und
    asyncio.CancelledError weitergegeben.
    """
    task: asyncio.Task[T] = asyncio.ensure_future(aufruf)
    start = time.monotonic()
    letzter_herzschlag = start
    letzte_meldung = ""
    warte_s = min(takt_s, FORTSCHRITT_TAKT_S) if zwischenstand else takt_s
    try:
        while True:
            fertig, _ = await asyncio.wait({task}, timeout=warte_s)
            if fertig:
                return task.result()
            if k.abbruch.is_set():
                raise asyncio.CancelledError()
            if time.monotonic() - letzter_herzschlag >= takt_s:
                await k.herzschlag()
                letzter_herzschlag = time.monotonic()
            anteil, meldung = ANTEIL_WARTEND, f"Transkription läuft seit {_dauer_text(time.monotonic() - start)}"
            if zwischenstand:
                stand = await zwischenstand()
                if stand:
                    anteil, meldung = stand
            if meldung != letzte_meldung:
                await k.fortschritt(anteil, meldung)
                letzte_meldung = meldung
    finally:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task


# ---------------------------------------------------------------- Datenbank


async def _videotitel(video_id: str) -> str:
    async with sitzung() as s:
        return str(await s.scalar(select(Video.titel).where(Video.id == video_id)) or "")


async def _audio_laden(video_id: str) -> Audio:
    async with sitzung() as s:
        audio = await s.scalar(select(Audio).where(Audio.video_id == video_id))
    if audio is None:
        raise RuntimeError("Für dieses Video liegt keine Audiodatei vor - zuerst die Stufe Audio ausführen")
    return audio


async def _transkript_speichern(video_id: str, ergebnis: TranskriptErgebnis, dauer_s: float) -> str:
    """Ältere Transkripte des Videos verlieren `aktuell`; das neue bekommt es. Gibt die neue Kennung zurück."""
    transkript = Transkript(
        id=neue_id(),
        video_id=video_id,
        engine=ergebnis.engine,
        modell=ergebnis.modell,
        sprache=ergebnis.sprache,
        volltext=ergebnis.text,
        segmente=ergebnis.segmente_speicherform(),
        dauer_verarbeitung_s=round(dauer_s, 1),
        aktuell=True,
    )
    async with sitzung() as s:
        await s.execute(update(Transkript).where(Transkript.video_id == video_id, Transkript.aktuell.is_(True)).values(aktuell=False))
        s.add(transkript)
        await s.commit()
    return transkript.id


# ---------------------------------------------------------------- Helfer


def _audiopfad(audio: Audio) -> Path:
    """Absolute Pfade gelten wie gespeichert; relative liegen unter dem Audio- oder Datenverzeichnis."""
    pfad = Path(audio.pfad)
    if pfad.is_absolute():
        return pfad
    unter_audio = einstellungen.audio_verzeichnis / pfad
    if unter_audio.exists():
        return unter_audio
    return einstellungen.daten_verzeichnis / pfad


def _megabyte(pfad: Path) -> str:
    try:
        return f"{pfad.stat().st_size / (1024 * 1024):.1f}"
    except OSError:
        return "?"


def _dauer_text(sekunden: float | None) -> str:
    if sekunden is None:
        return "Dauer unbekannt"
    ganze = int(sekunden)
    if ganze < 60:
        return f"{ganze} Sekunden"
    minuten = ganze // 60
    if minuten == 1:
        return "1 Minute"
    if minuten < 60:
        return f"{minuten} Minuten"
    stunden, rest = divmod(minuten, 60)
    stunden_text = "1 Stunde" if stunden == 1 else f"{stunden} Stunden"
    if rest == 0:
        return stunden_text
    return f"{stunden_text} {rest} Minuten"
