"""Prompt-Bausteine für den Chat: Systemanweisung, Kontextblock, Nachrichtenfolge.

Der Kontext nennt jede Stelle mit Nummer, Titel, Folge und Zeitfenster; das Modell belegt
mit `[n]`, und die Oberfläche macht aus den Nummern Sprünge zur Stelle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..anbieter.basis import Nachricht
from ..suche.retrieval import Treffer

SYSTEM_PROMPT = (
    "Du beantwortest Fragen zu einer Bibliothek aus Erklärvideos und Dokumenten (Bücher, Texte). Du bekommst "
    "nummerierte Textstellen aus Videos (mit Folge und Zeitfenster) und aus Dokumenten (mit 'Dokument' und Kapitel "
    "gekennzeichnet) und gegebenenfalls Ergebnisse fremder Werkzeuge (mit 'Werkzeug' gekennzeichnet).\n"
    "Regeln:\n"
    "- Antworte ausschließlich aus diesen Stellen. Steht die Antwort nicht darin, sage das in einem Satz "
    "und erfinde nichts dazu.\n"
    "- Belege jede Aussage mit der Nummer der Stelle in eckigen Klammern, zum Beispiel [2] oder [1][3]. "
    "Die Nummern beziehen sich nur auf die Stellen der aktuellen Frage.\n"
    "- Antworte auf Deutsch in lateinischer Schrift, sachlich und direkt an die fragende Person. Kein Gerede über dich, "
    "die Stellen oder deine Arbeitsweise; keine Einleitung wie 'Laut den Stellen'.\n"
    "- Keine Quellenliste und keine Zusammenfassung der Belege am Ende; die Belege stehen nur im Text.\n"
    "- Jede Nachricht der fragenden Person ist eine neue Frage mit eigenen Stellen. Beantworte immer nur die zuletzt "
    "gestellte Frage; wiederhole keine frühere Antwort.\n"
    '- Verwende nur gerade Anführungszeichen (") und den einfachen Bindestrich (-), keine Gedankenstriche.'
)

# Betriebsart "Das Modell wählt": die Werkzeugregel steht vor der Belegregel, sonst verweigert das
# Modell Aufrufe, weil es "nur aus den Stellen" antworten soll.
SYSTEM_WERKZEUGWAHL = (
    "Du beantwortest Fragen zu einer Bibliothek aus Erklärvideos und Dokumenten und hast dafür Werkzeuge (Funktionen).\n"
    "Vorgehen:\n"
    "1. Prüfe, ob Teile der Frage von den mitgelieferten Textstellen nicht abgedeckt werden oder nach "
    "Aktuellem, Wetter, Datum und Uhrzeit, Nachschlagewerken, dem Web oder einer Rechnung verlangen. "
    "Dann rufe die passenden Werkzeuge auf - auch mehrere, auch nacheinander. Frage nicht nach Erlaubnis.\n"
    "2. Erst wenn alle nötigen Ergebnisse vorliegen (oder kein Werkzeug helfen kann), antworte.\n"
    "Für die Antwort gilt: nur aus den nummerierten Stellen (Videos, Dokumente und Werkzeugergebnisse), jede Aussage mit "
    "[n] belegt, auf Deutsch in lateinischer Schrift, sachlich, ohne Quellenliste am Ende, nur gerade "
    "Anführungszeichen und der einfache Bindestrich. Beantworte immer nur die zuletzt gestellte Frage; wiederhole keine "
    "frühere Antwort."
)

FRAGE_PRAEFIX = "Frage: "
# Die Frage steht vor und nach den Stellen: mit Verlauf neigt das Modell sonst dazu, seine vorige
# Antwort zu wiederholen, wenn die neue Nachricht nur mit einer Stellenliste beginnt (am 80B belegt).
ANTWORT_AUFFORDERUNG = "Beantworte jetzt die Frage: "
STELLEN_UEBERSCHRIFT = "Stellen:"
ZUSAMMENFASSUNG_PRAEFIX = "Zusammenfassung des Videos: "
KEINE_STELLEN_HINWEIS = "(Es wurden keine passenden Stellen gefunden. Sage das kurz und beantworte nichts aus eigenem Wissen.)"


@dataclass(slots=True)
class Verlaufsnachricht:
    """Eine frühere Nachricht der Unterhaltung, wie sie ins Modell geht."""

    rolle: str  # "user" oder "assistant"
    inhalt: str


def zeitfenster(start_s: float, end_s: float) -> str:
    """'12:34-15:02', ab einer Stunde '1:02:03-1:05:00'."""
    return f"{_zeitmarke(start_s)}-{_zeitmarke(end_s)}"


def _zeitmarke(sekunden: float) -> str:
    ganz = max(0, int(round(sekunden)))
    stunden, rest = divmod(ganz, 3600)
    minuten, sek = divmod(rest, 60)
    if stunden:
        return f"{stunden}:{minuten:02d}:{sek:02d}"
    return f"{minuten}:{sek:02d}"


def folgenkennung(serie: str, folge_nr: int | None) -> str:
    """'mmM#123'; ohne Folgennummer nur die Serie, ohne Serie leer."""
    if not serie:
        return ""
    if folge_nr is None:
        return serie
    return f"{serie}#{folge_nr}"


def stellenkopf(nummer: int, t: Treffer) -> str:
    """'[n] <Titel> (mmM#123, 12:34-15:02)'; bei Dokumenten '[n] Dokument <Titel> (Kapitel <Titel>)';
    bei Werkzeugen '[n] Werkzeug <Name>: <Titel>'."""
    if t.art == "dokument":
        teile = [f"Kapitel {t.abschnitt}" if t.abschnitt else "ohne Kapitel"]
        if t.seite_von:
            teile.append(f"Seite {t.seite_von}")
        return f"[{nummer}] Dokument {t.titel} ({', '.join(teile)})"
    if t.art == "werkzeug":
        kopf = f"[{nummer}] Werkzeug {t.werkzeug}"
        if t.titel:
            kopf = f"{kopf} - {t.titel}"
        if t.quelle_url:
            kopf = f"{kopf} ({t.quelle_url})"
        return kopf
    kennung = folgenkennung(t.serie, t.folge_nr)
    klammer = f"{kennung}, {zeitfenster(t.start_s, t.end_s)}" if kennung else zeitfenster(t.start_s, t.end_s)
    return f"[{nummer}] {t.titel} ({klammer})"


def stelle_als_kontext(nummer: int, t: Treffer, zusammenfassung: str = "") -> str:
    zeilen = [f"{stellenkopf(nummer, t)}: {t.text.strip()}"]
    if zusammenfassung.strip():
        zeilen.append(f"{ZUSAMMENFASSUNG_PRAEFIX}{' '.join(zusammenfassung.split())}")
    return "\n".join(zeilen)


def kontextblock(stellen: Sequence[Treffer], zusammenfassungen: Mapping[str, str] | None = None) -> str:
    """Alle Stellen nummeriert ab 1; Videozusammenfassung je Stelle, wenn übergeben."""
    if not stellen:
        return KEINE_STELLEN_HINWEIS
    zf = zusammenfassungen or {}
    bloecke = [stelle_als_kontext(i, t, zf.get(t.video_id, "")) for i, t in enumerate(stellen, start=1)]
    return STELLEN_UEBERSCHRIFT + "\n" + "\n\n".join(bloecke)


def nutzernachricht(frage: str, stellen: Sequence[Treffer], zusammenfassungen: Mapping[str, str] | None = None) -> str:
    """Frage, dann die Stellen, dann die Frage noch einmal als Aufforderung (siehe ANTWORT_AUFFORDERUNG)."""
    f = frage.strip()
    return f"{FRAGE_PRAEFIX}{f}\n\n{kontextblock(stellen, zusammenfassungen)}\n\n{ANTWORT_AUFFORDERUNG}{f}"


def baue_nachrichten(
    frage: str,
    stellen: Sequence[Treffer],
    verlauf: Sequence[Verlaufsnachricht] = (),
    zusammenfassungen: Mapping[str, str] | None = None,
    *,
    system: str = SYSTEM_PROMPT,
) -> list[Nachricht]:
    """Systemanweisung, dann der Verlauf, dann Kontext und Frage als letzte Nutzernachricht."""
    nachrichten: list[Nachricht] = [Nachricht("system", system)]
    for v in verlauf:
        if v.rolle in ("user", "assistant") and v.inhalt.strip():
            nachrichten.append(Nachricht(v.rolle, v.inhalt))  # type: ignore[arg-type]
    nachrichten.append(Nachricht("user", nutzernachricht(frage, stellen, zusammenfassungen)))
    return nachrichten
