---
titel: Begriffe
unterzeile: Die Fachwörter der Anwendung, kurz und ohne Vorwissen erklärt.
kategorie: Anfang
symbol: fa-book-open
stichworte: glossar, begriffe, vektor, einbettung, token, temperatur, cross-encoder, mcp, json, stück, chunk, whisper, transkript, kontext, stapel, instanz, arbeiter
---

Wo ein Fachwort in der Oberfläche auftaucht, steht es hier. Die Erklärungen sind bewusst kurz; der Zusammenhang steht im jeweiligen Thema.

## Bibliothek und Suche

- Stück: Ein zusammenhängender Textabschnitt eines Videos oder Kapitels, meist einige hundert bis tausend Zeichen, mit Zeitfenster oder Kapitel und Thema. Die Suche findet Stücke, nicht ganze Videos.
- Einbettung: Die Übersetzung eines Textes in eine lange Zahlenreihe (den Vektor), die seine Bedeutung beschreibt. Texte mit ähnlicher Bedeutung bekommen ähnliche Zahlenreihen, egal welche Wörter sie benutzen. Das macht die Suche nach Sinn statt nach Wörtern möglich.
- Vektor: Diese Zahlenreihe. Bei dem verwendeten Modell hat sie 1024 Zahlen (Dimensionen). Vektorraum: alle Vektoren zusammen; "im selben Vektorraum" heißt, Videos und Dokumente sind mit demselben Modell eingebettet und darum vergleichbar.
- Ähnlichkeit: Ein Wert zwischen 0 und 1, wie nah der Vektor einer Stelle dem Vektor der Frage kommt. 1 wäre gleiche Bedeutung.
- Neu-Bewertung: Ein zweiter Durchgang, der die gefundenen Kandidaten genauer ordnet. Cross-Encoder: ein kleines lokales Modell liest Frage und Kandidat gemeinsam und bewertet, wie gut sie zusammenpassen; das ist genauer als der Vektorvergleich und dauert etwa eine Sekunde. Alternativ bewertet das Sprachmodell selbst (am genauesten, langsam).
- Index: Eine Datenstruktur in der Datenbank, die den Vektorvergleich schnell macht, ohne jede Stelle einzeln zu prüfen.

## Sprachmodell und Chat

- Sprachmodell: Das Modell, das die Antworten schreibt und die Transkripte korrigiert (lokal in LM Studio oder bei einem Anbieter im Netz).
- Token: Die Einheit, in der ein Sprachmodell Text zählt: ein Wortstück, im Deutschen etwa drei Viertel eines Wortes. Eine Antwort von 4000 Tokens sind grob 3000 Wörter.
- Temperatur: Wie frei das Modell formuliert. 0 heißt immer die wahrscheinlichste Fortsetzung, also nüchtern und wiederholbar; höhere Werte erlauben freiere, wechselnde Formulierungen.
- Kontext: Alles, was das Modell für eine Antwort zu lesen bekommt: die Frage, die Stellen, die Zusammenfassungen und die letzten Nachrichten der Unterhaltung. Der Kontext ist begrenzt, darum gibt es Grenzen für Verlauf und Stellen.
- Denkmodus: Manche Modelle schreiben vor der Antwort einen unsichtbaren Gedankengang und zählen ihn zum Token-Budget; für Korrektur und Chat schaltet man ihn beim Anbieter aus, sonst kann die Antwort leer bleiben.
- Kontextkopf: Der Videotitel und das Thema, die jedem Stück vor dem Einbetten vorangestellt werden, damit die Suche den Zusammenhang eines Stücks kennt.
- Werkzeug: Ein fremder Dienst, den der Chat zusätzlich befragen darf. MCP-Server: ein Programm, das seine Werkzeuge über ein offenes Protokoll (Model Context Protocol) anbietet und beschreibt. HTTP-Dienst: eine Webadresse, die auf eine Anfrage Daten liefert. JSON: das Textformat, in dem solche Dienste antworten, aus benannten Feldern und Listen.

## Werkstatt

- Fließband, Stufe, Auftrag: Jedes Video durchläuft feste Stufen (Abgleich, Audio, Transkription, Korrektur, Stückelung, Einbettung); jeder Schritt ist ein Auftrag mit Fortschritt, Protokoll und Ergebnis.
- Umfang: Die Menge der Videos, die auf dem Fließband verarbeitet werden. Die Auswahlregel nimmt automatisch auf; von Hand aufgenommene oder ausgeschlossene Videos bleiben so.
- Whisper: Das Spracherkennungsmodell, das aus der Tonspur Text mit Zeitmarken macht. Transkript: dieser Text in Segmenten (Satz- oder Absatzstücken mit Anfangs- und Endzeit), auf Wunsch mit Zeitmarke je Wort.
- Arbeiter: Ein Prozess des Transkriptionsdienstes mit geladenem Modell, der eine Datei zur Zeit transkribiert. Instanz: eine weitere geladene Kopie des Einbettungsmodells in LM Studio. Beides sind Wege, mehrere Aufträge gleichzeitig zu rechnen; die Grafikeinheit bleibt die gemeinsame Grenze.
- Stapel: So viele Stücke gehen in einer Anfrage zusammen an das Einbettungsmodell; größere Stapel sind schneller, brauchen aber mehr Speicher.
- Abweichungswächter: Die Prüfung nach der Korrektur, die jeden Block mit dem Rohtext vergleicht und zu stark veränderte Blöcke verwirft, damit das Sprachmodell nichts erfindet oder weglässt.
- Bitrate und Abtastrate: Die Datenrate der Tonspur in Kilobit je Sekunde und die Zahl der Messpunkte je Sekunde (Hertz). Für Sprache reichen 64 Kilobit und 16.000 Hertz; Whisper rechnet ohnehin mit 16.000. Mono: eine Tonspur statt links und rechts. AAC: das Tonformat der Audiodateien.
- ffmpeg: Das Werkzeug, das Ton und Video liest und wandelt; es muss auf dem Rechner installiert sein.
- LM Studio: Das Programm, das die lokalen Modelle (Sprachmodell, Einbettung) lädt und über eine Schnittstelle bereitstellt. fastembed: eine Alternative für die Einbettung ohne LM Studio, die mit dem kleinen Modell bge-m3 auf dem Prozessor läuft.
- Serie und Folge: Die Erklärserie des Kanals (mmM) und ihre Nummer, aus dem Titel erkannt; sie steuert Reihenfolge und Anzeige.
- Übergabe: Ein Ordner mit zufälliger Kennung, der alles Entstandene (Bibliothek, Audio, Modelle) für einen Empfänger bündelt; die Kennung in der Adresse ist der Zugang. Prüfsumme (SHA-256): ein Fingerabdruck einer Datei, mit dem sich prüfen lässt, dass sie unverändert und vollständig angekommen ist.
- Modellfamilie: Dasselbe Einbettungsmodell unter verschiedenen Anbieternamen (bge-m3 in LM Studio heißt text-embedding-bge-m3, bei fastembed BAAI/bge-m3); die Suche behandelt sie als eines.
