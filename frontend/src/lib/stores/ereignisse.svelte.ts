// Ereignisstrom vom Backend (SSE). Eine Verbindung für die ganze Oberfläche; Ansichten
// abonnieren einzelne Arten. Verbindungszustand ist sichtbar (Kopfleiste).

export interface Ereignis {
  art: string;
  daten: Record<string, unknown>;
}

type Empfaenger = (e: Ereignis) => void;

const ARTEN = [
  "auftrag_status",
  "auftrag_fortschritt",
  "auftrag_protokoll",
  "einstellung",
  "anbieter",
  "video",
  "quelle",
  "export",
  "herzschlag",
] as const;

class Ereignisstrom {
  verbunden = $state(false);
  letztes = $state<Ereignis | null>(null);
  private quelle: EventSource | null = null;
  private empfaenger = new Map<string, Set<Empfaenger>>();
  private alle = new Set<Empfaenger>();

  start(): void {
    if (this.quelle) return;
    const q = new EventSource("/api/ereignisse/stream?verlauf=0");
    this.quelle = q;
    q.onopen = () => (this.verbunden = true);
    q.onerror = () => (this.verbunden = false);
    for (const art of ARTEN) {
      q.addEventListener(art, (ev) => this.verteile(art, (ev as MessageEvent).data));
    }
    q.onmessage = (ev) => this.verteile("message", ev.data);
  }

  private verteile(art: string, roh: string): void {
    let daten: Record<string, unknown> = {};
    try {
      daten = JSON.parse(roh) as Record<string, unknown>;
    } catch {
      daten = { text: roh };
    }
    const e: Ereignis = { art, daten };
    if (art !== "herzschlag") this.letztes = e;
    for (const f of this.empfaenger.get(art) ?? []) f(e);
    for (const f of this.alle) f(e);
  }

  /** Abonnieren; die Rückgabe beendet das Abonnement (in onDestroy aufrufen). */
  abonniere(art: string | "*", f: Empfaenger): () => void {
    if (art === "*") {
      this.alle.add(f);
      return () => this.alle.delete(f);
    }
    if (!this.empfaenger.has(art)) this.empfaenger.set(art, new Set());
    this.empfaenger.get(art)!.add(f);
    return () => this.empfaenger.get(art)?.delete(f);
  }
}

export const ereignisse = new Ereignisstrom();
