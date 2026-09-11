"""Start: python -m app (liest Host und Port aus der Konfiguration)."""

from __future__ import annotations

import uvicorn

from .konfiguration import einstellungen

uvicorn.run("app.main:app", host=einstellungen.host, port=einstellungen.port, log_level=einstellungen.log_stufe.lower())
