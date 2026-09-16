---
titel: Umzug der Bibliothek
unterzeile: Paket exportieren und anderswo importieren.
kategorie: Verwaltung
symbol: fa-truck-ramp-box
stichworte: export, import, paket, umziehen, server, übergabe, empfänger, kennung, prüfsumme, holen
---

![Karte Paket erstellen mit Schalter für Rohtranskripte](/hilfe/umzug.png)
*Umzug: Paket erstellen, herunterladen und an anderer Stelle importieren.*


Das Paket enthält Videodaten, Korrekturen, Stücke, deren Vektoren (die Einbettungen, siehe Begriffe), Vorschaubilder und die Dokumente mit Kapiteln, Stücken und Originaldateien. Damit läuft die Bibliothek samt Chat an einem anderen Ort ohne die Rohdaten; nur ein Sprachmodell und dasselbe Einbettungsmodell werden gebraucht. Audio bleibt zurück, der Sprung zu YouTube bleibt immer möglich.

## Übergabe

Für einen Empfänger, der die Bibliothek ohne diese Werkstatt weiterbetreiben soll, gibt es unter Umzug die Übergabe: ein Ordner mit zufälliger Kennung (einer UUID, einer 36 Zeichen langen Zufallskennung), darin das Bibliothekspaket mit Rohtranskripten und Dokumenten, wahlweise alle Audiodateien in Teilen zu 2 Gigabyte und die lokalen Modelle (Spracherkennung und Einbettung), dazu eine Datei mit Prüfsummen (SHA-256, ein Fingerabdruck je Datei, mit dem der Empfänger die Unversehrtheit prüft) und eine Anleitung. Nicht enthalten sind deine Zugangsschlüssel, Anbieter, Einstellungen, Aufträge und Unterhaltungen.

Den Ordner lädst du auf einen Webspace. Die Kennung im Pfad ist der Zugang: die Adresse erfährt nur, wer die Bibliothek bekommen soll, Verzeichnislisten bleiben aus. Die Karte zeigt zu jeder Übergabe Ordner, Teile, Größen und Prüfsummen und bietet die Adresse an, unter der sie auch direkt von diesem Rechner geholt werden kann.

![Karte einer vorhandenen Übergabe mit Kennung, Teilen, Größen und Prüfsummen](/hilfe/uebergabe.png)
*Vorhandene Übergaben: Kennung, Ordner, Zähler und je Teil Größe und Prüfsumme.*

## Übergabe holen

Als Empfänger trägst du unter Umzug im Feld Übergabe holen die Adresse ein: die Webadresse mit der Kennung oder einen Ordner auf deinem Rechner, wenn die Dateien schon da sind. morf-gpt lädt die Teile, prüft jede Prüfsumme, liest die Bibliothek ein, legt die Audiodateien für den Abspieler ab und die Modelle in die Modellablage. Ein abgebrochener Download setzt beim nächsten Versuch dort fort, wo er stand. Danach fehlt nur noch das eigene Sprachmodell unter Einstellungen, Anbieter; die Einbettung übernimmt das mitgelieferte bge-m3 über fastembed, das dieselben Vektoren liefert wie der Index.

<div class="m-hinweis tipp"><i class="fa-solid fa-lightbulb"></i> Der Index passt zum Einbettungsmodell, nicht zum Anbieter: bge-m3 aus LM Studio und bge-m3 über fastembed liefern dieselben Vektoren (gemessen Cosinus 0,9995). Die Suche vergleicht darum über die Modellfamilie und findet die Stellen auch nach einem Anbieterwechsel.</div>
