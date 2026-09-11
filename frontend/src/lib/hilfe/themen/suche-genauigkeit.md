---
titel: Suche: Genauigkeit
unterzeile: Wie streng die Suche filtert und neu ordnet.
kategorie: Chat
symbol: fa-bullseye
stichworte: mindestähnlichkeit, neu-bewertung, cross-encoder, cosinus
---

![Regler für Breite und Genauigkeit](/hilfe/chat-breite.png)
*Genauigkeit: Mindestähnlichkeit und Neu-Bewertung stehen unter den Reglern der Breite.*


- Mindestähnlichkeit: Ein Wert zwischen 0 und 1. Stellen, deren Ähnlichkeit zur Frage darunter liegt, werden verworfen. 0,45 ist ein guter Anfang; bei sehr spezifischen Fragen hilft ein höherer Wert.
- Neu-Bewertung: Ordnet die Kandidaten mit einem zweiten Verfahren neu. Der Cross-Encoder ist lokal und schnell, das Sprachmodell am genauesten, aber langsam.

<div class="m-hinweis warnung"><i class="fa-solid fa-triangle-exclamation"></i> Eine zu hohe Mindestähnlichkeit lässt gar keine Stellen übrig. Dann sagt die Antwort ehrlich, dass nichts gefunden wurde.</div>
