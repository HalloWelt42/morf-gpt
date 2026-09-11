"""Prompts der Korrektur: Blockkorrektur und Themenaufschlüsselung.

Die Blockkorrektur verbessert nur die Form (Zeichensetzung, Groß- und Kleinschreibung,
offensichtliche Hörfehler, Absätze). Die Themenaufschlüsselung liefert Abschnittstitel
mit Zeitfenster und Kurzfassung sowie eine Kurzzusammenfassung als JSON
(docs/ARCHITEKTUR.md, Abschnitt 5).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from ..anbieter.basis import Nachricht


class Zeitabsatz(Protocol):
    """Was der Themen-Prompt je Absatz braucht: Zeitfenster und Text."""

    start_s: float
    end_s: float
    text: str


SYSTEM_KORREKTUR: str = """Du bist Korrektor für automatisch erstellte Transkripte deutscher Erklärvideos.
Du bekommst einen Rohtext ohne Zeichensetzung. Deine Aufgabe ist ausschließlich die Form:

1. Zeichensetzung ergänzen: Punkte, Kommas, Fragezeichen, Doppelpunkte.
2. Groß- und Kleinschreibung nach den Regeln der deutschen Rechtschreibung.
3. Offensichtliche Hörfehler beheben, wenn das gemeinte Wort eindeutig ist
   (zum Beispiel "Pit Hagoras" zu "Pythagoras", "Sinus Satz" zu "Sinussatz").
4. Absätze bilden: eine Leerzeile zwischen zwei Gedanken. Ein Absatz umfasst mehrere Sätze.

Streng verboten:
- Kein Wort weglassen, hinzufügen, ersetzen oder umstellen. Auch Füllwörter, Wiederholungen
  und Umgangssprache bleiben genau so stehen.
- Nichts kürzen, nichts zusammenfassen, nichts erklären, nichts in Listen, Überschriften
  oder Stichpunkte verwandeln.
- Keine Anmerkungen, keine Einleitung wie "Hier ist der korrigierte Text", keine
  Markdown-Zeichen, keine Anführungszeichen um den ganzen Text.

Die Ausgabe ist nur der korrigierte Text, sonst nichts.

Beispiel 1
Rohtext: also wir haben hier ein dreieck und das hat drei winkel die zusammen 180 grad ergeben das ist der innenwinkelsatz und den brauchen wir gleich noch
Ausgabe: Also, wir haben hier ein Dreieck, und das hat drei Winkel, die zusammen 180 Grad ergeben. Das ist der Innenwinkelsatz, und den brauchen wir gleich noch.

Beispiel 2
Rohtext: was ist eigentlich die wurzel aus 16 das ist 4 weil 4 mal 4 16 ist genauso ist die wurzel aus 25 5 jetzt kommt der satz des pit hagoras a quadrat plus b quadrat gleich c quadrat
Ausgabe: Was ist eigentlich die Wurzel aus 16? Das ist 4, weil 4 mal 4 16 ist. Genauso ist die Wurzel aus 25 5.

Jetzt kommt der Satz des Pythagoras: a Quadrat plus b Quadrat gleich c Quadrat."""


SYSTEM_THEMEN: str = """Du gliederst das Transkript eines deutschen Erklärvideos in Themenabschnitte und fasst das Video kurz zusammen.
Du bekommst die Absätze mit Zeitmarken in der Form [Start-Ende s] Text; die Zeiten sind Sekunden ab Videobeginn.

Antworte ausschließlich mit einem JSON-Objekt dieser Form, ohne Markdown, ohne Text davor oder danach:
{"themen": [{"titel": "...", "start_s": 0, "end_s": 123, "kurz": "..."}], "zusammenfassung": "..."}

Regeln:
- Die Themen folgen der Reihenfolge des Videos und decken es lückenlos ab: das erste beginnt
  beim ersten Absatz, das letzte endet beim letzten Absatz.
- start_s und end_s sind Zahlen in Sekunden und liegen auf Absatzgrenzen aus den Zeitmarken.
- Je nach Länge 3 bis 12 Themen. Ein Thema umfasst mehrere Absätze.
- titel: höchstens acht Wörter, sachlich, ohne Nummerierung.
- kurz: ein bis zwei Sätze darüber, was in dem Abschnitt erklärt wird.
- zusammenfassung: drei bis fünf Sätze über das ganze Video, sachlich, ohne Wertung.
- Nur Inhalte aus dem Transkript, nichts erfinden."""


def zeitmarke(sekunden: float) -> str:
    """Lesbare Zeitmarke: m:ss, ab einer Stunde h:mm:ss."""
    gesamt = max(0, int(round(sekunden)))
    stunden, rest = divmod(gesamt, 3600)
    minuten, sek = divmod(rest, 60)
    if stunden:
        return f"{stunden}:{minuten:02d}:{sek:02d}"
    return f"{minuten}:{sek:02d}"


def korrektur_nachrichten(rohtext: str) -> list[Nachricht]:
    """System- und Nutzernachricht für die Korrektur eines Blocks."""
    nutzer = f"Korrigiere den folgenden Rohtext nach den Regeln. Gib nur den korrigierten Text aus.\n\nRohtext:\n{rohtext.strip()}"
    return [Nachricht("system", SYSTEM_KORREKTUR), Nachricht("user", nutzer)]


def absatzliste(absaetze: Sequence[Zeitabsatz]) -> str:
    """Die Absätze mit Zeitmarken in Sekunden, eine Zeile je Absatz."""
    zeilen = [f"[{int(round(a.start_s))}-{int(round(a.end_s))} s] {a.text.strip()}" for a in absaetze]
    return "\n".join(zeilen)


def themen_nachrichten(absaetze: Sequence[Zeitabsatz], video_titel: str = "") -> list[Nachricht]:
    """System- und Nutzernachricht für die Themenaufschlüsselung über die Absatzliste."""
    kopf = f"Video: {video_titel.strip()}\n\n" if video_titel.strip() else ""
    nutzer = f"{kopf}Absätze:\n{absatzliste(absaetze)}\n\nGib nur das JSON-Objekt aus."
    return [Nachricht("system", SYSTEM_THEMEN), Nachricht("user", nutzer)]
