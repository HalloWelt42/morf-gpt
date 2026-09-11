// Inhalt der Hilfe: Abschnitte mit stabilen Ankern. Mini-i-Knöpfe springen per Anker.
// Struktur ohne HTML-Einbettung renderbar (h2, absatz, punkte, schritte, tipp, warnung).

export type BlockTyp = "h2" | "absatz" | "punkte" | "schritte" | "tipp" | "warnung";

export interface Block {
  typ: BlockTyp;
  text?: string;
  punkte?: string[];
}

export interface Abschnitt {
  anker: string;
  kategorie: string;
  titel: string;
  kurz: string;
  stichworte: string[];
  bloecke: Block[];
}

export const HILFE: Abschnitt[] = [
  {
    anker: "erste-schritte",
    kategorie: "Anfang",
    titel: "Erste Schritte",
    kurz: "Von der leeren Bibliothek zur ersten Antwort.",
    stichworte: ["start", "einrichten", "quelle", "anbieter"],
    bloecke: [
      { typ: "absatz", text: "morf-gpt holt die Audiospur der Videos, schreibt sie mit Whisper mit, lässt ein Sprachmodell die Form glätten, zerlegt den Text in große Stücke, bettet sie ein und beantwortet Fragen ausschließlich aus diesen Stücken. Jede Antwort belegt ihre Stellen mit Video und Zeitfenster." },
      { typ: "schritte", punkte: [
        "Unter Einstellungen, Quellen den Kanal anlegen und abgleichen. Alle Videos über der Mindestdauer kommen in den Umfang.",
        "Unter Einstellungen, Anbieter prüfen, ob Sprachmodell und Einbettung erreichbar sind.",
        "Im Fließband mit Band auffüllen die Aufträge anlegen. Ab dann läuft alles von selbst weiter.",
        "Sobald die ersten Videos eingebettet sind, antwortet der Chat aus ihnen. Der Stand steht in der Kopfleiste.",
      ] },
    ],
  },
  {
    anker: "chat",
    kategorie: "Chat",
    titel: "Chat",
    kurz: "Fragen stellen, belegte Antworten lesen, Stellen prüfen.",
    stichworte: ["frage", "antwort", "unterhaltung", "belege"],
    bloecke: [
      { typ: "absatz", text: "Links stehen die Unterhaltungen, in der Mitte der Verlauf, rechts die Suchleiste mit den Fundstellen. Eine Frage löst zuerst die Suche aus; die gefundenen Stellen erscheinen rechts, dann antwortet das Sprachmodell nur aus diesen Stellen." },
      { typ: "absatz", text: "Zahlen im Text wie [2] sind Belege. Ein Klick darauf hebt die Stelle rechts hervor; dort kannst du sie abspielen, bei YouTube öffnen oder in der Bibliothek ansehen." },
      { typ: "tipp", text: "Mit Nur suchen siehst du die Stellen, bevor eine Antwort entsteht. Wähle ab, was nicht passt, und lass dann antworten." },
    ],
  },
  {
    anker: "suche-breite",
    kategorie: "Chat",
    titel: "Suche: Breite",
    kurz: "Wie viel Material die Suche einbezieht.",
    stichworte: ["treffer", "nachbarn", "vielfalt", "je video"],
    bloecke: [
      { typ: "punkte", punkte: [
        "Treffer: So viele Stellen werden höchstens ausgewählt. Mehr Treffer geben dem Modell mehr Material, machen die Antwort aber breiter.",
        "Nachbarstücke je Treffer: Jede Stelle bekommt die angrenzenden Stücke desselben Videos mit, damit ein Gedanke nicht am Schnitt endet.",
        "Höchstens je Video: Sorgt für Vielfalt. Ohne diese Grenze könnten alle Treffer aus einem einzigen Video stammen.",
      ] },
    ],
  },
  {
    anker: "suche-genauigkeit",
    kategorie: "Chat",
    titel: "Suche: Genauigkeit",
    kurz: "Wie streng die Suche filtert und neu ordnet.",
    stichworte: ["mindestähnlichkeit", "neu-bewertung", "cross-encoder", "cosinus"],
    bloecke: [
      { typ: "punkte", punkte: [
        "Mindestähnlichkeit: Ein Wert zwischen 0 und 1. Stellen, deren Ähnlichkeit zur Frage darunter liegt, werden verworfen. 0,45 ist ein guter Anfang; bei sehr spezifischen Fragen hilft ein höherer Wert.",
        "Neu-Bewertung: Ordnet die Kandidaten mit einem zweiten Verfahren neu. Der Cross-Encoder ist lokal und schnell, das Sprachmodell am genauesten, aber langsam.",
      ] },
      { typ: "warnung", text: "Eine zu hohe Mindestähnlichkeit lässt gar keine Stellen übrig. Dann sagt die Antwort ehrlich, dass nichts gefunden wurde." },
    ],
  },
  {
    anker: "fundstellen",
    kategorie: "Chat",
    titel: "Fundstellen",
    kurz: "Was die Karten rechts zeigen und was du damit tun kannst.",
    stichworte: ["stellen", "abwählen", "abspielen", "youtube"],
    bloecke: [
      { typ: "absatz", text: "Jede Karte zeigt Video, Folge, Zeitfenster und den Wert der Ähnlichkeit. Der Balken ist der Wert zwischen 0 und 1. Mit dem Häkchen nimmst du eine Stelle aus der Antwort; Neu antworten nutzt dann nur die verbliebenen." },
    ],
  },
  {
    anker: "spieler",
    kategorie: "Chat",
    titel: "Audiospieler",
    kurz: "Ab Zeitmarke hören, springen, Tempo, YouTube.",
    stichworte: ["audio", "abspielen", "tempo", "zeitleiste"],
    bloecke: [
      { typ: "absatz", text: "Die Leiste unten bleibt über alle Ansichten bestehen. Die Zeitleiste zeigt die Themen des Videos; ein Klick springt dorthin. Die Knöpfe springen 5 und 30 Sekunden, das Tempo reicht von 0,8 bis 2,0. Das YouTube-Symbol öffnet das Original an derselben Sekunde." },
    ],
  },
  {
    anker: "bibliothek",
    kategorie: "Bibliothek",
    titel: "Bibliothek",
    kurz: "Alle Videos der Quelle, Umfang und Stufe.",
    stichworte: ["videos", "umfang", "auswahl", "stufe", "serie"],
    bloecke: [
      { typ: "absatz", text: "Die Liste zeigt jedes Video der Quelle mit Serie, Dauer und Stufe. Im Umfang heißt: das Video wird auf dem Fließband verarbeitet. Die Auswahlregel nimmt automatisch alle Videos über der Mindestdauer; von Hand kannst du jedes Video aufnehmen oder ausschließen, diese Entscheidung bleibt bestehen." },
      { typ: "absatz", text: "Die Stufe ist die höchste fertige Stufe: Audio bereit, Transkribiert, Korrigiert, Gestückelt, Eingebettet. Nur eingebettete Videos können im Chat gefunden werden." },
    ],
  },
  {
    anker: "video",
    kategorie: "Bibliothek",
    titel: "Video im Detail",
    kurz: "Originaldaten, Transkript, Korrektur, Themen, Stücke, Aufträge.",
    stichworte: ["transkript", "korrektur", "themen", "zurücksetzen"],
    bloecke: [
      { typ: "absatz", text: "Oben stehen die Originaldaten der Quelle und die Sprünge zu YouTube und in den Spieler. Die Reiter zeigen die Stufen des Videos. Über Fließband kannst du einzelne Stufen neu anlegen oder das Video auf eine Stufe zurücksetzen; dabei werden die Ergebnisse oberhalb gelöscht und neu gerechnet." },
    ],
  },
  {
    anker: "korrektur",
    kategorie: "Bibliothek",
    titel: "Korrektur und Abweichungswächter",
    kurz: "Warum das Modell nur die Form ändert.",
    stichworte: ["wächter", "ähnlichkeit", "verworfen", "blöcke"],
    bloecke: [
      { typ: "absatz", text: "Das Sprachmodell darf Zeichensetzung, Groß- und Kleinschreibung, offensichtliche Hörfehler und Absätze verbessern, sonst nichts. Der Abweichungswächter vergleicht jeden Block mit dem Rohtext; liegt die Ähnlichkeit unter der eingestellten Schwelle, bleibt der Rohtext stehen und der Block gilt als verworfen." },
      { typ: "absatz", text: "Im Vergleich siehst du beide Fassungen nebeneinander und kannst einen verworfenen Block bewusst übernehmen oder von Hand bearbeiten." },
    ],
  },
  {
    anker: "stellen",
    kategorie: "Bibliothek",
    titel: "Textstellen",
    kurz: "Die Stücke, aus denen Antworten entstehen.",
    stichworte: ["chunk", "stück", "überlappung", "einbetten", "teilen"],
    bloecke: [
      { typ: "absatz", text: "Ein Stück ist ein großer Textabschnitt mit Zeitfenster und Thema. Benachbarte Stücke überlappen sich um ganze Sätze, damit kein Gedanke am Schnitt verloren geht. Die Überlappung ist im Detail farbig markiert." },
      { typ: "absatz", text: "Du kannst ein Stück bearbeiten, teilen oder mit dem nächsten zusammenlegen. Danach muss es neu eingebettet werden; das Stück zeigt an, wenn die Einbettung fehlt." },
    ],
  },
  {
    anker: "fliessband",
    kategorie: "Werkstatt",
    titel: "Fließband",
    kurz: "Sechs Stufen, Aufträge, Durchsatz, Pausen.",
    stichworte: ["aufträge", "pause", "parallel", "durchsatz", "restzeit", "fehler"],
    bloecke: [
      { typ: "absatz", text: "Jedes Video durchläuft die Stufen Audio, Transkription, Korrektur, Stückelung und Einbettung. Je Stufe siehst du fertige, laufende und wartende Aufträge, den Durchsatz der letzten Stunde und eine geschätzte Restzeit. Der Schalter je Stufe hält sie an; laufende Aufträge enden noch." },
      { typ: "absatz", text: "Band auffüllen legt für alle Videos im Umfang den nächsten Schritt an. Fehlgeschlagene Aufträge zeigen die Ursache und lassen sich einzeln oder gesammelt wiederholen." },
      { typ: "tipp", text: "Die Transkription ist die langsamste Stufe; sie nutzt die Grafikeinheit gemeinsam mit dem Sprachmodell. Läuft beides, wird beides langsamer." },
    ],
  },
  {
    anker: "anbieter",
    kategorie: "Verwaltung",
    titel: "Anbieter",
    kurz: "Sprachmodelle und Einbettungen, Rollen zuweisen.",
    stichworte: ["lm studio", "hetzner", "fastembed", "rolle", "schlüssel", "modell"],
    bloecke: [
      { typ: "absatz", text: "Ein Anbieter ist ein Dienst, der ein Sprachmodell oder eine Einbettung liefert. Drei Rollen zeigen auf je einen Anbieter: Chat-Antworten, Korrektur und Einbettung. Prüfen fragt die Erreichbarkeit ab, Probe senden macht einen echten kurzen Aufruf." },
      { typ: "warnung", text: "Die Einbettung baut den Index. Wechselst du das Einbettungsmodell, müssen alle Stücke neu eingebettet werden; die Suche nutzt immer das Modell, das den Index gebaut hat." },
    ],
  },
  {
    anker: "werkzeuge",
    kategorie: "Verwaltung",
    titel: "Werkzeuge und fremde Dienste",
    kurz: "Weitere Quellen neben der Bibliothek: HTTP-Dienste und MCP-Server.",
    stichworte: ["werkzeug", "mcp", "http", "dienst", "weitere quellen", "modell wählt", "fundus", "wetter", "websuche"],
    bloecke: [
      { typ: "absatz", text: "Ein Werkzeug ist ein fremder Dienst, den der Chat zusätzlich zur Bibliothek befragen kann: ein MCP-Server (etwa ein eigener Recherche-Server mit Websuche, Wikipedia oder Wetter) oder ein beliebiger HTTP-Dienst mit JSON-Antwort. Werkzeuge sind eine Zusatzoption: die Bibliothek braucht keines davon. Solange kein Werkzeug angelegt ist, erscheint der Abschnitt im Chat gar nicht, und es läuft nie ein Werkzeug, das du nicht ausdrücklich eingeschaltet hast. Werkzeuge werden unter Einstellungen, Werkzeuge angelegt; bei MCP-Servern entdeckt Prüfen die einzelnen Werkzeuge, die du einzeln freischaltest." },
      { typ: "punkte", punkte: [
        "Ich wähle: alle im Chat eingeschalteten Werkzeuge laufen vor jeder Antwort. Braucht ein Werkzeug nur eine Frage, bekommt es die Frage; braucht es andere Angaben (etwa einen Ort), leitet das Sprachmodell sie aus der Frage ab.",
        "Modell wählt: die eingeschalteten Werkzeuge gehen als Funktionen mit, und das Modell entscheidet je Frage, ob und welche es aufruft. Das braucht ein Modell mit Werkzeugaufrufen; sonst antwortet der Chat ohne Werkzeuge und sagt das.",
        "Ergebnisse erscheinen als Stellen mit Steckersymbol, werden wie Videostellen mit [n] belegt und lassen sich abwählen. Jeder Aufruf steht mit Argumenten und Dauer unter der Antwort.",
      ] },
      { typ: "tipp", text: "Bei einem HTTP-Dienst beschreiben die Pfade, wo in der JSON-Antwort Text, Titel und Quelladresse stehen, zum Beispiel ergebnisse[].text. Mit Probe siehst du sofort, was der Dienst liefert." },
      { typ: "warnung", text: "Zeitgrenzen, Rundenzahl und die Kürzung langer Ergebnisse stehen unter Einstellungen, Werkzeuge. Geheime Kopfzeilen sind in der Verwaltung lesbar, im Protokoll maskiert." },
    ],
  },
  {
    anker: "einstellungen",
    kategorie: "Verwaltung",
    titel: "Einstellungen",
    kurz: "Jede Grenze mit Beschreibung, Bereich und Vorgabe.",
    stichworte: ["grenzen", "vorgabe", "zurücksetzen", "speichern"],
    bloecke: [
      { typ: "absatz", text: "Alle Werte werden beim Ändern gespeichert, ohne Speichern-Knopf. Geänderte Werte sind hervorgehoben und lassen sich einzeln auf die Vorgabe zurücksetzen. Grenzen, Einheit und Wirkung stehen bei jedem Wert." },
    ],
  },
  {
    anker: "umzug",
    kategorie: "Verwaltung",
    titel: "Umzug der Bibliothek",
    kurz: "Paket exportieren und anderswo importieren.",
    stichworte: ["export", "import", "paket", "umziehen", "server"],
    bloecke: [
      { typ: "absatz", text: "Das Paket enthält Videodaten, Korrekturen, Stücke, Vektoren und Vorschaubilder. Damit läuft die Bibliothek samt Chat an einem anderen Ort ohne die Rohdaten; nur ein Sprachmodell und dasselbe Einbettungsmodell werden gebraucht. Audio bleibt zurück, der Sprung zu YouTube bleibt immer möglich." },
    ],
  },
];
