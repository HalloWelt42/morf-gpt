"""Register aller Einstellungen: Schlüssel, Vorgabe, Grenzen, Einheit, Beschreibung.

Einzige Wahrheit über die Bedeutung einer Einstellung. Die Werte liegen in der
Datenbank (Tabelle einstellungen); was hier nicht steht, gibt es nicht. Die
Oberfläche zeigt jede Einstellung mit Beschreibung, Grenzen und Einheit - keine
versteckten Grenzen (siehe docs/ARCHITEKTUR.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

Typ = Literal["zahl", "ganzzahl", "text", "schalter", "auswahl"]


@dataclass(frozen=True, slots=True)
class Definition:
    schluessel: str
    titel: str
    beschreibung: str
    typ: Typ
    vorgabe: Any
    gruppe: str
    einheit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    schritt: float | None = None
    auswahl: tuple[tuple[str, str], ...] = field(default_factory=tuple)  # (wert, titel)
    geheim: bool = False


DEFINITIONEN: tuple[Definition, ...] = (
    # --- Quelle und Auswahl -------------------------------------------------
    Definition(
        "quelle.mindest_dauer_s", "Mindestdauer eines Videos",
        "Nur Videos, die länger sind als dieser Wert, werden automatisch in den Umfang aufgenommen. "
        "Kürzere lassen sich in der Videoliste von Hand aufnehmen.",
        "ganzzahl", 300, "quelle", einheit="Sekunden", minimum=0, maximum=36000, schritt=30,
    ),
    Definition(
        "quelle.typen", "Videoarten im Umfang",
        "Welche Arten die Quelle liefert und automatisch aufgenommen werden (Shorts sind ohnehin kurz).",
        "text", "video,live", "quelle",
    ),
    Definition(
        "quelle.nur_heruntergeladene", "Nur bereits heruntergeladene Videos",
        "Wenn an, werden nur Videos aufgenommen, die in der Quelle schon als Datei vorliegen.",
        "schalter", True, "quelle",
    ),
    Definition(
        "quelle.serie_zuerst", "Serie zuerst",
        "Aufträge für die Erklärserie (mmM) werden vor allen anderen Videos abgearbeitet.",
        "schalter", True, "quelle",
    ),
    Definition(
        "quelle.serien_kennung", "Kennung der Erklärserie",
        "Text im Titel, an dem die Serie erkannt wird (z. B. 'mmM'). Die Folgennummer folgt nach '#'.",
        "text", "mmM", "quelle",
    ),
    # --- Fließband -------------------------------------------------------------
    Definition(
        "band.automatik", "Automatisch weiterreichen",
        "Nach einer fertigen Stufe wird sofort der Auftrag der nächsten Stufe angelegt.",
        "schalter", True, "band",
    ),
    Definition(
        "band.parallel.audio", "Parallele Audio-Aufträge",
        "Wie viele Audios gleichzeitig beschafft werden (Netz und ffmpeg).",
        "ganzzahl", 2, "band", minimum=1, maximum=8,
    ),
    Definition(
        "band.parallel.transkription", "Parallele Transkriptionen",
        "Der Whisper-Dienst nutzt die Grafikeinheit; mehr als 1 bringt nichts.",
        "ganzzahl", 1, "band", minimum=1, maximum=2,
    ),
    Definition(
        "band.parallel.korrektur", "Parallele Korrekturen",
        "Ein lokales Sprachmodell antwortet nacheinander; bei einem Cloud-Anbieter sind 2 bis 3 sinnvoll.",
        "ganzzahl", 1, "band", minimum=1, maximum=6,
    ),
    Definition(
        "band.parallel.stueckelung", "Parallele Stückelungen",
        "Reine Rechenarbeit, kann breit laufen.",
        "ganzzahl", 4, "band", minimum=1, maximum=16,
    ),
    Definition(
        "band.parallel.einbettung", "Parallele Einbettungen",
        "Das Einbettungsmodell arbeitet stapelweise; 1 reicht meist.",
        "ganzzahl", 1, "band", minimum=1, maximum=4,
    ),
    Definition(
        "band.wiederholungen", "Wiederholungen bei Fehlern",
        "So oft wird ein fehlgeschlagener Auftrag automatisch erneut versucht.",
        "ganzzahl", 2, "band", minimum=0, maximum=10,
    ),
    Definition(
        "band.herzschlag_frist_s", "Frist ohne Lebenszeichen",
        "Meldet sich ein laufender Auftrag so lange nicht, gilt er als hängend und wird als Fehler markiert.",
        "ganzzahl", 7200, "band", einheit="Sekunden", minimum=60, maximum=86400, schritt=60,
    ),
    Definition("band.pause.audio", "Stufe Audio pausiert", "Keine neuen Audio-Aufträge starten.", "schalter", False, "band"),
    Definition("band.pause.transkription", "Stufe Transkription pausiert", "Keine neuen Transkriptionen starten.", "schalter", False, "band"),
    Definition("band.pause.korrektur", "Stufe Korrektur pausiert", "Keine neuen Korrekturen starten.", "schalter", False, "band"),
    Definition("band.pause.stueckelung", "Stufe Stückelung pausiert", "Keine neuen Stückelungen starten.", "schalter", False, "band"),
    Definition("band.pause.einbettung", "Stufe Einbettung pausiert", "Keine neuen Einbettungen starten.", "schalter", False, "band"),
    # --- Audio -----------------------------------------------------------------
    Definition(
        "audio.bezugsweg", "Bezugsweg für Audio",
        "Videostrom: das Video wird von der Quelle gestreamt und hier mit ffmpeg zu Audio gewandelt (schnell, "
        "nichts bleibt auf dem Quellrechner). Quelle: die Quelle extrahiert selbst und liefert die Audiodatei.",
        "auswahl", "videostrom_ffmpeg", "audio",
        auswahl=(("videostrom_ffmpeg", "Videostrom + ffmpeg hier"), ("quelle_extraktion", "Extraktion in der Quelle")),
    ),
    Definition(
        "audio.bitrate_kbit", "Audio-Bitrate",
        "Mono-AAC. 64 reicht für Sprache und Transkription; mehr macht die Dateien nur größer.",
        "ganzzahl", 64, "audio", einheit="kbit/s", minimum=32, maximum=192, schritt=16,
    ),
    Definition(
        "audio.abtastrate", "Abtastrate",
        "Whisper arbeitet mit 16.000 Hz; 24.000 klingt beim Abspielen etwas voller.",
        "ganzzahl", 24000, "audio", einheit="Hz", minimum=16000, maximum=48000, schritt=8000,
    ),
    # --- Transkription ---------------------------------------------------------
    Definition(
        "transkription.engine", "Transkriptionsdienst",
        "Worker: direkt der Whisper-Worker von txt2voice (ohne Sprechertrennung, ohne Eintrag in dessen "
        "Bibliothek). App: über die txt2voice-Oberfläche (legt dort eine Transkription an).",
        "auswahl", "txt2voice_worker", "transkription",
        auswahl=(("txt2voice_worker", "txt2voice-Worker"), ("txt2voice_api", "txt2voice-App")),
    ),
    Definition(
        "transkription.worker_url", "Adresse des Whisper-Workers",
        "HTTP-Adresse des txt2voice-Workers.", "text", "http://127.0.0.1:10033", "transkription",
    ),
    Definition(
        "transkription.app_url", "Adresse der txt2voice-App",
        "HTTP-Adresse des txt2voice-Backends.", "text", "http://127.0.0.1:10031", "transkription",
    ),
    Definition(
        "transkription.sprache", "Sprache", "Sprache der Aufnahmen (Whisper-Sprachname).",
        "text", "german", "transkription",
    ),
    Definition(
        "transkription.zeitgrenze_s", "Zeitgrenze je Transkription",
        "So lange darf eine Transkription dauern, bevor sie als Fehler gilt (lange Videos brauchen lange).",
        "ganzzahl", 14400, "transkription", einheit="Sekunden", minimum=300, maximum=86400, schritt=300,
    ),
    Definition(
        "transkription.wortzeiten_speichern", "Wortzeiten speichern",
        "Zeitmarke je Wort mitspeichern (größere Datensätze, feinere Sprünge).",
        "schalter", True, "transkription",
    ),
    # --- Korrektur -------------------------------------------------------------
    Definition(
        "korrektur.block_zeichen", "Blockgröße der Korrektur",
        "Der Rohtext wird in Blöcke dieser Größe (an Segmentgrenzen) geschnitten und blockweise korrigiert.",
        "ganzzahl", 2500, "korrektur", einheit="Zeichen", minimum=800, maximum=8000, schritt=100,
    ),
    Definition(
        "korrektur.mindest_aehnlichkeit", "Abweichungswächter",
        "Liegt die Ähnlichkeit zwischen Rohtext und Korrektur eines Blocks darunter, bleibt der Rohtext stehen. "
        "So kann das Modell keinen Inhalt verändern.",
        "zahl", 0.80, "korrektur", minimum=0.5, maximum=1.0, schritt=0.01,
    ),
    Definition(
        "korrektur.temperatur", "Temperatur des Modells",
        "0 = so wortgetreu wie möglich. Höhere Werte erlauben freiere Formulierungen (nicht empfohlen).",
        "zahl", 0.0, "korrektur", minimum=0.0, maximum=1.0, schritt=0.05,
    ),
    Definition(
        "korrektur.zeitgrenze_s", "Zeitgrenze je Modellaufruf",
        "So lange darf ein einzelner Aufruf des Sprachmodells dauern.",
        "ganzzahl", 1800, "korrektur", einheit="Sekunden", minimum=60, maximum=14400, schritt=60,
    ),
    Definition(
        "korrektur.themen", "Themenaufschlüsselung erstellen",
        "Nach der Korrektur einen zweiten Aufruf, der Abschnitte mit Titel, Zeitfenster und Kurzfassung "
        "sowie eine Kurzzusammenfassung des Videos liefert.",
        "schalter", True, "korrektur",
    ),
    # --- Stückelung ------------------------------------------------------------
    Definition(
        "stueckelung.ziel_zeichen", "Zielgröße eines Stücks",
        "Große Stücke tragen mehr Zusammenhang. Das Einbettungsmodell verträgt bis etwa 8.000 Zeichen.",
        "ganzzahl", 3000, "stueckelung", einheit="Zeichen", minimum=800, maximum=8000, schritt=100,
    ),
    Definition(
        "stueckelung.ueberlappung_zeichen", "Überlappung",
        "So viel Text (ganze Sätze) wiederholt ein Stück vom Ende des vorigen, damit kein Gedanke am Schnitt verloren geht.",
        "ganzzahl", 400, "stueckelung", einheit="Zeichen", minimum=0, maximum=2000, schritt=50,
    ),
    Definition(
        "stueckelung.kontextkopf", "Kontextkopf einbetten",
        "Der Einbettungstext beginnt mit Videotitel und Thema, damit die Suche den Zusammenhang kennt.",
        "schalter", True, "stueckelung",
    ),
    # --- Einbettung --------------------------------------------------------------
    Definition(
        "einbettung.stapel", "Stapelgröße",
        "So viele Stücke gehen je Aufruf an das Einbettungsmodell.",
        "ganzzahl", 16, "einbettung", minimum=1, maximum=128,
    ),
    Definition(
        "einbettung.zeitgrenze_s", "Zeitgrenze je Aufruf",
        "So lange darf ein Einbettungsaufruf dauern.", "ganzzahl", 600, "einbettung",
        einheit="Sekunden", minimum=30, maximum=3600, schritt=30,
    ),
    # --- Suche und Chat ----------------------------------------------------------
    Definition(
        "suche.treffer", "Anzahl Treffer",
        "Wie viele Textstellen die Suche höchstens auswählt (Breite).",
        "ganzzahl", 8, "suche", minimum=1, maximum=50,
    ),
    Definition(
        "suche.nachbarn", "Nachbarstücke",
        "So viele angrenzende Stücke je Treffer werden zusätzlich mitgegeben (Breite).",
        "ganzzahl", 0, "suche", minimum=0, maximum=3,
    ),
    Definition(
        "suche.max_je_video", "Höchstens je Video",
        "Vielfalt: nicht mehr als so viele Stücke aus demselben Video (0 = keine Grenze).",
        "ganzzahl", 3, "suche", minimum=0, maximum=50,
    ),
    Definition(
        "suche.mindest_aehnlichkeit", "Mindestähnlichkeit",
        "Treffer unter diesem Wert (Cosinus 0 bis 1) werden verworfen (Genauigkeit).",
        "zahl", 0.45, "suche", minimum=0.0, maximum=1.0, schritt=0.01,
    ),
    Definition(
        "suche.neubewertung", "Neu-Bewertung",
        "Aus: reine Vektorreihenfolge. Cross-Encoder: lokales Modell ordnet die Kandidaten neu (genauer, "
        "etwa eine Sekunde). Sprachmodell: das Chat-Modell bewertet (sehr genau, langsam).",
        "auswahl", "aus", "suche",
        auswahl=(("aus", "Aus"), ("crossencoder", "Cross-Encoder"), ("sprachmodell", "Sprachmodell")),
    ),
    Definition(
        "suche.kandidaten_faktor", "Kandidaten je Treffer",
        "Für Neu-Bewertung und Vielfalt werden so viel mal mehr Kandidaten geholt als Treffer gewünscht.",
        "ganzzahl", 4, "suche", minimum=1, maximum=10,
    ),
    Definition(
        "chat.max_tokens", "Antwortlänge",
        "Höchstzahl an Tokens je Antwort.", "ganzzahl", 4000, "chat", einheit="Tokens", minimum=200, maximum=32000, schritt=100,
    ),
    Definition(
        "chat.temperatur", "Temperatur", "0 = nüchtern und belegnah, 1 = freier.",
        "zahl", 0.2, "chat", minimum=0.0, maximum=1.5, schritt=0.05,
    ),
    Definition(
        "chat.verlauf_nachrichten", "Verlauf im Kontext",
        "So viele vorige Nachrichten der Unterhaltung bekommt das Modell mit.",
        "ganzzahl", 6, "chat", minimum=0, maximum=40,
    ),
    Definition(
        "chat.zeitgrenze_s", "Zeitgrenze je Antwort",
        "So lange darf eine Antwort dauern.", "ganzzahl", 1800, "chat", einheit="Sekunden", minimum=30, maximum=7200, schritt=30,
    ),
    Definition(
        "chat.videoebene", "Videoebene mitgeben",
        "Zu jeder Fundstelle bekommt das Modell auch die Kurzzusammenfassung des Videos.",
        "schalter", True, "chat",
    ),
    # --- Anbieter-Rollen ----------------------------------------------------------
    Definition("anbieter.chat", "Anbieter für Chat", "Kennung des aktiven Sprachmodell-Anbieters für Antworten.", "text", "", "anbieter"),
    Definition("anbieter.korrektur", "Anbieter für Korrektur", "Kennung des Sprachmodell-Anbieters für die Korrektur.", "text", "", "anbieter"),
    Definition("anbieter.einbettung", "Anbieter für Einbettung", "Kennung des Einbettungsanbieters (baut und befragt den Index).", "text", "", "anbieter"),
)

GRUPPEN_TITEL: dict[str, str] = {
    "quelle": "Quelle und Auswahl",
    "band": "Fließband",
    "audio": "Audio",
    "transkription": "Transkription",
    "korrektur": "Korrektur",
    "stueckelung": "Stückelung",
    "einbettung": "Einbettung",
    "suche": "Suche",
    "chat": "Chat",
    "anbieter": "Anbieter",
}

JE_SCHLUESSEL: dict[str, Definition] = {d.schluessel: d for d in DEFINITIONEN}


def definition(schluessel: str) -> Definition:
    try:
        return JE_SCHLUESSEL[schluessel]
    except KeyError as e:
        raise KeyError(f"Unbekannte Einstellung: {schluessel}") from e


def pruefe_wert(d: Definition, wert: Any) -> Any:
    """Prüft und normalisiert einen Wert gegen seine Definition. Wirft ValueError."""
    if d.typ == "schalter":
        if isinstance(wert, bool):
            return wert
        if isinstance(wert, str) and wert.lower() in ("true", "an", "1", "ja"):
            return True
        if isinstance(wert, str) and wert.lower() in ("false", "aus", "0", "nein"):
            return False
        raise ValueError(f"{d.titel}: erwartet an/aus")
    if d.typ in ("zahl", "ganzzahl"):
        try:
            zahl = int(wert) if d.typ == "ganzzahl" else float(wert)
        except (TypeError, ValueError) as e:
            raise ValueError(f"{d.titel}: erwartet eine Zahl") from e
        if d.minimum is not None and zahl < d.minimum:
            raise ValueError(f"{d.titel}: mindestens {d.minimum} {d.einheit}".strip())
        if d.maximum is not None and zahl > d.maximum:
            raise ValueError(f"{d.titel}: höchstens {d.maximum} {d.einheit}".strip())
        return zahl
    if d.typ == "auswahl":
        werte = {w for w, _ in d.auswahl}
        if str(wert) not in werte:
            raise ValueError(f"{d.titel}: ungültige Auswahl '{wert}'")
        return str(wert)
    return "" if wert is None else str(wert)
