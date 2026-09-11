# morf-gpt - Architektur

morf-gpt macht die Erklärvideos des Kanals "morf" als lokale Wissensbibliothek befragbar.
Der Weg von der Videoquelle bis zur Antwort im Chat ist ein Fließband mit sechs Stufen.
Jede Stufe ist ein austauschbarer Baustein hinter einer klaren Schnittstelle, jeder
Zwischenstand ist in der Oberfläche sichtbar und vom Nutzer bearbeitbar.

## 1. Zwei Hälften: Werkstatt und Bibliothek

| Hälfte | Braucht | Zweck |
|---|---|---|
| **Werkstatt** | Videoquelle (TubeVault auf dem Pi), Transkriptionsdienst (txt2voice-Worker mit Whisper), Sprachmodell für die Korrektur | Rohdaten beschaffen und zu Bausteinen verarbeiten |
| **Bibliothek** | Datenbank (Bausteine + Vektoren), Einbettungsanbieter, Sprachmodell für die Antwort | Suchen, auswählen, antworten |

Die Trennung ist bewusst: **sind die Daten einmal aggregiert, läuft die Bibliothek
samt Chat ohne Zugang zu den Rohdaten an einem beliebigen anderen Ort** (z. B. auf einem
Server mit Hetzner-Inferenz als Sprachmodell und lokalem bge-m3 über fastembed als
Einbettung). Die Werkstatt-Stufen bleiben dort einfach ohne Anbieter und erscheinen
nicht (Regel: nur zeigen, was geht). Die Bibliothek wird als ein Paket exportiert und
importiert (siehe Abschnitt 8).

Audiodateien gehören zur Werkstatt. Sie sind für die Bibliothek optional: fehlen sie,
gibt es keinen Abspielknopf an den Textstellen, alles andere bleibt gleich.

## 2. Das Fließband (Stufen je Video)

```
entdeckt -> audio -> transkribiert -> korrigiert -> gestueckelt -> eingebettet
```

| Stufe | Auftragsart | Baustein (Schnittstelle) | Standard-Umsetzung |
|---|---|---|---|
| Quelle abgleichen | `quelle_abgleich` | `VideoQuelle` | TubeVault-REST (Kanalvideos, Dauer, Downloadstand) |
| Audio beschaffen | `audio` | `AudioBezug` | Videostrom von TubeVault holen, lokal mit ffmpeg zu Mono-AAC wandeln; alternativ Extraktion auf dem Pi |
| Transkribieren | `transkription` | `TranskriptionsEngine` | txt2voice-Worker `POST /stt` (Whisper Large V3, MLX), ohne Sprechertrennung |
| Korrigieren | `korrektur` | `KorrekturEngine` | Sprachmodell (lokal 80B oder Hetzner) je Zeitblock, mit Abweichungswächter |
| Stückeln | `stueckelung` | `Stueckler` | Absatzbewusst, große Stücke mit sauberer Überlappung an Satzgrenzen |
| Einbetten | `einbettung` | `EinbettungsAnbieter` | LM Studio `/v1/embeddings` mit `text-embedding-bge-m3` |

Regeln des Fließbands:

- Ein Auftrag (`auftraege`) bezieht sich auf genau ein Video und eine Stufe. Zustände:
  `wartend`, `laeuft`, `fertig`, `fehler`, `pausiert`, `abgebrochen`.
- Der Auftragsläufer (`dienste/auftraege/laeufer.py`) ist eine Schleife im Backend. Je
  Stufe gilt eine eigene Parallelität (Einstellung, sichtbar): Audio 2, Transkription 1
  (die GPU ist geteilt), Korrektur 1, Stückelung 4, Einbettung 1.
- Jede Stufe ist einzeln pausierbar. "Automatisch weiterreichen" (Einstellung je Stufe)
  legt nach Abschluss den Auftrag der nächsten Stufe an.
- Reihenfolge: Einstellung "Serie zuerst" (mmM vor allem anderen), dann nach Datum.
  Einzelne Videos lassen sich vorziehen (Priorität).
- Fehler werden je Auftrag mit Meldung gespeichert; Wiederholung mit Zähler. Nichts
  bricht das Band, ein hängender Auftrag wird nach einer sichtbaren Frist als Fehler
  markiert.
- Fortschritt und Protokoll je Auftrag laufen als Ereignisstrom (SSE) in die Oberfläche.

## 3. Datenmodell (PostgreSQL mit pgvector, Docker)

