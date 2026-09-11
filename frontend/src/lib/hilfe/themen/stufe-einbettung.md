---
titel: Schritt 5: Einbetten
unterzeile: Jedes Stück bekommt einen Vektor, damit die Suche nach Bedeutung statt nach Wörtern findet.
kategorie: Werkstatt
symbol: fa-cube
stichworte: einbettung, vektor, bge-m3, ähnlichkeit, pgvector
---

Was passiert: Das Einbettungsmodell (bge-m3) berechnet für jedes Stück einen Vektor: eine Reihe von 1024 Zahlen, die seine Bedeutung beschreibt, so dass Stücke mit ähnlichem Sinn ähnliche Zahlenreihen bekommen (siehe Begriffe). Die Vektoren liegen in der Datenbank neben den Stücken; ein Index macht die Ähnlichkeitssuche schnell. Wechselt das Einbettungsmodell, müssen alle Stücke neu eingebettet werden.

Warum das wichtig ist: Erst jetzt kann der Chat das Video finden. Eine Frage wird mit demselben Modell eingebettet und mit allen Stücken verglichen; die ähnlichsten werden zu Fundstellen, aus denen das Sprachmodell antwortet. Ohne Einbettung existiert ein Video für den Chat nicht, auch wenn Transkript und Stücke fertig sind.

## Mehrere Instanzen

Unter Einstellungen, Einbettung lässt sich die Zahl der Instanzen (geladener Kopien) des Modells in LM Studio wählen (1 bis 4) und wie viele Anfragen je Instanz gleichzeitig laufen. Die Stapel eines Auftrags werden im Wechsel auf die Instanzen verteilt. Gemessen an echten Stücken: eine Instanz 3,9 Texte je Sekunde, mit 2 bis 4 gleichzeitigen Anfragen 4,5 bis 4,8, zwei Instanzen mit je vier Anfragen 6,2. Mehr bringt kaum etwas, weil alle Instanzen dieselbe Grafikeinheit teilen. Vor dem Laden einer weiteren Instanz prüft die Werkstatt den freien Speicher (frei plus inaktiv) gegen die Modellgröße und die eingestellte Reserve; was nicht passt, wird nicht geladen, sondern gemeldet. Die Einstellungsseite zeigt die geladenen Instanzen, den Arbeitsspeicher des Rechners und den Speicherplatz des Projekts auf der Platte (Audio, Datenbank, Modelle und so weiter) und lädt oder entlädt Instanzen auf Knopfdruck.

<div class="m-hinweis tipp"><i class="fa-solid fa-lightbulb"></i> Für den Betrieb ohne große Hardware reicht das lokale bge-m3 über fastembed; die Vektoren sind Teil des Bibliothekspakets und müssen am Zielort nicht neu gerechnet werden.</div>
