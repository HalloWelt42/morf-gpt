---
titel: Schritt 1: Audio beschaffen
unterzeile: Die Tonspur wird geholt und in ein schlankes, einheitliches Format gebracht.
kategorie: Werkstatt
symbol: fa-headphones
stichworte: audio, ffmpeg, m4a, bezugsweg, tonspur
---

Was passiert: Von der Quelle wird der Videostrom geholt (oder die Quelle extrahiert das Audio selbst); bei lokalen Dateien wird die Datei direkt gelesen. ffmpeg (das Werkzeug für Ton und Video) wandelt die Tonspur in eine einzelne Tonspur im Format AAC mit der eingestellten Abtastrate (Messpunkte je Sekunde) und Bitrate (Datenmenge je Sekunde); für Sprache reichen kleine Werte. Die fertige Datei liegt unter data/audio und wird bei einem erneuten Lauf wiederverwendet, wenn sie noch gültig ist.

Warum das wichtig ist: Die Transkription braucht eine saubere, kleine Tonspur; ein Video von zehn Minuten wird zu etwa fünf Megabyte. Dieselbe Datei spielt später der Audiospieler ab, damit jede Fundstelle ab der Sekunde anhörbar ist. Ohne Audio gibt es weder Transkript noch Abspielknopf.

<div class="m-hinweis tipp"><i class="fa-solid fa-lightbulb"></i> Die Audiodateien gehören zur Werkstatt und sind nicht Teil des Bibliothekspakets. Wer nur das Paket hat, sieht die Belege trotzdem und springt über die Originaladresse zur Stelle.</div>
