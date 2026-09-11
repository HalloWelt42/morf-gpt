# morf-gpt - Architektur

morf-gpt macht die Erklärvideos des Kanals "morf" als lokale Wissensbibliothek befragbar.
Der Weg von der Videoquelle bis zur Antwort im Chat ist ein Fließband mit sechs Stufen.
Jede Stufe ist ein austauschbarer Baustein hinter einer klaren Schnittstelle, jeder
Zwischenstand ist in der Oberfläche sichtbar und vom Nutzer bearbeitbar.

## 1. Zwei Hälften: Werkstatt und Bibliothek

| Hälfte | Braucht | Zweck |
|---|---|---|
| **Werkstatt** | Videoquelle (TubeVault-Kanal oder ein Verzeichnis mit eigenen Dateien, beides nebeneinander), Transkriptionsdienst (txt2voice-Worker mit Whisper), Sprachmodell für die Korrektur | Rohdaten beschaffen und zu Bausteinen verarbeiten |
| **Bibliothek** | Datenbank (Bausteine + Vektoren), Einbettungsanbieter, Sprachmodell für die Antwort | Suchen, auswählen, antworten |

Die Trennung ist bewusst: **sind die Daten einmal aggregiert, läuft die Bibliothek
samt Chat ohne Zugang zu den Rohdaten an einem beliebigen anderen Ort** (z. B. auf einem
Server mit Hetzner-Inferenz als Sprachmodell und lokalem bge-m3 über fastembed als
Einbettung). Die Werkstatt-Stufen bleiben dort einfach ohne Anbieter und erscheinen
nicht (Regel: nur zeigen, was geht). Die Bibliothek wird als ein Paket exportiert und
importiert (siehe Abschnitt 8).

Audiodateien gehören zur Werkstatt. Sie sind für die Bibliothek optional: fehlen sie,
gibt es keinen Abspielknopf an den Textstellen, alles andere bleibt gleich.

**Zielbild für Empfänger der fertigen Bibliothek:** Wer das Paket bekommt, hat in der
Regel wenig Hardware und keinen der Spezialdienste dieser Werkstatt (keine Videoquelle
auf dem Pi, keinen Recherche-Server). Die Bibliothek muss deshalb mit einem
OpenAI-kompatiblen Dienst mittlerer Stärke als Sprachmodell und fastembed als Einbettung
vollständig nutzbar sein: befragen, Belege lesen, Stellen pflegen. Neue Videos kommen dort
eher von lokalen Dateien als aus einer Videoquelle, und Metadaten werden auch von Hand
gepflegt. Alles darüber hinaus (Transkription, Korrektur, fremde Werkzeuge) ist Zusatz,
der zuschaltbar ist und nie Voraussetzung.

## 2. Das Fließband (Stufen je Video)

Jede Stufe trägt in der Oberfläche einen Info-Knopf, der in der Hilfe erklärt, was in
dem Schritt genau passiert und warum er wichtig ist (Anker `stufe-abgleich`,
`stufe-audio`, `stufe-transkription`, `stufe-korrektur`, `stufe-stueckelung`,
`stufe-einbettung`); dieselben Anker hängen an den Reitern der Videoansicht.

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
  die **Originaladresse** (bei TubeVault `https://youtu.be/<kennung>`, bei lokalen
  Dateien aus dem Beiblatt oder von Hand) ist ein Feld des Videos.
- **Zwei Quellenarten** hinter einer Schnittstelle (`dienste/quellen/basis.VideoQuelle`):
  `tubevault` (Kanal eines Dienstes) und `lokal` (Verzeichnis auf dem Rechner; Kennung
  aus dem relativen Pfad, Metadaten aus Beiblatt `name.json`, ffprobe und Dateiname,
  Bild `name.jpg` oder Einzelbild aus dem Film). Die Audiostufe wandelt lokale Dateien
  direkt mit ffmpeg (Bezugsweg `lokale_datei`), alles andere bleibt gleich.
- **Handpflege**: Titel, Beschreibung, Datum, Dauer, Art, Originaladresse, Kanal, Serie,
  Folge, Schlagworte und Vorschaubild lassen sich am Video von Hand setzen. Gepflegte
  Felder stehen in `videos.felder_manuell`; der Abgleich überschreibt sie nicht, bis der
  Nutzer die Handpflege aufhebt. So bleibt die Bibliothek auch ohne Quelle pflegbar.
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

## 9. Fremde Dienste und Werkzeuge

Werkzeuge sind eine Zusatzoption der Bibliothek, keine Voraussetzung: ohne angelegte
Werkzeuge fehlt der Abschnitt im Chat, und es läuft nie ein Werkzeug, das nicht ausdrücklich
je Frage oder als Vorauswahl eingeschaltet wurde. Das Paket für den Umzug enthält keine
Werkzeuge; sie werden am Zielort bei Bedarf neu angelegt.

Neben der eigenen Bibliothek kann der Chat weitere Quellen befragen. Ein **Werkzeug** ist
ein Baustein hinter der Schnittstelle `Werkzeug` (`dienste/werkzeuge/basis.py`):

```
beschreibung() -> Werkzeugbeschreibung(name, beschreibung, parameter_schema)
ausfuehren(argumente) -> Werkzeugergebnis(text, quellen[], dauer_ms)
```

