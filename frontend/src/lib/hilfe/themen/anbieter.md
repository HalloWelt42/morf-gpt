---
titel: Anbieter
unterzeile: Sprachmodelle und Einbettungen, Rollen zuweisen.
kategorie: Verwaltung
symbol: fa-microchip
stichworte: lm studio, hetzner, fastembed, rolle, schlüssel, modell
---

![Rollen chat, korrektur und einbettung mit Anbieterauswahl](/hilfe/anbieter.png)
*Rollen: welcher Anbieter antwortet, korrigiert und einbettet.*


Ein Anbieter ist ein Dienst, der ein Sprachmodell oder eine Einbettung liefert. Drei Rollen zeigen auf je einen Anbieter: Chat-Antworten, Korrektur und Einbettung. Prüfen fragt die Erreichbarkeit ab, Probe senden macht einen echten kurzen Aufruf.

## Denkmodus

Manche Sprachmodelle (etwa die Qwen-Familie bei der Hetzner-Inferenz) denken vor jeder Antwort in einem eigenen, unsichtbaren Textteil. Das kostet Zeit und Token: Bei der Korrektur eines Blocks verbrauchte das Denken das ganze Token-Budget, die eigentliche Antwort blieb leer und der Rohtext blieb stehen. Darum hat jeder Sprachmodell-Anbieter die Option Denkmodus: aus (empfohlen für Korrektur und Chat), an, oder nicht steuern (der Dienst entscheidet). Die Einstellung geht als Feld mit jeder Anfrage mit; Dienste, die es nicht kennen, ignorieren es. Meldet die Korrektur "Antwort leer" mit dem Hinweis auf Denk-Token, ist genau das der Grund.

<div class="m-hinweis warnung"><i class="fa-solid fa-triangle-exclamation"></i> Die Einbettung baut den Index. Wechselst du auf ein anderes Einbettungsmodell, müssen alle Stücke neu eingebettet werden. Ein Wechsel des Anbieters bei gleichem Modell (bge-m3 in LM Studio, bge-m3 über fastembed) ist dagegen unschädlich: die Suche vergleicht über die Modellfamilie.</div>

## Einbettung ohne LM Studio

Der Anbieter "Lokal - bge-m3 (fastembed)" rechnet die Einbettung auf dem Prozessor, ohne Dienst und ohne Grafikeinheit; das Modell (2,3 Gigabyte) lädt beim ersten Aufruf in die Modellablage des Projekts oder kommt mit einer Übergabe mit. Für Empfänger der Bibliothek ist das der einfache Weg: Rolle Einbettung auf diesen Anbieter stellen, fertig.
