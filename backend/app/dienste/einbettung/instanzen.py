"""Mehrere Instanzen des Einbettungsmodells in LM Studio, mit Rücksicht auf den freien Speicher.

Gemessen am 2026-09-11 (bge-m3, 96 Stücke zu 2.658 Zeichen, 80B nebenbei aktiv): eine Instanz
3,9 Texte/s, mit 2 bis 4 gleichzeitigen Anfragen 4,5 bis 4,8; zwei Instanzen mit je 4 Anfragen
6,2 Texte/s. Mehr Instanzen bringen kaum mehr, weil alle dieselbe Grafikeinheit teilen.

Die zusätzlichen Instanzen werden über die Befehlszeile von LM Studio (`lms`) geladen und
tragen die Kennung `<modell>-instanz-<n>`. Vor jedem Laden wird geprüft, ob die Modellgröße
in den freien Speicher passt, abzüglich einer einstellbaren Reserve. Was nicht passt, wird
nicht geladen, sondern als Hinweis gemeldet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger(__name__)

LMS_VORGABE = Path.home() / ".lmstudio" / "bin" / "lms"
LADE_ZEITGRENZE_S = 180.0
GIGABYTE = 1024**3


@dataclass(slots=True)
class Speicherstand:
    gesamt_gb: float
    frei_gb: float
    inaktiv_gb: float

    @property
    def verfuegbar_gb(self) -> float:
        """Frei plus inaktiv: inaktive Seiten gibt macOS bei Bedarf her."""
        return self.frei_gb + self.inaktiv_gb


@dataclass(slots=True)
class Instanz:
    kennung: str
    groesse_gb: float


@dataclass(slots=True)
class Instanzstand:
    modell: str
    gewuenscht: int
    geladen: list[Instanz]
    speicher: Speicherstand
    hinweise: list[str] = field(default_factory=list)
    lms_vorhanden: bool = True

    def als_dict(self) -> dict[str, Any]:
        return {
            "modell": self.modell,
            "gewuenscht": self.gewuenscht,
            "geladen": [{"kennung": i.kennung, "groesse_gb": round(i.groesse_gb, 2)} for i in self.geladen],
            "speicher": {
                "gesamt_gb": round(self.speicher.gesamt_gb, 1),
                "frei_gb": round(self.speicher.frei_gb, 1),
                "inaktiv_gb": round(self.speicher.inaktiv_gb, 1),
                "verfuegbar_gb": round(self.speicher.verfuegbar_gb, 1),
            },
            "hinweise": self.hinweise,
            "lms_vorhanden": self.lms_vorhanden,
        }


# ---------------------------------------------------------------- reine Regeln
def instanzkennung(modell: str, nummer: int) -> str:
    """Die erste Instanz ist das Modell selbst, weitere heißen <modell>-instanz-<n>."""
    return modell if nummer <= 1 else f"{modell}-instanz-{nummer}"


def kennungen(modell: str, anzahl: int) -> list[str]:
    return [instanzkennung(modell, n) for n in range(1, max(1, anzahl) + 1)]


def passt_in_speicher(verfuegbar_gb: float, groesse_gb: float, reserve_gb: float) -> bool:
    """Eine weitere Instanz darf geladen werden, wenn danach noch die Reserve frei bleibt."""
    return verfuegbar_gb - groesse_gb >= reserve_gb


def verteile[T](stapel: list[T], ziele: list[str]) -> list[tuple[T, str]]:
    """Stapel im Wechsel auf die Instanzen verteilen (rund um)."""
    if not ziele:
        raise ValueError("Keine Instanz zum Verteilen")
    return [(s, ziele[i % len(ziele)]) for i, s in enumerate(stapel)]


# ---------------------------------------------------------------- Speicher und LM Studio
def speicherstand() -> Speicherstand:
    """Speicher aus sysctl und vm_stat (macOS); auf anderen Systemen 0, dann wird nicht geladen."""
    try:
        gesamt = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5).stdout.strip())
        vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, ValueError, subprocess.SubprocessError):
        return Speicherstand(0.0, 0.0, 0.0)
    seitengroesse = 4096
    werte: dict[str, int] = {}
    for zeile in vm.splitlines():
        if "page size of" in zeile:
            seitengroesse = int("".join(c for c in zeile.split("page size of")[1] if c.isdigit()) or 4096)
        elif ":" in zeile:
            name, wert = zeile.split(":", 1)
            wert = wert.strip().rstrip(".")
            if wert.isdigit():
                werte[name.strip()] = int(wert)
    frei = (werte.get("Pages free", 0) + werte.get("Pages speculative", 0)) * seitengroesse
    inaktiv = werte.get("Pages inactive", 0) * seitengroesse
    return Speicherstand(gesamt / GIGABYTE, frei / GIGABYTE, inaktiv / GIGABYTE)


def lms_pfad(werte: Mapping[str, Any]) -> Path | None:
    eigener = str(werte.get("einbettung.lms_pfad") or "").strip()
    kandidaten = [Path(eigener)] if eigener else []
    gefunden = shutil.which("lms")
    if gefunden:
        kandidaten.append(Path(gefunden))
    kandidaten.append(LMS_VORGABE)
    return next((k for k in kandidaten if k.is_file()), None)


async def geladene_instanzen(basis_url: str, modell: str) -> list[Instanz]:
    """Alle geladenen Instanzen des Modells laut LM Studio (Kennung und Größe)."""
    lms = lms_pfad({})
    if lms is not None:
        try:
            prozess = await asyncio.create_subprocess_exec(
                str(lms), "ps", "--json", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            aus, _ = await asyncio.wait_for(prozess.communicate(), timeout=20)
            eintraege = json.loads(aus.decode("utf-8", errors="replace") or "[]")
            return [
                Instanz(kennung=str(e.get("identifier")), groesse_gb=float(e.get("sizeBytes") or 0) / GIGABYTE)
                for e in eintraege
                if e.get("type") == "embedding" and str(e.get("modelKey")) == modell
            ]
        except (OSError, ValueError, TimeoutError):
            log.warning("lms ps lieferte nichts Brauchbares; weiche auf die Modellliste aus")
    # Ohne Befehlszeile: die Modellliste des Servers, Größe unbekannt.
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            daten = (await client.get(f"{basis_url.rstrip('/')}/models")).json().get("data") or []
    except (httpx.HTTPError, ValueError):
        return []
    return [
        Instanz(kennung=str(m.get("id")), groesse_gb=0.0)
        for m in daten
        if str(m.get("id")) == modell or str(m.get("id")).startswith(f"{modell}-instanz-")
    ]


async def _lms(lms: Path, *argumente: str, zeitgrenze_s: float = LADE_ZEITGRENZE_S) -> tuple[int, str]:
    prozess = await asyncio.create_subprocess_exec(str(lms), *argumente, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        aus, _ = await asyncio.wait_for(prozess.communicate(), timeout=zeitgrenze_s)
    except TimeoutError:
        prozess.kill()
        return 1, "Zeitgrenze überschritten"
    return int(prozess.returncode or 0), aus.decode("utf-8", errors="replace").strip()


async def stand(basis_url: str, modell: str, werte: Mapping[str, Any]) -> Instanzstand:
    return Instanzstand(
        modell=modell,
        gewuenscht=int(werte.get("einbettung.instanzen", 1)),
        geladen=await geladene_instanzen(basis_url, modell),
        speicher=speicherstand(),
        lms_vorhanden=lms_pfad(werte) is not None,
    )


async def sicherstellen(basis_url: str, modell: str, werte: Mapping[str, Any]) -> Instanzstand:
    """Lädt fehlende Instanzen bis zur eingestellten Zahl, solange der Speicher reicht."""
    s = await stand(basis_url, modell, werte)
    reserve = float(werte.get("einbettung.speicher_reserve_gb", 8))
    lms = lms_pfad(werte)
    vorhanden = {i.kennung for i in s.geladen}
    if s.gewuenscht > 1 and lms is None:
        s.hinweise.append("Die Befehlszeile von LM Studio (lms) wurde nicht gefunden; weitere Instanzen lassen sich nicht laden.")
        return s
    groesse = next((i.groesse_gb for i in s.geladen if i.groesse_gb > 0), 0.7)
    for kennung in kennungen(modell, s.gewuenscht)[1:]:
        if kennung in vorhanden:
            continue
        speicher = speicherstand()
        if not passt_in_speicher(speicher.verfuegbar_gb, groesse, reserve):
            s.hinweise.append(
                f"{kennung} nicht geladen: {speicher.verfuegbar_gb:.1f} GB verfügbar, {groesse:.2f} GB nötig plus {reserve:.0f} GB Reserve."
            )
            break
        code, ausgabe = await _lms(lms, "load", modell, "--identifier", kennung, "-y")  # type: ignore[arg-type]
        if code != 0:
            s.hinweise.append(f"{kennung} konnte nicht geladen werden: {ausgabe[-200:]}")
            break
        log.info("Einbettungsinstanz %s geladen", kennung)
    s.geladen = await geladene_instanzen(basis_url, modell)
    s.speicher = speicherstand()
    return s


async def abbauen(basis_url: str, modell: str, werte: Mapping[str, Any]) -> Instanzstand:
    """Entlädt alle zusätzlichen Instanzen; die erste (das Modell selbst) bleibt."""
    lms = lms_pfad(werte)
    s = await stand(basis_url, modell, werte)
    if lms is None:
        s.hinweise.append("Die Befehlszeile von LM Studio (lms) wurde nicht gefunden.")
        return s
    for i in s.geladen:
        if i.kennung != modell:
            code, ausgabe = await _lms(lms, "unload", i.kennung, zeitgrenze_s=60)
            if code != 0:
                s.hinweise.append(f"{i.kennung} nicht entladen: {ausgabe[-200:]}")
    s.geladen = await geladene_instanzen(basis_url, modell)
    s.speicher = speicherstand()
    return s


def aktive_kennungen(s: Instanzstand) -> list[str]:
    """Die Instanzen, auf die Stapel verteilt werden: die geladenen in der Reihenfolge der Nummern."""
    geladen = {i.kennung for i in s.geladen}
    aus = [k for k in kennungen(s.modell, s.gewuenscht) if k in geladen]
    return aus or [s.modell]
