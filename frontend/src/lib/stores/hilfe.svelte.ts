// Zustand des freischwebenden Hilfefensters: eine Instanz für die ganze Anwendung, damit jeder
// Hilfepunkt dasselbe Fenster steuert. Lage, Größe, Zustand und zuletzt gezeigtes Thema werden im
// Browser gemerkt. Die Volltextsuche kennt zwei Bereiche: "alle" (alle Themen, das Durchblättern
// führt von Thema zu Thema) und "thema" (nur das gezeigte Thema).
import { alleThemen, gibtThema, zaehleTreffer } from "../hilfe/themen";

const SCHLUESSEL = "m-hilfe-fenster";
const KOPF_HOEHE = 44;
const MIN_BREITE = 380;
const MIN_HOEHE = 260;

export type Suchbereich = "alle" | "thema";

interface Gemerkt {
  x: number;
  y: number;
  breite: number;
  hoehe: number;
  minimiert: boolean;
  maximiert: boolean;
  thema: string;
}

interface Treffer {
  thema: string;
  lokal: number; // der wievielte Treffer innerhalb des Themas
}

const STANDARD: Gemerkt = { x: 0, y: 0, breite: 640, hoehe: 640, minimiert: false, maximiert: false, thema: "" };

function gemerktLesen(): Gemerkt {
  try {
    const roh = localStorage.getItem(SCHLUESSEL);
    if (roh) return { ...STANDARD, ...(JSON.parse(roh) as Partial<Gemerkt>) };
  } catch {
    // Gemerktes ist Bequemlichkeit; Fehler dürfen die Oberfläche nie stören.
  }
  return { ...STANDARD };
}

class HilfeZustand {
  offen = $state(false);
  thema = $state("");
  suche = $state("");
  bereich = $state<Suchbereich>("alle");
  trefferIndex = $state(0);
  treffer = $state<Treffer[]>([]);
  x = $state(STANDARD.x);
  y = $state(STANDARD.y);
  breite = $state(STANDARD.breite);
  hoehe = $state(STANDARD.hoehe);
  minimiert = $state(false);
  maximiert = $state(false);
  private bereit = false;

  get trefferGesamt(): number {
    return this.treffer.length;
  }

  /** Einmalig Lage und Größe herstellen; Standardlage oben rechts unter der Kopfleiste. */
  init(): void {
    if (this.bereit) return;
    const g = gemerktLesen();
    if (g.x === 0 && g.y === 0) {
      g.x = Math.max(16, window.innerWidth - g.breite - 24);
      g.y = 64;
    }
    this.x = g.x;
    this.y = g.y;
    this.breite = g.breite;
    this.hoehe = g.hoehe;
    this.minimiert = g.minimiert;
    this.maximiert = g.maximiert;
    if (!this.thema && gibtThema(g.thema)) this.thema = g.thema;
    this.bereit = true;
  }

  private ersterAnker(): string {
    return alleThemen()[0]?.anker ?? "";
  }

  /** Fenster öffnen und ein Thema zeigen. */
  zeige(anker = ""): void {
    this.init();
    if (anker && gibtThema(anker)) this.thema = anker;
    if (!this.thema) this.thema = this.ersterAnker();
    this.offen = true;
    this.minimiert = false;
    this.suche = "";
    this.trefferIndex = 0;
    this.treffer = [];
    this.speichern();
  }

  /** Thema wechseln. Läuft eine Suche über alle Themen, zum ersten Treffer dort springen. */
  waehle(anker: string): void {
    if (!gibtThema(anker)) return;
    this.thema = anker;
    if (this.bereich === "alle" && this.suche.trim()) {
      const i = this.treffer.findIndex((t) => t.thema === anker);
      if (i !== -1) this.trefferIndex = i;
    } else {
      this.trefferIndex = 0;
      this.neuBerechnen();
    }
    this.speichern();
  }

  /** Thema zeigen und darin gezielt einen Begriff suchen und markieren (Auffinden). */
  finde(anker: string, begriff: string): void {
    this.zeige(anker);
    this.bereich = "thema";
    this.suche = begriff;
    this.trefferIndex = 0;
    this.neuBerechnen();
  }

  /** Auf- und zuklappen über den zentralen Hilfe-Knopf. */
  umschalten(anker = ""): void {
    this.init();
    if (!this.offen) {
      this.zeige(anker);
      return;
    }
    this.offen = false;
    this.speichern();
  }

  schliessen(): void {
    this.offen = false;
    this.speichern();
  }

