"""Anbieter-Register: aus Datenbank-Einträgen die passende Umsetzung bauen.

Rollen (chat, korrektur, einbettung) zeigen per Einstellung auf eine Anbieter-Kennung.
Beim ersten Start werden sinnvolle Anbieter angelegt (LM Studio lokal, fastembed,
Hetzner-Inferenz falls ein Schlüssel in der Umgebung liegt); der Nutzer ändert alles
in der Oberfläche.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...db.modelle import Anbieter
from ..einstellungen import dienst as einstellungen_dienst
from .basis import AnbieterFehler, AnbieterInfo, EinbettungsAnbieter, SprachmodellAnbieter
from .fastembed_anbieter import BEKANNTE_MODELLE, FastembedEinbettung
from .lmstudio import LmStudio, LmStudioEinbettung
from .openai_kompatibel import OpenAiKompatibel, OpenAiKompatibelEinbettung

TYPEN: dict[str, str] = {
    "lmstudio": "LM Studio (lokal)",
    "openai_kompatibel": "OpenAI-kompatibler Dienst",
    "fastembed": "Lokale Einbettung (fastembed)",
}

ROLLEN: dict[str, str] = {
    "chat": "Chat-Antworten",
    "korrektur": "Korrektur der Transkripte",
    "einbettung": "Einbettung (Index und Suche)",
}

LMSTUDIO_URL = "http://127.0.0.1:1234/v1"
HETZNER_URL = "https://inference.hetzner.com/api/v1"


def _info(a: Anbieter) -> AnbieterInfo:
    dim = a.parameter.get("dimension") if isinstance(a.parameter, dict) else None
    if a.art == "einbettung" and dim is None and a.typ == "fastembed":
        dim = BEKANNTE_MODELLE.get(a.modell)
    return AnbieterInfo(kennung=a.id, name=a.name, typ=a.typ, modell=a.modell, basis_url=a.basis_url, dimension=dim)


def baue_sprachmodell(a: Anbieter) -> SprachmodellAnbieter:
    if a.art != "sprachmodell":
        raise AnbieterFehler(f"Anbieter '{a.name}' ist kein Sprachmodell")
    zusatz = a.parameter.get("zusatz") if isinstance(a.parameter, dict) else None
    if a.typ == "lmstudio":
        return LmStudio(_info(a), a.api_schluessel, zusatz)
    if a.typ == "openai_kompatibel":
        return OpenAiKompatibel(_info(a), a.api_schluessel, zusatz)
    raise AnbieterFehler(f"Unbekannter Sprachmodell-Typ '{a.typ}'")


def baue_einbettung(a: Anbieter) -> EinbettungsAnbieter:
    if a.art != "einbettung":
        raise AnbieterFehler(f"Anbieter '{a.name}' ist keine Einbettung")
    if a.typ == "lmstudio":
        return LmStudioEinbettung(_info(a), a.api_schluessel)
    if a.typ == "openai_kompatibel":
        return OpenAiKompatibelEinbettung(_info(a), a.api_schluessel)
    if a.typ == "fastembed":
        return FastembedEinbettung(_info(a))
    raise AnbieterFehler(f"Unbekannter Einbettungs-Typ '{a.typ}'")


async def anbieter_fuer_rolle(session: AsyncSession, rolle: str) -> Anbieter:
    """Der aktive Anbieter-Eintrag einer Rolle. Fehlt er, ein sprechender Fehler."""
    if rolle not in ROLLEN:
        raise AnbieterFehler(f"Unbekannte Rolle '{rolle}'")
    kennung = await einstellungen_dienst.wert(session, f"anbieter.{rolle}")
    if not kennung:
        raise AnbieterFehler(f"Für die Rolle '{ROLLEN[rolle]}' ist kein Anbieter gewählt (Einstellungen).")
    a = await session.get(Anbieter, kennung)
    if a is None:
        raise AnbieterFehler(f"Der gewählte Anbieter für '{ROLLEN[rolle]}' existiert nicht mehr.")
    if not a.aktiv:
        raise AnbieterFehler(f"Der Anbieter '{a.name}' ist deaktiviert.")
    return a


async def sprachmodell_fuer(session: AsyncSession, rolle: str) -> SprachmodellAnbieter:
    return baue_sprachmodell(await anbieter_fuer_rolle(session, rolle))


async def einbettung_aktiv(session: AsyncSession) -> EinbettungsAnbieter:
    return baue_einbettung(await anbieter_fuer_rolle(session, "einbettung"))


async def alle(session: AsyncSession) -> list[Anbieter]:
    return list((await session.execute(select(Anbieter).order_by(Anbieter.art, Anbieter.erstellt))).scalars().all())


async def anlegen_wenn_leer(session: AsyncSession) -> None:
    """Erststart: Standard-Anbieter anlegen und Rollen belegen (nur wenn noch nichts da ist)."""
    vorhanden = await alle(session)
    if vorhanden:
        return
    lm_chat = Anbieter(
        name="LM Studio - Chat",
        typ="lmstudio",
        art="sprachmodell",
        basis_url=LMSTUDIO_URL,
        modell="qwen3-next-80b-a3b-instruct-mlx@4bit",
    )
    lm_einbettung = Anbieter(
        name="LM Studio - bge-m3",
        typ="lmstudio",
        art="einbettung",
        basis_url=LMSTUDIO_URL,
        modell="text-embedding-bge-m3",
        parameter={"dimension": 1024},
    )
    lokal_einbettung = Anbieter(
        name="Lokal - bge-m3 (fastembed)",
        typ="fastembed",
        art="einbettung",
        modell="BAAI/bge-m3",
        parameter={"dimension": 1024},
    )
    session.add_all([lm_chat, lm_einbettung, lokal_einbettung])
    hetzner_schluessel = os.environ.get("MORF_HETZNER_API_SCHLUESSEL", "").strip()
    if hetzner_schluessel:
        session.add(
            Anbieter(
                name="Hetzner-Inferenz - Qwen3.6 35B",
                typ="openai_kompatibel",
                art="sprachmodell",
                basis_url=HETZNER_URL,
                api_schluessel=hetzner_schluessel,
                modell="Qwen/Qwen3.6-35B-A3B-FP8",
            )
        )
    await session.flush()
    await einstellungen_dienst.setze(session, "anbieter.chat", lm_chat.id)
    await einstellungen_dienst.setze(session, "anbieter.korrektur", lm_chat.id)
    await einstellungen_dienst.setze(session, "anbieter.einbettung", lm_einbettung.id)


def oeffentlich(a: Anbieter, schluessel_zeigen: bool = False) -> dict[str, Any]:
    """Darstellung für die API. Der Schlüssel ist im Verwaltungsbereich lesbar."""
    return {
        "id": a.id,
        "name": a.name,
        "typ": a.typ,
        "typ_titel": TYPEN.get(a.typ, a.typ),
        "art": a.art,
        "basis_url": a.basis_url,
        "modell": a.modell,
        "parameter": a.parameter or {},
        "aktiv": a.aktiv,
        "api_schluessel": a.api_schluessel if schluessel_zeigen else ("*" * 8 + a.api_schluessel[-4:] if a.api_schluessel else ""),
        "hat_schluessel": bool(a.api_schluessel),
        "erstellt": a.erstellt.isoformat() if a.erstellt else None,
    }
