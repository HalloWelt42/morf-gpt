"""Stufe Einbetten: alle Chunks eines Videos mit dem aktiven Einbettungsanbieter."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ...db.engine import sitzung
from ...domaene.fliessband import Auftragsart
from ..anbieter import dienst as anbieter_dienst
from ..auftraege import stufen
from ..einbettung import dienst as einbettung_dienst
from ..einbettung import instanzen as instanzen_dienst
from ..ereignisse import bus

if TYPE_CHECKING:
    from ..auftraege.laeufer import AuftragKontext


async def _instanzen(k: AuftragKontext) -> list[str] | None:
    """Bei LM Studio die eingestellte Zahl an Instanzen laden (soweit der Speicher reicht) und ihre Kennungen liefern."""
    if int(k.werte.get("einbettung.instanzen", 1)) <= 1:
        return None
    async with sitzung() as s:
        zeile = await anbieter_dienst.anbieter_fuer_rolle(s, "einbettung")
    if zeile.typ != "lmstudio":
        await k.protokoll("Mehrere Instanzen gibt es nur bei LM Studio; der Anbieter ist " + zeile.typ, "warn")
        return None
    stand = await instanzen_dienst.sicherstellen(zeile.basis_url, zeile.modell, k.werte)
    for hinweis in stand.hinweise:
        await k.protokoll(hinweis, "warn")
    kennungen = instanzen_dienst.aktive_kennungen(stand)
    await k.protokoll(f"{len(kennungen)} Instanz(en): {', '.join(kennungen)}; verfügbarer Speicher {stand.speicher.verfuegbar_gb:.1f} GB")
    return kennungen


@stufen.registriere(Auftragsart.EINBETTUNG)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis: anzahl, modell, anbieter, dimension, dauer_verarbeitung_s."""
    if not k.video_id and not k.dokument_id:
        raise RuntimeError("Die Stufe Einbettung braucht ein Video oder ein Dokument")
    await k.fortschritt(0.02, "Einbettung beginnt")
    kennungen = await _instanzen(k)
    start = time.monotonic()
    ergebnis = await einbettung_dienst.chunks_einbetten(
        k.video_id, k.werte, dokument_id=k.dokument_id, instanzen=kennungen, fortschritt=k.fortschritt, abbruch=k.abbruch
    )
    dauer = time.monotonic() - start
    await k.protokoll(
        f"{ergebnis.anzahl} Stücke eingebettet mit {ergebnis.anbieter} ({ergebnis.modell}, {ergebnis.dimension} Dimensionen) "
        f"in {dauer:.1f} Sekunden"
    )
    bus.veroeffentliche(
        "einbettung", aktion="fertig", video_id=k.video_id, dokument_id=k.dokument_id, anzahl=ergebnis.anzahl, modell=ergebnis.modell
    )
    return {
        "anzahl": ergebnis.anzahl,
        "modell": ergebnis.modell,
        "anbieter": ergebnis.anbieter,
        "dimension": ergebnis.dimension,
        "dauer_verarbeitung_s": round(dauer, 1),
    }