  setzeSuche(text: string): void {
    this.suche = text;
    this.trefferIndex = 0;
    this.neuBerechnen();
  }

  setzeBereich(bereich: Suchbereich): void {
    this.bereich = bereich;
    this.trefferIndex = 0;
    this.neuBerechnen();
  }

  /** Trefferliste zum Suchbegriff neu aufbauen; im Bereich "alle" über alle Themen in Reihenfolge. */
  neuBerechnen(): void {
    const nadel = this.suche.trim();
    const liste: Treffer[] = [];
    if (nadel) {
      const kandidaten = this.bereich === "alle" ? alleThemen().map((t) => t.anker) : [this.thema];
      for (const anker of kandidaten) {
        const n = zaehleTreffer(anker, nadel);
        for (let i = 0; i < n; i++) liste.push({ thema: anker, lokal: i });
      }
    }
    this.treffer = liste;
    if (this.trefferIndex >= liste.length) this.trefferIndex = 0;
    this.demAktivenFolgen();
  }

  /** Bei der Suche über alle Themen das Thema des aktiven Treffers zeigen. */
  private demAktivenFolgen(): void {
    const t = this.treffer[this.trefferIndex];
    if (t && t.thema !== this.thema) this.thema = t.thema;
  }

  naechster(): void {
    if (!this.treffer.length) return;
    this.trefferIndex = (this.trefferIndex + 1) % this.treffer.length;
    this.demAktivenFolgen();
  }

  voriger(): void {
    if (!this.treffer.length) return;
    this.trefferIndex = (this.trefferIndex - 1 + this.treffer.length) % this.treffer.length;
    this.demAktivenFolgen();
  }

  /** Trefferzahl je Thema (für die Themenliste bei der Suche über alle Themen). */
  trefferJeThema(anker: string): number {
    return this.treffer.reduce((n, t) => (t.thema === anker ? n + 1 : n), 0);
  }

  /** Lokaler Index des aktiven Treffers im gezeigten Thema (für die Hervorhebung), sonst -1. */
  aktivLokal(): number {
    const t = this.treffer[this.trefferIndex];
    return t && t.thema === this.thema ? t.lokal : -1;
  }

  minimierenUmschalten(): void {
    this.minimiert = !this.minimiert;
    if (this.minimiert) this.maximiert = false;
    this.speichern();
  }

  maximierenUmschalten(): void {
    this.maximiert = !this.maximiert;
    if (this.maximiert) this.minimiert = false;
    else this.einpassen();
    this.speichern();
  }

  /** Sichtschutz: Vollbild erzwingen, wenn die Bedienelemente aus dem Bild geraten sind. */
  maximieren(): void {
    this.init();
    this.offen = true;
    this.minimiert = false;
    this.maximiert = true;
    this.speichern();
  }

  /** Liegt das Fenster mit seinen Bedienelementen vollständig im Browserfenster? */
  imBild(): boolean {
    const w = window.innerWidth;
    const h = window.innerHeight;
    const unten = this.minimiert ? this.y + KOPF_HOEHE : this.y + this.hoehe;
    return this.x >= 0 && this.y >= 0 && this.x + this.breite <= w && unten <= h;
  }

  /** Lage und Größe so zwingen, dass das Fenster vollständig im Browserfenster liegt. */
  einpassen(): void {
    const w = window.innerWidth;
    const h = window.innerHeight;
    this.breite = Math.min(this.breite, Math.max(MIN_BREITE, w - 16));
    this.hoehe = Math.min(this.hoehe, Math.max(MIN_HOEHE, h - 16));
    this.x = Math.min(Math.max(0, this.x), Math.max(0, w - this.breite));
    this.y = Math.min(Math.max(0, this.y), Math.max(0, h - this.hoehe));
  }

  setzePosition(x: number, y: number): void {
    this.x = x;
    this.y = y;
  }

  setzeGroesse(breite: number, hoehe: number): void {
    this.breite = Math.max(MIN_BREITE, breite);
    this.hoehe = Math.max(MIN_HOEHE, hoehe);
  }

  speichern(): void {
    try {
      const g: Gemerkt = { x: this.x, y: this.y, breite: this.breite, hoehe: this.hoehe, minimiert: this.minimiert, maximiert: this.maximiert, thema: this.thema };
      localStorage.setItem(SCHLUESSEL, JSON.stringify(g));
    } catch {
      // siehe oben
    }
  }
}

export const hilfe = new HilfeZustand();
export { KOPF_HOEHE };
