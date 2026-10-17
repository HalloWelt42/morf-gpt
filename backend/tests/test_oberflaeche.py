"""Auslieferung der gebauten Oberfläche: Symbole und Manifest per GET und HEAD mit passendem Typ, SPA-Rückfall,
kein Ausbruch aus dist, Startseite ohne Zwischenspeicher und Bau-Dateien mit langer Haltezeit.

Geprüft an einer eigenen kleinen App ohne Lebenszyklus und Datenbank, mit einer nachgebauten dist im Testordner.
"""

from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from app.main import oberflaeche_einbinden


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "index.js").write_text("export {};\n", encoding="utf-8")
    (dist / "index.html").write_text("<!doctype html><title>morf-gpt</title>\n", encoding="utf-8")
    (dist / "site.webmanifest").write_text('{"name": "morf-gpt"}\n', encoding="utf-8")
    (dist / "apple-touch-icon.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    # Liegt neben dist und darf nie ausgeliefert werden
    (tmp_path / "geheim.txt").write_text("geheim\n", encoding="utf-8")
    app = FastAPI()
    oberflaeche_einbinden(app, dist)
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


@pytest.mark.parametrize("pfad", ["/..%2Fgeheim.txt", "/assets/..%2F..%2Fgeheim.txt", "/%2E%2E/geheim.txt"])
def test_kein_ausbruch_aus_dist(client: TestClient, pfad: str) -> None:
    for methode in ("GET", "HEAD"):
        antwort = client.request(methode, pfad)
        assert "geheim" not in antwort.text, (methode, pfad)
        assert antwort.status_code in (200, 404), (methode, pfad)


@pytest.mark.parametrize("pfad", ["/", "/index.html", "/chat/irgendwas"])
def test_startseite_ohne_zwischenspeicher(client: TestClient, pfad: str) -> None:
    for methode in ("GET", "HEAD"):
        antwort = client.request(methode, pfad)
        assert antwort.status_code == 200, (methode, pfad)
        assert antwort.headers["cache-control"] == "no-cache", (methode, pfad)


def test_bau_dateien_bleiben_lange(client: TestClient) -> None:
    for methode in ("GET", "HEAD"):
        antwort = client.request(methode, "/assets/index.js")
        assert antwort.status_code == 200, methode
        assert "immutable" in antwort.headers["cache-control"], methode


def test_ohne_gebaute_oberflaeche_keine_routen(tmp_path: Path) -> None:
    app = FastAPI()
    oberflaeche_einbinden(app, tmp_path)
    assert TestClient(app).get("/site.webmanifest").status_code == 404
