from pathlib import Path

import httpx

from app.engines.basis import EngineBeschreibung
from app.konfiguration import Einstellungen
from app.main import erstelle_app

ATTRAPPE = EngineBeschreibung(kennung="attrappe", modul="tests.attrappe", klasse="AttrappenEngine", argumente={"dauer_s": 0.05})
ABLAGE = Path(__file__).resolve().parent.parent / ".test-tmp"


async def test_http_schnittstelle():
    werte = Einstellungen(arbeiter=1, arbeiter_maximum=2, speicher_reserve_gb=0, tmp_verzeichnis=ABLAGE / "uploads")
    app = erstelle_app(ATTRAPPE, werte)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
            assert (await c.get("/health")).json()["status"] in ("laedt", "ok"), "der Dienst antwortet, während das Modell lädt"
            await app.state.ladevorgang
            h = (await c.get("/health")).json()
            assert h["status"] == "ok" and h["engine"] == "attrappe" and h["arbeiter"] == 1

            unbekannt = (await c.get("/auftraege/gibt-es-nicht")).json()
            assert unbekannt["zustand"] == "unbekannt"
            r = await c.post(
                "/transkription", files={"datei": ("guten_tag.wav", b"RIFF...", "audio/wav")}, data={"sprache": "german", "kennung": "k-1"}
            )
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["text"] == "guten tag" and d["segmente"][0]["words"][0]["word"] == "guten" and d["sprache"] == "de"
            assert d["engine"] == "attrappe" and d["dauer_s"] >= 0 and d["arbeiter"]["nummer"] == 1 and d["arbeiter"]["pid"] > 0

            r = await c.post("/transkription", files={"datei": ("leer.wav", b"", "audio/wav")})
            assert r.status_code == 422
            r = await c.post("/transkription", files={"datei": ("x.wav", b"1", "audio/wav")}, data={"sprache": "klingonisch"})
            assert r.status_code == 422

            r = await c.post("/arbeiter", json={"anzahl": 2})
            assert r.status_code == 200 and len(r.json()["arbeiter"]) == 2
            r = await c.post("/arbeiter", json={"anzahl": 3})
            assert r.status_code == 422
            s = (await c.get("/stand")).json()
            assert s["gewuenscht"] == 2 and s["speicher"]["gesamt_gb"] >= 0 and s["dienst"]["pid"] > 0
            assert s["arbeiter"][0]["zuletzt"]["datei"] == "guten_tag.wav" and s["arbeiter"][0]["aktuell"] is None
    assert not list((ABLAGE / "uploads").glob("*")), "hochgeladene Dateien werden nach der Arbeit gelöscht"