Alle Kennungen sind UUIDs (hex). Zeiten in UTC. Tabellen und Felder tragen deutsche
ASCII-Namen.

| Tabelle | Inhalt |
|---|---|
| `quellen` | Videoquelle: Typ, Basisadresse, Kanalkennung, Kanalname, Filterregeln (Mindestdauer) |
| `videos` | Ein Video der Quelle: externe Kennung, Originaladresse (YouTube), Titel, Beschreibung, Datum, Dauer, Typ, Aufrufe, Schlagworte, Serie und Folgennummer (aus dem Titel, z. B. `mmM#377`), Vorschaubild (lokal gespeichert) und Original-Metadaten der Quelle als JSON, `ausgewaehlt` (im Umfang), `stufe` (höchste fertige Stufe), Fehlertext |
| `audios` | Audiodatei je Video: Pfad, Format, Dauer, Größe, Bezugsweg |
| `transkripte` | Rohtranskript: Engine, Modell, Sprache, Volltext, Segmente (JSON mit Start, Ende, Text, Wortzeiten) |
| `korrekturen` | Korrigierter Text: Absätze (JSON mit Start, Ende, Text), Themenaufschlüsselung (JSON mit Titel, Start, Ende, Kurzfassung), Kurzzusammenfassung des Videos, Ähnlichkeit zum Rohtext, Anzahl verworfener Blöcke, Anbieter und Modell |
| `chunks` | Textstücke: Reihenfolge je Video, Text, Zeitfenster, Zeichen, Thema, Überlappung vor/nach in Zeichen |
| `einbettungen` | Vektor je Chunk und Modell: Anbieter, Modell, Dimension, `vector(1024)` |
| `auftraege` | Fließband-Aufträge (siehe oben) |
| `auftrag_protokoll` | Protokollzeilen je Auftrag, seitenweise abrufbar |
| `einstellungen` | Schlüssel/Wert (JSON); die Beschreibung, Grenzen und Einheit je Schlüssel stehen im Code-Register `dienste/einstellungen/register.py` |
| `anbieter` | Sprachmodell- und Einbettungsanbieter: Typ (`lmstudio`, `openai_kompatibel`, `fastembed`), Basisadresse, Schlüssel, Modell, Rolle (`chat`, `korrektur`, `einbettung`), aktiv |
| `unterhaltungen` | Chat-Gespräche mit den zuletzt benutzten Suchparametern |
| `nachrichten` | Nachrichten mit Rolle, Inhalt, benutzten Textstellen (Chunk-Kennungen, Werte), Parametern, Modell, Dauer |

Warum eine Datenbank für alles: die Bibliothek ist damit **ein** Paket (Metadaten,
Texte, Vektoren), umziehbar mit einem Export. pgvector trägt die ~35.000 Vektoren
(664 Videos, ~50 Stücke je Video) mühelos; ein HNSW-Index reicht.

Die Vektordimension ist ein Konfigurationswert (`EINBETTUNG_DIMENSION`, Standard 1024
für bge-m3). Ein Modell mit anderer Dimension braucht eine Migration; die Oberfläche
zeigt die Dimension je Anbieter, damit der Nutzer den Unterschied sieht.

## 4. Anbieter (Sprachmodelle und Einbettungen)

Schnittstellen in `dienste/anbieter/`:

- `SprachmodellAnbieter.antworte(nachrichten, parameter)` und `.streame(...)`
- `EinbettungsAnbieter.einbetten(texte) -> Vektoren`
- Umsetzungen: `lmstudio` (OpenAI-kompatibel auf `:1234`, Modellzustand über
  `/api/v0/models`), `openai_kompatibel` (z. B. Hetzner `https://inference.hetzner.com/api/v1`
  mit Schlüssel), `fastembed` (lokale ONNX-Einbettung, kein Dienst nötig).
- Der Nutzer wählt je Rolle (Chat, Korrektur, Einbettung) den aktiven Anbieter in der
  Oberfläche. Nichts ist fest verdrahtet; Schlüssel sind im Verwaltungsbereich lesbar
  (Auge deckt auf), im Protokoll maskiert.
- Ein Einbettungswechsel erzeugt einen neuen Einbettungslauf (je Chunk und Modell ein
  Vektor); die Suche fragt immer mit demselben Modell, das den Index gebaut hat.

## 5. Korrektur ohne Sinnverlust

Das Sprachmodell darf Form verbessern, nicht Inhalt. Darum:

