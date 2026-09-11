"""morf-gpt Backend - FastAPI-Anwendung.

Beim Start: Verzeichnisse, Datenbankprüfung, Standard-Anbieter, Auftragsläufer.
Die gebaute Oberfläche (frontend/dist) wird ausgeliefert, wenn sie existiert.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from .config import einstellungen
from .db import migration
from .db.engine import engine, engine_schliessen, sitzung
from .dienste.anbieter import dienst as anbieter_dienst
from .dienste.auftraege import stufen
from .dienste.auftraege.laeufer import laeufer
from .routers import (
    anbieter,
    audio,
    auftraege,
    chat,
    chunks,
    dokumente,
    einbettung,
    ereignisse,
    export,
    korrekturen,
    quellen,
    system,
    transkripte,
    videos,
    werkzeuge,
)
from .routers import (
    einstellungen as einstellungen_router,
)
from .version import version_lesen

logging.basicConfig(level=einstellungen.log_stufe, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
log = logging.getLogger("morf")


@asynccontextmanager
async def lebenszyklus(app: FastAPI) -> AsyncIterator[None]:
    einstellungen.verzeichnisse_anlegen()
    async with engine().connect() as c:
        await c.execute(text("select 1"))
    if einstellungen.migration_beim_start:
        await migration.schema_aktualisieren()
    async with sitzung() as s:
        await anbieter_dienst.anlegen_wenn_leer(s)
        await s.commit()
    stufen.alle_laden()
    await laeufer.start()
    log.info("morf-gpt %s bereit auf %s:%s", version_lesen()["voll"], einstellungen.backend_host, einstellungen.backend_port)
    try:
        yield
    finally:
        await laeufer.stopp()
        await engine_schliessen()


app = FastAPI(
    title="morf-gpt",
    version=version_lesen()["version"],
    description="Wissensbibliothek und Chat über die Erklärvideos von morf.",
    lifespan=lebenszyklus,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"http://127.0.0.1:{einstellungen.frontend_port}", f"http://localhost:{einstellungen.frontend_port}"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (
    system,
    einstellungen_router,
    anbieter,
    quellen,
    videos,
    audio,
    transkripte,
    korrekturen,
    chunks,
    dokumente,
    einbettung,
    auftraege,
    chat,
    export,
    ereignisse,
    werkzeuge,
):
    app.include_router(r.router, prefix="/api")


# Gebaute Oberfläche ausliefern (Betrieb ohne Vite), Fallback auf index.html für die SPA.
_dist: Path = einstellungen.frontend_dist
if _dist.exists() and (_dist / "index.html").exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{pfad:path}", include_in_schema=False)
    async def spa(pfad: str) -> FileResponse:
        ziel = _dist / pfad
        if pfad and ziel.is_file():
            return FileResponse(ziel)
        return FileResponse(_dist / "index.html")
