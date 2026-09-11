// Meldungen unten rechts (statt Browser-Dialogen). Verschwinden nach einigen Sekunden.

export type MeldungArt = "normal" | "gut" | "fehler";

export interface Meldung {
  id: number;
  art: MeldungArt;
  text: string;
}

class Meldungen {
  liste = $state<Meldung[]>([]);
  private naechste = 1;

  zeige(text: string, art: MeldungArt = "normal", dauerMs = 5000): void {
    const id = this.naechste++;
    this.liste = [...this.liste, { id, art, text }];
    window.setTimeout(() => this.entferne(id), art === "fehler" ? Math.max(dauerMs, 9000) : dauerMs);
  }

  gut(text: string): void {
    this.zeige(text, "gut");
  }

  fehler(text: string): void {
    this.zeige(text, "fehler");
  }

  entferne(id: number): void {
    this.liste = this.liste.filter((m) => m.id !== id);
  }
}

export const meldungen = new Meldungen();

/** Fehler eines Aufrufs als Meldung zeigen und weitergeben. */
export function meldeFehler(e: unknown, vorsatz = ""): void {
  const text = e instanceof Error ? e.message : String(e);
  meldungen.fehler(vorsatz ? `${vorsatz}: ${text}` : text);
}
