---
titel: Schritt 5: Einbetten
unterzeile: Jedes Stück bekommt einen Vektor, damit die Suche nach Bedeutung statt nach Wörtern findet.
kategorie: Werkstatt
symbol: fa-cube
stichworte: einbettung, vektor, bge-m3, ähnlichkeit, pgvector
---

Was passiert: Das Einbettungsmodell (bge-m3, 1024 Dimensionen) berechnet für jedes Stück einen Vektor, der seine Bedeutung beschreibt. Die Vektoren liegen in der Datenbank neben den Stücken; ein Index macht die Ähnlichkeitssuche schnell. Wechselt das Einbettungsmodell, müssen alle Stücke neu eingebettet werden.

Warum das wichtig ist: Erst jetzt kann der Chat das Video finden. Eine Frage wird mit demselben Modell eingebettet und mit allen Stücken verglichen; die ähnlichsten werden zu Fundstellen, aus denen das Sprachmodell antwortet. Ohne Einbettung existiert ein Video für den Chat nicht, auch wenn Transkript und Stücke fertig sind.

<div class="m-hinweis tipp"><i class="fa-solid fa-lightbulb"></i> Für den Betrieb ohne große Hardware reicht das lokale bge-m3 über fastembed; die Vektoren sind Teil des Bibliothekspakets und müssen am Zielort nicht neu gerechnet werden.</div>
