---
titel: Werkzeuge und fremde Dienste
unterzeile: Weitere Quellen neben der Bibliothek: HTTP-Dienste und MCP-Server.
kategorie: Verwaltung
symbol: fa-plug
stichworte: werkzeug, mcp, http, dienst, weitere quellen, modell wählt, fundus, wetter, websuche
---

![Abschnitt Weitere Quellen mit Umschalter und Werkzeugschaltern](/hilfe/chat-werkzeuge.png)
*Weitere Quellen im Chat: Ich wähle oder Modell wählt, darunter die Schalter der Werkzeuge.*


Ein Werkzeug ist ein fremder Dienst, den der Chat zusätzlich zur Bibliothek befragen kann: ein MCP-Server (ein Programm, das seine Werkzeuge über das offene Model Context Protocol anbietet, etwa ein eigener Recherche-Server mit Websuche, Wikipedia oder Wetter) oder ein beliebiger HTTP-Dienst, also eine Webadresse, die auf eine Anfrage strukturierte Daten im Textformat JSON liefert. Werkzeuge sind eine Zusatzoption: die Bibliothek braucht keines davon. Solange kein Werkzeug angelegt ist, erscheint der Abschnitt im Chat gar nicht, und es läuft nie ein Werkzeug, das du nicht ausdrücklich eingeschaltet hast. Werkzeuge werden unter Einstellungen, Werkzeuge angelegt; bei MCP-Servern entdeckt Prüfen die einzelnen Werkzeuge, die du einzeln freischaltest.

- Ich wähle: alle im Chat eingeschalteten Werkzeuge laufen vor jeder Antwort. Braucht ein Werkzeug nur eine Frage, bekommt es die Frage; braucht es andere Angaben (etwa einen Ort), leitet das Sprachmodell sie aus der Frage ab.
- Modell wählt: die eingeschalteten Werkzeuge gehen als Funktionen mit, und das Modell entscheidet je Frage, ob und welche es aufruft. Das braucht ein Modell mit Werkzeugaufrufen; sonst antwortet der Chat ohne Werkzeuge und sagt das.
- Ergebnisse erscheinen als Stellen mit Steckersymbol, werden wie Videostellen mit [n] belegt und lassen sich abwählen. Jeder Aufruf steht mit Argumenten und Dauer unter der Antwort.

<div class="m-hinweis tipp"><i class="fa-solid fa-lightbulb"></i> Bei einem HTTP-Dienst beschreiben die Pfade, wo in der Antwort Text, Titel und Quelladresse stehen (JSON ist aus benannten Feldern und Listen aufgebaut; ein Pfad wie ergebnisse[].text meint: in der Liste ergebnisse das Feld text jedes Eintrags). Mit Probe siehst du sofort, was der Dienst liefert.</div>

<div class="m-hinweis warnung"><i class="fa-solid fa-triangle-exclamation"></i> Zeitgrenzen, Rundenzahl und die Kürzung langer Ergebnisse stehen unter Einstellungen, Werkzeuge. Geheime Kopfzeilen sind in der Verwaltung lesbar, im Protokoll maskiert.</div>

![Karte eines MCP-Servers mit entdeckten Werkzeugen](/hilfe/werkzeuge-mcp.png)
*Einstellungen, Werkzeuge: ein MCP-Server mit Prüfen, Probe und den einzeln freischaltbaren Werkzeugen.*