1. Der Rohtext wird in Zeitblöcke von etwa 2.500 Zeichen an Segmentgrenzen geschnitten.
2. Je Block: Zeichensetzung, Groß-/Kleinschreibung, offensichtliche Hörfehler, Absätze.
   Keine Umformulierung, keine Kürzung, keine Ergänzung. Der Prompt zeigt das Ziel mit
   Beispielen.
3. **Abweichungswächter**: die Ähnlichkeit (Zeichen-Diff) zwischen Roh und korrigiert muss
   über einer sichtbaren Schwelle liegen (Standard 0,80), sonst bleibt der Rohtext des
   Blocks stehen und der Block wird als "verworfen" gezählt.
4. Nach den Blöcken ein zweiter Aufruf über die Absatzliste: Themenaufschlüsselung
   (Abschnittstitel mit Zeitfenster und Kurzfassung) und eine Kurzzusammenfassung des
   Videos. Diese Aufschlüsselung liefert den Stücken ihren Themenkontext und dem Chat
   eine Videoebene.

Die Blöcke behalten ihre Zeitfenster; so bleibt jede Textstelle zum Audio springbar.

Alles, was aus einem Sprachmodell kommt (Korrektur, Themen, Chat-Antworten), läuft durch
`dienste/text.py`: typografische Sonderzeichen werden gerade gesetzt, und Zeichen fremder
Schriften (chinesisch, kyrillisch, arabisch ...) werden entfernt. Niedrig quantisierte
Modelle streuen solche Zeichen gelegentlich ein; die Bibliothek ist deutsch.

## 6. Stückelung

- Eingabe: die korrigierten Absätze mit Zeitfenstern (Fallback: Rohsegmente).
- Zielgröße groß (Standard 3.000 Zeichen, einstellbar 800 bis 8.000), Überlappung
  Standard 400 Zeichen, immer an Satzgrenzen: das Ende eines Stücks wird um ganze Sätze
  bis zur Überlappungsgröße im nächsten Stück wiederholt. Kein Schnitt im Wort.
- Jeder Chunk kennt: Video, Reihenfolge, Zeitfenster, Thema (aus der Aufschlüsselung),
  Überlappungslänge vor und nach. Der Einbettungstext wird mit Kontextkopf gebildet:
  `Video: <Titel> | Thema: <Thema>\n<Text>`.
- Der Nutzer kann Stücke ansehen, Text bearbeiten, zusammenlegen, teilen, neu stückeln
  (Video-weit) und neu einbetten.

## 7. Suche und Chat

Die Suche hat zwei vom Nutzer gesteuerte Achsen, sichtbar als feste Leiste im Chat:

- **Breite**: Anzahl Treffer (1 bis 50), Nachbarstücke je Treffer (0 bis 3), höchstens
  N Stücke je Video (Vielfalt).
- **Genauigkeit**: Mindestähnlichkeit (Cosinus 0 bis 1), Neu-Bewertung (aus, lokaler
  Cross-Encoder, Sprachmodell).
- Filter: Serie, Zeitraum, einzelne Videos.

Ablauf einer Frage:

1. Frage einbetten (gleiches Modell wie der Index).
2. pgvector-Cosinus-Suche mit Filtern, Mindestähnlichkeit, Vielfaltsgrenze.
3. Optional Neu-Bewertung, dann Nachbarn ergänzen (an Überlappungen entdoppelt).
4. Die ausgewählten Stellen erscheinen im Chat **vor** der Antwort (mit Wert, Video,
   Zeitfenster, Sprung ins Audio). Der Nutzer kann Stellen abwählen und neu antworten
   lassen.
5. Das Sprachmodell fasst ausschließlich aus den ausgewählten Stellen zusammen und belegt
   mit `[n]`; die Oberfläche macht daraus Mini-Links auf die Stelle.

Alles streamt über SSE (`treffer`, `delta`, `fertig`, `fehler`). Nachrichten speichern
die benutzten Stellen und Parameter, damit ein Gespräch später nachvollziehbar bleibt.

## 7a. Herkunft und Wiederauffindbarkeit

Jede Textstelle muss zur Originalquelle zurückführen. Darum gilt:

- Beim Abgleich werden die **originalen Metadaten** der Quelle vollständig übernommen
  (Titel, Beschreibung, Datum, Dauer, Aufrufe, Schlagworte, Kanal) und zusätzlich roh
  als JSON abgelegt; das **Vorschaubild** wird lokal gespeichert (`data/miniaturen/`),
  die **YouTube-Adresse** (`https://youtu.be/<kennung>`) ist ein Feld des Videos.
