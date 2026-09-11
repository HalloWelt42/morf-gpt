"""Stückelung: aus Absätzen mit Zeitfenstern werden Stücke aus ganzen Sätzen.

Reine Rechenarbeit ohne Datenbank. Eingabe sind die korrigierten Absätze (Fallback:
Rohsegmente des Transkripts) und die Themenaufschlüsselung, Ausgabe sind Stücke mit
Text, Zeitfenster, Thema und Überlappung (siehe docs/ARCHITEKTUR.md, Abschnitt 6).

Regeln:
- Ein Stück besteht aus ganzen Sätzen bis zur Zielgröße. Es wird nie im Wort
  geschnitten; nur ein einzelner Satz, der die Zielgröße sprengt, wird an
  Leerzeichen gebrochen.
- Das nächste Stück beginnt mit den letzten ganzen Sätzen des vorigen, bis die
  Überlappungsgröße erreicht ist. Das vorige Stück merkt sich diese Länge als
  ueberlappung_nach, das nächste als ueberlappung_vor.
- Das Zeitfenster eines Stücks umfasst alle beteiligten Absätze.
- Das Thema ist der Titel des Themas, in dessen Zeitfenster die Mitte des Stücks liegt.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

# --------------------------------------------------------------------------- Datentypen


@dataclass(slots=True, frozen=True)
class Absatz:
    """Ein Absatz mit Zeitfenster, wie ihn die Korrektur liefert."""

    text: str
    start_s: float
    end_s: float


@dataclass(slots=True, frozen=True)
class Thema:
    """Ein Abschnitt der Themenaufschlüsselung."""

    titel: str
    start_s: float
    end_s: float


@dataclass(slots=True, frozen=True)
class Satz:
    """Ein ganzer Satz mit dem Zeitfenster seines Absatzes."""

    text: str
    absatz_nr: int
    start_s: float
    end_s: float


@dataclass(slots=True)
class Stueck:
    """Ein fertiges Stück. Die Reihenfolge zählt je Video ab 1."""

    reihenfolge: int
    text: str
    start_s: float
    end_s: float
    zeichen: int
    thema: str
    ueberlappung_vor: int
    ueberlappung_nach: int


# --------------------------------------------------------------------------- Eingabe wandeln


def _zahl(roh: dict[str, Any], *schluessel: str) -> float:
    """Erster vorhandener Zahlenwert unter den gegebenen Schlüsseln, sonst 0."""
    for s in schluessel:
        wert = roh.get(s)
        if wert is not None:
            return float(wert)
    return 0.0


def absaetze_aus_dicts(rohe: Iterable[dict[str, Any]]) -> list[Absatz]:
    """Absätze aus den JSON-Zeilen der Korrektur. Leere Absätze werden übergangen.

    Verstanden werden die Schlüssel start_s/end_s und start/end.
    """
    aus: list[Absatz] = []
    for roh in rohe:
        text = str(roh.get("text") or "").strip()
        if not text:
            continue
        aus.append(Absatz(text=text, start_s=_zahl(roh, "start_s", "start"), end_s=_zahl(roh, "end_s", "end")))
    return aus


def themen_aus_dicts(rohe: Iterable[dict[str, Any]]) -> list[Thema]:
    """Themen aus der Aufschlüsselung der Korrektur. Themen ohne Titel werden übergangen."""
    aus: list[Thema] = []
    for roh in rohe:
        titel = str(roh.get("titel") or "").strip()
        if not titel:
            continue
        aus.append(Thema(titel=titel, start_s=_zahl(roh, "start_s", "start"), end_s=_zahl(roh, "end_s", "end")))
    return aus


def absaetze_aus_segmenten(segmente: Iterable[dict[str, Any]], hoechstens_zeichen: int) -> list[Absatz]:
    """Rohsegmente des Transkripts zu Absätzen bündeln (Fallback ohne Korrektur).

    Segmente enden oft mitten im Satz. Darum werden aufeinanderfolgende Segmente zu
    einem Absatz zusammengefasst, bis ein Segment mit einem Satzende schließt oder die
    Grenze in Zeichen erreicht ist. Das Zeitfenster reicht vom ersten bis zum letzten
    beteiligten Segment.
    """
    aus: list[Absatz] = []
    texte: list[str] = []
    start = 0.0
    ende = 0.0
    laenge = 0
    for roh in segmente:
        text = _normalisieren(str(roh.get("text") or ""))
        if not text:
            continue
        if not texte:
            start = _zahl(roh, "start_s", "start")
        texte.append(text)
        laenge += len(text) + 1
        ende = _zahl(roh, "end_s", "end")
        if _endet_mit_satzende(text) or laenge >= hoechstens_zeichen:
            aus.append(Absatz(text=" ".join(texte), start_s=start, end_s=ende))
            texte = []
            laenge = 0
    if texte:
        aus.append(Absatz(text=" ".join(texte), start_s=start, end_s=ende))
    return aus


# --------------------------------------------------------------------------- Satzteiler

# Schließende Anführungszeichen und Klammern, die noch zum Satz gehören (typografische
# Zeichen als Escapes, damit die Quelle nur gerade Zeichen enthält).
_SCHLUSS = "\"'»«“”’)\\]"
# Öffnende Zeichen, mit denen ein neuer Satz beginnen darf.
_AUFTAKT = "\"'„»«“‘(\\["

# Satzende-Kandidat: Satzzeichen (plus Schlusszeichen), Leerraum, dann ein Großbuchstabe
# oder eine Ziffer (gegebenenfalls hinter einem öffnenden Zeichen).
_SATZENDE = re.compile(r"([.!?…]+[" + _SCHLUSS + r"]*)(\s+)(?=[" + _AUFTAKT + r"]?[A-ZÄÖÜ0-9])")
_LETZTES_WORT = re.compile(r"(\S+)$")
_LETZTE_ZWEI_WOERTER = re.compile(r"(\S+ \S+)$")
_LEERRAUM = re.compile(r"\s+")

# Abkürzungen, nach deren Punkt kein Satz endet (klein geschrieben, mit Punkt).
_ABKUERZUNGEN: frozenset[str] = frozenset(
    {
        "z. b.",
        "z.b.",
        "bzw.",
        "nr.",
        "dr.",
        "prof.",
        "usw.",
        "etc.",
        "ca.",
        "vgl.",
        "u. a.",
        "u.a.",
        "d. h.",
        "d.h.",
        "evtl.",
        "ggf.",
        "inkl.",
        "exkl.",
        "max.",
        "min.",
        "sog.",
        "st.",
        "str.",
        "tel.",
        "abs.",
        "art.",
        "bd.",
        "jh.",
        "mio.",
        "mrd.",
        "o. ä.",
        "o.ä.",
        "u. u.",
        "u.u.",
        "s. o.",
        "s.o.",
        "s. u.",
        "s.u.",
        "v. a.",
        "v.a.",
        "kap.",
        "abb.",
        "bsp.",
        "geb.",
        "gest.",
        "hr.",
        "fr.",
        "bzgl.",
        "zzgl.",
        "allg.",
        "ev.",
        "ehem.",
        "engl.",
        "dt.",
        "frz.",
        "lat.",
        "ugs.",
        "urspr.",
        "vs.",
        "no.",
        "jr.",
        "sen.",
        "mr.",
        "mrs.",
        "ms.",
        "co.",
        "ltd.",
        "inc.",
        "std.",
        "sek.",
        "mind.",
        "hrsg.",
        "verf.",
        "jhd.",
        "n. chr.",
        "v. chr.",
        "n.chr.",
        "v.chr.",
    }
)


def _normalisieren(text: str) -> str:
    """Leerraum (auch Zeilenumbrüche) zu einzelnen Leerzeichen, Ränder abschneiden."""
    return _LEERRAUM.sub(" ", text).strip()


def _endet_mit_satzende(text: str) -> bool:
    return bool(re.search(r"[.!?…][" + _SCHLUSS + r"]*$", text))


def _ist_satzende(text: str, treffer: re.Match[str]) -> bool:
    """Entscheidet, ob der Kandidat wirklich ein Satzende ist (keine Abkürzung, keine Ordnungszahl)."""
    zeichen = treffer.group(1)
    if not zeichen.startswith("."):
        return True
    davor = text[: treffer.start(1)]
    wort_treffer = _LETZTES_WORT.search(davor)
    if wort_treffer is None:
        return True
    wort = wort_treffer.group(1)
    if len(wort) == 1 and wort.isalpha():
        return False  # Initial ("A. Müller") oder erster Teil von "u. a."
    if wort.isdigit() and len(wort) <= 2:
        return False  # Ordnungszahl wie "3. Mai" oder "20. Jahrhundert"
    if (wort + ".").lower() in _ABKUERZUNGEN:
        return False
    zwei = _LETZTE_ZWEI_WOERTER.search(davor)
    if zwei is not None and (zwei.group(1) + ".").lower() in _ABKUERZUNGEN:
        return False
    return True


def saetze_teilen(text: str) -> list[str]:
    """Teilt einen Text in ganze Sätze. Nie innerhalb eines Wortes.

    Satzenden sind Punkt, Ausrufezeichen, Fragezeichen oder Auslassungspunkte, gefolgt
    von Leerraum und einem Großbuchstaben oder einer Ziffer. Abkürzungen (z. B., bzw.,
    Nr.), Initialen und Ordnungszahlen beenden keinen Satz.
    """
    sauber = _normalisieren(text)
    if not sauber:
        return []
    saetze: list[str] = []
    anfang = 0
    for treffer in _SATZENDE.finditer(sauber):
        if not _ist_satzende(sauber, treffer):
            continue
        satz = sauber[anfang : treffer.end(1)].strip()
        if satz:
            saetze.append(satz)
        anfang = treffer.end()
    rest = sauber[anfang:].strip()
    if rest:
        saetze.append(rest)
    return saetze


def an_leerraum_brechen(text: str, hoechstens_zeichen: int) -> list[str]:
    """Bricht einen zu langen Satz an Leerzeichen in Teile bis zur Grenze. Nie im Wort.

    Findet sich vor der Grenze kein Leerzeichen, wird beim nächsten dahinter gebrochen;
    ein einzelnes Wort bleibt immer ganz.
    """
    if hoechstens_zeichen < 1:
        raise ValueError("Die Grenze zum Brechen langer Sätze muss mindestens 1 Zeichen sein")
    teile: list[str] = []
    rest = text.strip()
    while len(rest) > hoechstens_zeichen:
        schnitt = rest.rfind(" ", 0, hoechstens_zeichen + 1)
        if schnitt <= 0:
            schnitt = rest.find(" ", hoechstens_zeichen)
        if schnitt <= 0:
            break
        teile.append(rest[:schnitt].rstrip())
        rest = rest[schnitt:].lstrip()
    if rest:
        teile.append(rest)
    return teile


def saetze_sammeln(absaetze: Sequence[Absatz], hoechstens_zeichen: int) -> list[Satz]:
    """Alle Sätze aller Absätze in Reihenfolge, jeder mit dem Zeitfenster seines Absatzes."""
    aus: list[Satz] = []
    for nr, absatz in enumerate(absaetze):
        for satz in saetze_teilen(absatz.text):
            for teil in an_leerraum_brechen(satz, hoechstens_zeichen):
                aus.append(Satz(text=teil, absatz_nr=nr, start_s=absatz.start_s, end_s=absatz.end_s))
    return aus


# --------------------------------------------------------------------------- Stücke bilden


def _trenner(vorher: Satz, nachher: Satz) -> str:
    """Sätze desselben Absatzes trennt ein Leerzeichen, Absätze eine Leerzeile."""
    return " " if vorher.absatz_nr == nachher.absatz_nr else "\n\n"


def text_verbinden(saetze: Sequence[Satz]) -> str:
    teile: list[str] = []
    for i, satz in enumerate(saetze):
        if i > 0:
            teile.append(_trenner(saetze[i - 1], satz))
        teile.append(satz.text)
    return "".join(teile)


def _laenge(saetze: Sequence[Satz]) -> int:
    return len(text_verbinden(saetze))


@dataclass(slots=True)
class _Rohstueck:
    saetze: list[Satz]
    ueberlappung_vor: int
    ueberlappung_nach: int


def _ueberlappung_waehlen(neue: Sequence[Satz], ueberlappung_zeichen: int) -> list[Satz]:
    """Die letzten ganzen Sätze eines Stücks, die zusammen in die Überlappung passen.

    Nur Sätze, die in diesem Stück neu waren, kommen infrage, und der erste neue Satz
    nie: so trägt jedes Stück mindestens einen Satz, der im nächsten nicht wiederholt
    wird, und die Stückelung kommt immer voran.
    """
    if ueberlappung_zeichen <= 0 or len(neue) < 2:
        return []
    gewaehlt: list[Satz] = []
    for satz in reversed(neue[1:]):
        probe = [satz, *gewaehlt]
        if _laenge(probe) > ueberlappung_zeichen:
            break
        gewaehlt = probe
    return gewaehlt


def _stuecke_bilden(saetze: Sequence[Satz], ziel_zeichen: int, ueberlappung_zeichen: int) -> list[_Rohstueck]:
    stuecke: list[_Rohstueck] = []
    uebertrag: list[Satz] = []
    i = 0
    while i < len(saetze):
        inhalt: list[Satz] = list(uebertrag)
        neue: list[Satz] = []
        laenge = _laenge(inhalt)
        while i < len(saetze):
            satz = saetze[i]
            zusatz = len(satz.text) if not inhalt else len(_trenner(inhalt[-1], satz)) + len(satz.text)
            if neue and laenge + zusatz > ziel_zeichen:
                break
            inhalt.append(satz)
            neue.append(satz)
            laenge += zusatz
            i += 1
        ueberlappung_vor = _laenge(uebertrag)
        uebertrag = _ueberlappung_waehlen(neue, ueberlappung_zeichen)
        stuecke.append(_Rohstueck(saetze=inhalt, ueberlappung_vor=ueberlappung_vor, ueberlappung_nach=_laenge(uebertrag)))
    if stuecke:
        stuecke[-1].ueberlappung_nach = 0  # nach dem letzten Stück kommt nichts mehr
    return stuecke


def thema_fuer_zeit(themen: Sequence[Thema], zeit_s: float) -> str:
    """Titel des Themas, in dessen Zeitfenster die Zeit liegt.

    Liegt die Zeit in einer Lücke zwischen Themen, gilt das zuletzt begonnene Thema.
    Ohne passendes Thema bleibt der Titel leer.
    """
    for thema in themen:
        if thema.start_s <= zeit_s <= thema.end_s:
            return thema.titel
    begonnene = [t for t in themen if t.start_s <= zeit_s]
    if not begonnene:
        return ""
    return max(begonnene, key=lambda t: t.start_s).titel


def _stueck_bauen(reihenfolge: int, roh: _Rohstueck, themen: Sequence[Thema]) -> Stueck:
    text = text_verbinden(roh.saetze)
    start_s = min(s.start_s for s in roh.saetze)
    end_s = max(s.end_s for s in roh.saetze)
    mitte = (start_s + end_s) / 2
    return Stueck(
        reihenfolge=reihenfolge,
        text=text,
        start_s=start_s,
        end_s=end_s,
        zeichen=len(text),
        thema=thema_fuer_zeit(themen, mitte),
        ueberlappung_vor=roh.ueberlappung_vor,
        ueberlappung_nach=roh.ueberlappung_nach,
    )


def _grenzen_pruefen(ziel_zeichen: int, ueberlappung_zeichen: int) -> None:
    if ziel_zeichen < 1:
        raise ValueError("Die Zielgröße eines Stücks muss mindestens 1 Zeichen sein")
    if ueberlappung_zeichen < 0:
        raise ValueError("Die Überlappung darf nicht negativ sein")


def stueckeln(absaetze: Sequence[Absatz], themen: Sequence[Thema], ziel_zeichen: int, ueberlappung_zeichen: int) -> list[Stueck]:
    """Bildet aus Absätzen Stücke aus ganzen Sätzen mit Überlappung, Zeitfenster und Thema."""
    _grenzen_pruefen(ziel_zeichen, ueberlappung_zeichen)
    saetze = saetze_sammeln(absaetze, ziel_zeichen)
    rohe = _stuecke_bilden(saetze, ziel_zeichen, ueberlappung_zeichen)
    return [_stueck_bauen(nr, roh, themen) for nr, roh in enumerate(rohe, start=1)]
