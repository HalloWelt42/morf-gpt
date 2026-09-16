"""Reihenfolge der Routen: feste Pfade müssen vor Pfaden mit Kennung stehen, sonst fängt der
Platzhalter sie ab und verlangt die Felder des anderen Modells ("Field required").

Geprüft ohne Datenbank: die Eingabeprüfung läuft vor dem Handler, ein leerer Körper nennt
genau die Felder des Modells, das die Route erwartet.
"""

from starlette.testclient import TestClient

from app.main import app


def _fehlende_felder(methode: str, pfad: str) -> set[str]:
    client = TestClient(app)  # ohne Kontext: kein Lebenszyklus, keine Datenbank
    antwort = client.request(methode, pfad, json={})
    assert antwort.status_code == 422, antwort.text
    return {fehler["loc"][-1] for fehler in antwort.json()["detail"] if fehler["type"] == "missing"}


def test_rollen_route_vor_anbieterkennung():
    assert _fehlende_felder("PUT", "/api/anbieter/rollen") == {"rolle", "anbieter_id"}
    assert "name" in _fehlende_felder("PUT", "/api/anbieter/irgendeine-kennung")


def test_uebergabe_feste_pfade_vor_kennung():
    assert _fehlende_felder("POST", "/api/uebergabe/holen") == {"adresse"}
    client = TestClient(app)
    assert client.get("/api/uebergabe/holen/status").status_code == 200
    assert client.get("/api/uebergabe/erstellen/status").status_code == 200
    assert client.get("/api/uebergabe/keine-uuid/datei").status_code == 422