Werkzeuge werden vom Nutzer in der Oberfläche angelegt (Tabelle `werkzeuge`: Name,
Typ, Beschreibung für das Modell, Konfiguration, aktiv, im Chat vorausgewählt). Typen:

| Typ | Was er anbindet | Konfiguration |
|---|---|---|
| `http_json` | Beliebiger HTTP-Dienst mit JSON-Antwort (REST) | Adresse mit Platzhalter `{frage}`, Methode, Kopfzeilen (Schlüssel geheim markierbar), Rumpf-Vorlage, Pfad zum Antworttext (z. B. `ergebnisse[].text`), Pfad zur Quelladresse, Zeitgrenze |
| `mcp` | MCP-Server (Streamable HTTP oder SSE), etwa ein Recherche-Server mit Websuche, Wikipedia oder Wetter | Adresse, Transport, Kopfzeilen; die Werkzeuge des Servers werden beim Prüfen entdeckt und einzeln freigeschaltet |

Ein MCP-Server erscheint im Chat als mehrere Werkzeuge (`server: werkzeug`), jedes
abwählbar. Das Register (`dienste/werkzeuge/register.py`) baut aus den Zeilen die
einsetzbaren Werkzeuge; neue Typen kommen als weiteres Modul dazu.

**Zwei Betriebsarten** (Einstellung `chat.werkzeugwahl`, im Chat umschaltbar):

1. **Der Nutzer wählt** (Vorgabe): in der Suchleiste stehen die aktiven Werkzeuge als
   Schalter. Vor der Antwort führt morf-gpt jedes gewählte Werkzeug aus. Braucht ein
   Werkzeug nur einen Text, bekommt es die Frage; braucht es strukturierte Argumente,
   leitet das Sprachmodell sie in einem kleinen Aufruf mit dem Parameterschema ab
   (`dienste/werkzeuge/argumente.py`). Deterministisch und ohne Modellfähigkeit zur
   Werkzeugwahl.
2. **Das Modell wählt**: die Werkzeuge gehen als Funktionsbeschreibungen mit; das
   Modell entscheidet je Runde, ob und welche es aufruft (`dienste/chat/werkzeugschleife.py`,
   höchstens `werkzeuge.max_runden` Runden), die Ergebnisse gehen zurück, am Ende wird
   die Antwort gestreamt. Kann der Anbieter keine Werkzeugaufrufe, fällt der Chat auf
   Betriebsart 1 zurück und sagt das.

In beiden Fällen werden Werkzeugergebnisse zu **Stellen** wie die Bibliothekstreffer
(Art `werkzeug`, mit Werkzeugname und Quelladresse) und im Kontext nummeriert, damit das
Modell sie mit `[n]` belegt. Jeder Aufruf steht mit Argumenten, Dauer und Ergebnis in der
Nachricht (`Nachricht.parameter.werkzeugaufrufe`) und ist in der Oberfläche einsehbar.
Geheimnisse (Kopfzeilen) sind im Verwaltungsbereich lesbar, im Protokoll maskiert.

## 9a. Hilfe: freischwebendes Fenster mit Themen als Markdown

Die Hilfe folgt dem Muster der Demo `HalloWelt42/hilfe-fenster-demo`: ein Fenster, das frei
über der Seite liegt und sich ziehen, in der Größe ändern, minimieren und maximieren lässt.
Lage, Größe, Zustand und zuletzt gezeigtes Thema werden im Browser gemerkt; geraten die
Bedienelemente aus dem Bild (Sichtschutz), schaltet das Fenster von selbst auf Vollbild.

- **Themen** sind Markdown-Dateien unter `frontend/src/lib/hilfe/themen/<anker>.md` mit
  Kopf (titel, unterzeile, kategorie, symbol, stichworte); `hilfe/themen.ts` liest sie beim
  Bauen ein (Vite `import.meta.glob`), rendert mit marked und führt das HTML durch
  DOMPurify. Ein neues Thema ist eine neue Datei; der Dateiname ist der Anker.
- **Zustand** lebt in `stores/hilfe.svelte.ts` (eine Instanz): offen, Thema, Suche, Bereich,
  Trefferliste, Lage und Größe.
- **Volltextsuche** über alle Themen oder nur im gezeigten, mit Trefferzähler (etwa 3/12),
  Vor und Zurück per Pfeilen, Eingabe und Umschalt + Eingabe; in der Suche über alle Themen
  führt der nächste Treffer ins nächste Thema, die Themenliste zeigt die Trefferzahl je Thema.
  Fundstellen werden im Text markiert, die aktive in die Mitte geholt.
- **Hilfepunkte** (`InfoKnopf`, der Mini-i-Knopf) öffnen genau das passende Thema; mit
  `finde` wird dort gleich ein Begriff gesucht und markiert (Auffinden). Jede Fließbandstufe
  und jeder Reiter der Videoansicht trägt einen solchen Punkt.

## 10. Technik

Beim Start bringt das Backend das Datenbankschema selbst auf den neuesten Stand
(`db/migration.py`, Alembic `upgrade head`, abschaltbar über
`MORF_MIGRATION_BEIM_START`), und zwar vor dem Auftragsläufer. Grund: uvicorn lädt nach
einer Modelländerung sofort neu; ohne diesen Schritt trafen Aufträge auf Spalten, die in
der Datenbank noch fehlten, und verbrauchten ihre Versuche.

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
