"""morf-Transkription: eigener Transkriptionsdienst der Bibliothek (Whisper hinter HTTP).

Schnittstelle:
  GET  /health                 Zustand kurz (status ok, sobald ein Arbeiter bereit ist)
  GET  /stand                  Engine, Modell, Arbeiter, Wartende, Speicher
  POST /arbeiter {anzahl}      Zahl der Arbeiter anpassen (mit Speicherprüfung)
  POST /transkription          multipart: datei, sprache (Name oder Code, "auto"), wortzeiten (true/false)
                               Antwort: text, segmente (Speicherform), sprache, modell, engine, dauer_s
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import shutil
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from . import nachbearbeitung, sprachen
from .arbeiter import ArbeiterFehler, Arbeiterpool
from .engines import wahl
from .engines.basis import EngineBeschreibung
from .konfiguration import Einstellungen, einstellungen
from .version import VERSION

log = logging.getLogger("transkription")
UPLOAD_BLOCK = 1024 * 1024
# So oft wird während einer laufenden Transkription geprüft, ob der Aufrufer noch da ist
AUFLEGEN_TAKT_S = 2.0


class ArbeiterWunsch(BaseModel):
    anzahl: int = Field(ge=1, le=16)


def _ffmpeg_sicherstellen() -> None:
    """Homebrew-Pfad ergänzen, wenn ffmpeg sonst nicht gefunden wird (die Engine mlx entpackt Audio damit)."""
    if shutil.which("ffmpeg"):
        return
    for kandidat in ("/opt/homebrew/bin", "/usr/local/bin"):
        if Path(kandidat, "ffmpeg").exists():
            os.environ["PATH"] = kandidat + os.pathsep + os.environ.get("PATH", "")
            return
    log.warning("ffmpeg wurde nicht gefunden; die Engine mlx braucht es zum Lesen der Audiodateien")


def erstelle_app(beschreibung: EngineBeschreibung | None = None, werte: Einstellungen | None = None) -> FastAPI:
    e = werte or einstellungen

    @asynccontextmanager
    async def lebenszyklus(app: FastAPI) -> AsyncIterator[None]:
        logging.basicConfig(level=e.log_stufe.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        _ffmpeg_sicherstellen()
        e.tmp_verzeichnis.mkdir(parents=True, exist_ok=True)
        b = beschreibung or wahl.beschreibung_fuer(e)
        pool = Arbeiterpool(b, maximum=e.arbeiter_maximum, reserve_gb=e.speicher_reserve_gb, ladefrist_s=e.ladefrist_s)
        app.state.pool = pool
        log.info("Engine %s, Modell %s, Modellablage %s", b.kennung, b.argumente.get("modell"), e.modelle_verzeichnis)
        # Das Modell lädt im Hintergrund: /health antwortet sofort ("laedt"), Aufträge warten auf den ersten Arbeiter.
        app.state.ladevorgang = asyncio.create_task(pool.anpassen(e.arbeiter))
        yield
        if not app.state.ladevorgang.done():
            app.state.ladevorgang.cancel()
        await pool.beenden_alle()

    app = FastAPI(title="morf-Transkription", version=VERSION, lifespan=lebenszyklus)
    regeln = nachbearbeitung.Blockregeln(min_s=e.segment_min_s, max_s=e.segment_max_s, pause_s=e.pause_s)

    def pool() -> Arbeiterpool:
        return app.state.pool

    @app.get("/health")
    async def health() -> dict[str, Any]:
        p = pool()
        return {
            "status": "ok" if p.bereite() else "laedt",
            "version": VERSION,
            "engine": p.engine_kennung,
            "modell": p.modell,
            "arbeiter": p.bereite(),
        }

    gestartet = datetime.now(UTC).isoformat(timespec="seconds")

    def _stand(p: Arbeiterpool) -> dict[str, Any]:
        return {**p.stand(), "dienst": {"pid": os.getpid(), "gestartet": gestartet}, "version": VERSION}

    @app.get("/stand")
    async def stand() -> dict[str, Any]:
        return _stand(pool())

    @app.post("/arbeiter")
    async def arbeiter(wunsch: ArbeiterWunsch) -> dict[str, Any]:
        p = pool()
        if wunsch.anzahl > e.arbeiter_maximum:
            raise HTTPException(422, f"Höchstens {e.arbeiter_maximum} Arbeiter (MORF_TRANSKRIPTION_ARBEITER_MAXIMUM)")
        hinweise = await p.anpassen(wunsch.anzahl)
        return {**_stand(p), "hinweise": hinweise}

    async def _ablegen(datei: UploadFile) -> Path:
        """Legt den Upload blockweise in der Zwischenablage ab; der Name bleibt lesbar, eine Kennung davor macht ihn eindeutig."""
        name = "".join(z if z.isalnum() or z in "._-" else "_" for z in Path(datei.filename or "audio.bin").name)
        pfad = e.tmp_verzeichnis / f"{uuid.uuid4().hex[:8]}-{name}"
        groesse = 0
        with pfad.open("wb") as ziel:
            while block := await datei.read(UPLOAD_BLOCK):
                ziel.write(block)
                groesse += len(block)
        if groesse == 0:
            pfad.unlink(missing_ok=True)
            raise HTTPException(422, "Die Audiodatei ist leer")
        return pfad

    async def _bis_fertig_oder_aufgelegt(request: Request, aufgabe: asyncio.Task[Any]) -> Any:
        """Wartet auf die Aufgabe; legt der Aufrufer vorher auf, wird die Aufgabe abgebrochen (Arbeiter wird ersetzt)."""  # noqa: E501
        while not aufgabe.done():
            if await request.is_disconnected():
                aufgabe.cancel()
                with contextlib.suppress(asyncio.CancelledError, ArbeiterFehler):
                    await aufgabe
                raise HTTPException(499, "Der Aufrufer hat die Verbindung beendet; die Transkription wurde abgebrochen")
            await asyncio.wait({aufgabe}, timeout=AUFLEGEN_TAKT_S)
        return aufgabe.result()

    @app.post("/transkription")
    async def transkription(
        request: Request,
        datei: UploadFile = File(...),
        sprache: str = Form("german"),
        wortzeiten: bool = Form(True),
    ) -> dict[str, Any]:
        try:
            code = sprachen.code_fuer(sprache)
        except ValueError as fehler:
            raise HTTPException(422, str(fehler)) from fehler
        pfad = await _ablegen(datei)
        start = time.monotonic()
        try:
            aufgabe = asyncio.create_task(pool().transkribiere(pfad, code, wortzeiten, anzeige=datei.filename))
            roh, arbeiter = await _bis_fertig_oder_aufgelegt(request, aufgabe)
        except ArbeiterFehler as fehler:
            log.error("Transkription fehlgeschlagen: %s", fehler)
            raise HTTPException(500, str(fehler)) from fehler
        finally:
            pfad.unlink(missing_ok=True)
        dauer = time.monotonic() - start
        segmente = nachbearbeitung.nachbearbeiten(roh.segmente, regeln)
        log.info(
            "%s: %d Segmente, %.1f s Audio in %.1f s (Arbeiter %d, PID %s)",
            datei.filename,
            len(segmente),
            segmente[-1].end if segmente else 0.0,
            dauer,
            arbeiter.nummer,
            arbeiter.prozess.pid,
        )
        return {
            "arbeiter": {"nummer": arbeiter.nummer, "pid": arbeiter.prozess.pid},
            "text": nachbearbeitung.volltext(segmente) or roh.text.strip(),
            "segmente": [s.als_speicherform() for s in segmente],
            "sprache": roh.sprache,
            "modell": roh.modell,
            "engine": pool().engine_kennung,
            "dauer_s": round(dauer, 1),
        }

    return app


app = erstelle_app()
