"""Auslieferung der gebauten Oberfläche: Symbole und Manifest per GET und HEAD mit passendem Typ, SPA-Rückfall.

Geprüft an einer eigenen kleinen App ohne Lebenszyklus und Datenbank, mit einer nachgebauten dist im Testordner.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.main import oberflaeche_einbinden


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index.js").write_text("export {};\n", encoding="utf-8")
    (tmp_path / "index.html").write_text("<!doctype html><title>morf-gpt</title>\n", encoding="utf-8")
    (tmp_path / "site.webmanifest").write_text('{"name": "morf-gpt"}\n', encoding="utf-8")
    (tmp_path / "apple-touch-icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    app = FastAPI()
    oberflaeche_einbinden(app, tmp_path)
    return TestClient(app)


@pytest.mark.parametrize(
    ("pfad", "typ"),
    [
        ("/site.webmanifest", "application/manifest+json"),
        ("/apple-touch-icon.png", "image/png"),
        ("/assets/index.js", "text/javascript"),
    ],
)
def test_dateien_per_get_und_head(client: TestClient, pfad: str, typ: str) -> None:
    for methode in ("GET", "HEAD"):
        antwort = client.request(methode, pfad)
        assert antwort.status_code == 200, (methode, pfad)
        assert antwort.headers["content-type"].startswith(typ), (methode, pfad)


def test_unbekannter_pfad_liefert_die_spa(client: TestClient) -> None:
    for methode in ("GET", "HEAD"):
        antwort = client.request(methode, "/chat/irgendwas")
        assert antwort.status_code == 200
        assert antwort.headers["content-type"].startswith("text/html")


def test_ohne_gebaute_oberflaeche_keine_routen(tmp_path: Path) -> None:
    app = FastAPI()
    oberflaeche_einbinden(app, tmp_path)
    assert TestClient(app).get("/site.webmanifest").status_code == 404
