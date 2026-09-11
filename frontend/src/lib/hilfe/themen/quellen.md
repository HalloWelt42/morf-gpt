---
titel: Quellen: Dienst oder Verzeichnis
unterzeile: Woher Videos kommen: TubeVault-Kanal oder lokale Dateien, beides zugleich möglich.
kategorie: Werkstatt
symbol: fa-folder-open
stichworte: quelle, verzeichnis, lokale dateien, tubevault, kanal, beiblatt, abgleich
---

![Formular Neue Quelle mit Typ Lokale Dateien und Verzeichnis](/hilfe/quellen-neu.png)
*Neue Quelle: Typ wählen, bei lokalen Dateien das Verzeichnis eintragen, prüfen, anlegen.*


Eine Quelle liefert Videos samt Metadaten in die Bibliothek. Es gibt zwei Arten, und beide dürfen nebeneinander bestehen: ein Kanal in einem Videodienst (TubeVault) und ein Verzeichnis mit eigenen Dateien auf diesem Rechner. Der Abgleich liest die Quelle, legt neue Videos an, frischt bekannte auf und wendet die Aufnahmeregel an.

Lokale Dateien: Jede Video- oder Audiodatei unter dem Verzeichnis (auch in Unterordnern) wird ein Video. Titel entsteht aus dem Dateinamen, Datum aus dem Änderungsdatum, Dauer aus der Datei. Liegt ein Beiblatt name.json oder name.info.json daneben (etwa von einem Downloader), werden Titel, Beschreibung, Datum, Schlagworte und Originaladresse daraus übernommen. Ein Bild name.jpg, name.png oder name.webp daneben wird das Vorschaubild; fehlt es, zieht die Werkstatt bei Videodateien ein Einzelbild aus dem Film.

Die Kennung eines lokalen Videos ergibt sich aus seinem Pfad im Verzeichnis. Ein erneuter Abgleich erkennt dieselbe Datei wieder; eine umbenannte oder verschobene Datei gilt als neues Video.

<div class="m-hinweis tipp"><i class="fa-solid fa-lightbulb"></i> Was die Quelle nicht liefert, pflegst du am Video von Hand nach (Bearbeiten in der Videoansicht): Serie und Folge, Datum, Originaladresse, Schlagworte, Vorschaubild. Diese Felder bleiben beim nächsten Abgleich stehen.</div>
