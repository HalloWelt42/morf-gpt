---
titel: Schritt 2: Transkribieren
unterzeile: Aus der Tonspur wird Text mit Zeitmarken je Segment.
kategorie: Werkstatt
symbol: fa-closed-captioning
stichworte: transkript, whisper, segmente, zeitmarken, sprache, arbeiter, dienst, parallel
---

Was passiert: Die Audiodatei geht an den Transkriptionsdienst (Whisper, großes Modell). Zurück kommt der gesprochene Text in Segmenten mit Anfangs- und Endzeit sowie die erkannte Sprache. Das Transkript wird unverändert gespeichert, als Rohfassung und als Grundlage für alle späteren Schritte.

Warum das wichtig ist: Die Zeitmarken sind der Anker jeder Fundstelle. Jeder Absatz, jedes Stück und jeder Beleg im Chat kennt sein Zeitfenster nur, weil das Transkript es kennt. Die Qualität dieses Schritts begrenzt die Qualität aller Antworten; deshalb läuft hier das beste verfügbare Modell, auch wenn es der langsamste Schritt ist.

<div class="m-hinweis warnung"><i class="fa-solid fa-triangle-exclamation"></i> Transkription und Sprachmodell teilen sich die Grafikeinheit. Laufen beide, wird beides langsamer; die Parallelität je Stufe lässt sich in den Einstellungen begrenzen.</div>

## Eigener Dienst

Die Transkription läuft über den mitgelieferten Dienst (Whisper, großes Modell), nicht über ein fremdes Programm: er startet mit der Anwendung, lädt sein Modell beim ersten Mal selbst und nutzt auf Apple Silicon die Grafikeinheit, sonst den Prozessor. Unter Einstellungen, Transkription steht seine Adresse; die Karte darüber zeigt seinen Stand: welche Arbeiter geladen sind, ob sie gerade transkribieren, wie viele Aufträge warten und wie viel Speicher der Rechner noch hat.

![Karte des Transkriptionsdienstes mit Arbeitern und Speicher](/hilfe/transkription-dienst.png)
*Einstellungen, Transkription: der Dienst mit seinen Arbeitern, dem Arbeitsspeicher des Rechners und dem Speicherplatz des Projekts auf der Platte.*

## Arbeiter und Parallelität

Ein Arbeiter ist ein Prozess mit geladenem Modell (etwa 3,5 GB), der eine Datei zur Zeit transkribiert. Die Einstellung Arbeiter (1 bis 4) sagt dem Dienst, wie viele er halten soll; die Stufe bringt ihn vor jedem Auftrag darauf. Vor dem Laden eines weiteren Arbeiters prüft der Dienst den freien Speicher (frei plus inaktiv) gegen die gemessene Modellgröße und seine Reserve; was nicht passt, wird nicht geladen, sondern gemeldet. Beim Verkleinern enden freie Arbeiter sofort, beschäftigte nach ihrem Auftrag.

Gemessen an Videos von fünf bis sieben Minuten: ein Arbeiter schafft etwa dreifache Echtzeit; zwei Arbeiter mit je einem Video schaffen zusammen etwa 40 Prozent mehr, vier etwa zwei Drittel mehr. Jeder einzelne Auftrag wird dabei langsamer (mit vier Arbeitern etwa halb so schnell wie allein), weil alle dieselbe Grafikeinheit teilen; der Gewinn liegt im Durchsatz über viele Videos. Damit zwei Arbeiter überhaupt gleichzeitig arbeiten, müssen unter Einstellungen, Fließband ebenso viele parallele Transkriptionen erlaubt sein; sonst wartet der zweite Arbeiter auf Aufträge.
