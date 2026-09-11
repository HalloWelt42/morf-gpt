"""Stufe Einbetten: alle Chunks eines Videos mit dem aktiven Einbettungsanbieter."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

from ...domaene.fliessband import Auftragsart
from ..auftraege import stufen
from ..einbettung import dienst as einbettung_dienst
from ..ereignisse import bus

if TYPE_CHECKING:
    from ..auftraege.laeufer import AuftragKontext


@stufen.registriere(Auftragsart.EINBETTUNG)
async def ausfuehren(k: AuftragKontext, parameter: dict[str, Any]) -> dict[str, Any]:
    """Ergebnis: anzahl, modell, anbieter, dimension, dauer_verarbeitung_s."""
    if not k.video_id:
        raise RuntimeError("Die Stufe Einbettung braucht ein Video")
    await k.fortschritt(0.02, "Einbettung beginnt")
    start = time.monotonic()
    ergebnis = await einbettung_dienst.chunks_einbetten(k.video_id, k.werte, fortschritt=k.fortschritt, abbruch=k.abbruch)
    dauer = time.monotonic() - start
    await k.protokoll(
        f"{ergebnis.anzahl} Stücke eingebettet mit {ergebnis.anbieter} ({ergebnis.modell}, {ergebnis.dimension} Dimensionen) "
        f"in {dauer:.1f} Sekunden"
    )
    bus.veroeffentliche("einbettung", aktion="fertig", video_id=k.video_id, anzahl=ergebnis.anzahl, modell=ergebnis.modell)
    return {
        "anzahl": ergebnis.anzahl,
        "modell": ergebnis.modell,
        "anbieter": ergebnis.anbieter,
        "dimension": ergebnis.dimension,
        "dauer_verarbeitung_s": round(dauer, 1),
    }