- Chunks, Absätze und Segmente tragen Zeitfenster. Jede Fundstelle im Chat und in der
  Bibliothek zeigt Vorschaubild, Titel, Folge und Zeitfenster und bietet zwei Sprünge:
  **Abspielen im eigenen Spieler** ab der Sekunde und **Öffnen bei YouTube** mit Zeitmarke
  (`?t=<sekunden>`).
- Der **Audiospieler** ist ein fester Bestandteil der Oberfläche (zweizeilige Leiste am
  unteren Rand, bleibt über Ansichtswechsel bestehen): oben Titel, aktuelles Thema,
  Knöpfe (5 und 30 Sekunden vor und zurück), Zeit und Tempo (0,8 bis 2,0); unten die
  Zeitleiste in voller Breite mit den Themen als Abschnitte. Der aktuell gesprochene
  Absatz wird in Transkript und Themenliste hervorgehoben. Das Backend liefert Audio mit
  HTTP-Range, damit Sprünge sofort greifen.
- Vorschaubilder und Metadaten sind Teil des Bibliothekspakets (Abschnitt 8).

## 8. Umzug der Bibliothek

`POST /api/export/bibliothek` schreibt ein Paket (`morf-gpt-bibliothek-<datum>.tar.gz`)
mit JSONL je Tabelle (Videos, Korrekturen, Chunks, Einbettungen) plus Manifest
(Version, Einbettungsmodell, Dimension, Zähler) sowie den Vorschaubildern.
`POST /api/import/bibliothek` liest es in eine leere oder bestehende Datenbank (Abgleich
über Video-Kennung). Audio wird nicht mitgenommen (Sprung zu YouTube bleibt immer
möglich); Transkripte optional.

## 9. Erweiterung: Fremde Dienste und Werkzeuge

Vorbereitet, noch ohne Oberfläche (kein toter Regler): das Anbieter-Register
(`dienste/anbieter/register.py`) nimmt weitere Typen auf; die Chat-Orchestrierung ist so
geschnitten, dass Werkzeuge (Zeit, Web, fremde Suchdienste) als weitere Quellen vor der
Antwort eingehängt werden können (`dienste/chat/orchestrierung.py`, Punkt "Quellen
sammeln"). Sobald eine erste Umsetzung existiert, bekommt sie ihre Verwaltung in der
Oberfläche.

## 10. Technik

- Backend: Python 3.12, FastAPI, SQLAlchemy 2 (async, asyncpg), Alembic, Pydantic v2,
  httpx. Start über `start.sh` (Datenbank per Docker Compose, Backend, Frontend).
- Frontend: Svelte 5 (Runes, TypeScript), Vite, Bootstrap 5 (npm, SCSS-Thema: kantig,
  Radius 0), Barlow, Font Awesome. Große Schrift für Antworten und Dialoge. Kopf bleibt
  stehen, Listen rollen in eigenen Feldern, lange Listen seitenweise.
- Version: einzige Wahrheit `version.json`, Pre-Commit-Hook zählt hoch, Backend liest sie,
  Oberfläche zeigt sie im Fuß.
- Hilfe: freischwebendes, verschiebbares, durchsuchbares Fenster mit Sprungmarken; an
  jedem erklärungsbedürftigen Bedienelement ein Mini-i-Knopf.
- Mockups (`mockups/`) sind echtes HTML mit demselben Stil und bleiben der verbindliche
  Leitfaden: Layoutänderungen zuerst dort, dann im Svelte-Code.

## 11. Ports und Pfade

| Dienst | Adresse |
|---|---|
| Backend | `http://127.0.0.1:8460` (per `MORF_BACKEND_PORT`) |
| Frontend (Vite) | `http://127.0.0.1:5460` |
| PostgreSQL (Docker) | `127.0.0.1:5462`, Daten als Bind-Mount unter `data/postgres` |
| TubeVault (Quelle) | `http://192.168.178.49:8031` (Backend-API) |
| txt2voice-Worker (Whisper) | `http://127.0.0.1:10033` |
| LM Studio | `http://127.0.0.1:1234` |

Audio liegt unter `data/audio/<video_id>.m4a`, Vorschaubilder unter `data/miniaturen/<video_id>.jpg`, Exporte unter `data/export/`.
