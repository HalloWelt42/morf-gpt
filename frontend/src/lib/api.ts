// Zugriff auf das Backend. Alle Aufrufe gehen über diese Datei; jede Antwort hat einen
// expliziten Typ (siehe lib/typen.ts). Fehler werden als ApiFehler mit der deutschen
// Meldung des Backends geworfen.

export class ApiFehler extends Error {
  status: number;
  constructor(status: number, meldung: string) {
    super(meldung);
    this.status = status;
  }
}

async function fehlerAus(antwort: Response): Promise<ApiFehler> {
  let meldung = `HTTP ${antwort.status}`;
  try {
    const daten = (await antwort.json()) as { detail?: unknown };
    if (typeof daten.detail === "string") meldung = daten.detail;
    else if (Array.isArray(daten.detail)) {
      meldung = daten.detail
        .map((d) => (typeof d === "object" && d && "msg" in d ? String((d as { msg: unknown }).msg) : String(d)))
        .join("; ");
    }
  } catch {
    // kein JSON-Körper
  }
  return new ApiFehler(antwort.status, meldung);
}

async function anfrage<T>(methode: string, pfad: string, koerper?: unknown): Promise<T> {
  const antwort = await fetch(`/api${pfad}`, {
    method: methode,
    headers: koerper === undefined ? {} : { "Content-Type": "application/json" },
    body: koerper === undefined ? undefined : JSON.stringify(koerper),
  });
  if (!antwort.ok) throw await fehlerAus(antwort);
  if (antwort.status === 204) return undefined as T;
  return (await antwort.json()) as T;
}

export const api = {
  get: <T>(pfad: string) => anfrage<T>("GET", pfad),
  post: <T>(pfad: string, koerper?: unknown) => anfrage<T>("POST", pfad, koerper),
  put: <T>(pfad: string, koerper?: unknown) => anfrage<T>("PUT", pfad, koerper),
  patch: <T>(pfad: string, koerper?: unknown) => anfrage<T>("PATCH", pfad, koerper),
  del: <T>(pfad: string) => anfrage<T>("DELETE", pfad),
  /** Datei per multipart hochladen (ohne JSON-Kopf). */
  hochladen: async <T>(pfad: string, formular: FormData): Promise<T> => {
    const antwort = await fetch(`/api${pfad}`, { method: "POST", body: formular });
    if (!antwort.ok) throw await fehlerAus(antwort);
    return (await antwort.json()) as T;
  },
};

/** Suchparameter an eine Adresse hängen; leere Werte werden ausgelassen. */
export function mitParametern(pfad: string, parameter: Record<string, string | number | boolean | undefined | null>): string {
  const teile: string[] = [];
  for (const [k, v] of Object.entries(parameter)) {
    if (v === undefined || v === null || v === "") continue;
    teile.push(`${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
  }
  return teile.length ? `${pfad}?${teile.join("&")}` : pfad;
}

export interface SseEreignis {
  art: string;
  daten: Record<string, unknown>;
}

/**
 * SSE per POST (fetch-Stream), weil EventSource nur GET kann. Ruft je Ereignis den
 * Empfänger auf; die zurückgegebene Funktion bricht den Strom ab.
 */
export function postStrom(
  pfad: string,
  koerper: unknown,
  empfaenger: (e: SseEreignis) => void,
  fertig: (fehler?: Error) => void,
): () => void {
  const steuerung = new AbortController();
  (async () => {
    try {
      const antwort = await fetch(`/api${pfad}`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify(koerper),
        signal: steuerung.signal,
      });
      if (!antwort.ok || !antwort.body) throw await fehlerAus(antwort);
      const leser = antwort.body.getReader();
      const dekoder = new TextDecoder();
      let puffer = "";
      let art = "message";
      let datenZeilen: string[] = [];
      const abschliessen = () => {
        if (datenZeilen.length) {
          const roh = datenZeilen.join("\n");
          let daten: Record<string, unknown> = {};
          try {
            daten = JSON.parse(roh) as Record<string, unknown>;
          } catch {
            daten = { text: roh };
          }
          empfaenger({ art, daten });
        }
        art = "message";
        datenZeilen = [];
      };
      for (;;) {
        const { value, done } = await leser.read();
        if (done) break;
        puffer += dekoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = puffer.indexOf("\n")) >= 0) {
          const zeile = puffer.slice(0, idx).replace(/\r$/, "");
          puffer = puffer.slice(idx + 1);
          if (zeile === "") abschliessen();
          else if (zeile.startsWith("event:")) art = zeile.slice(6).trim();
          else if (zeile.startsWith("data:")) datenZeilen.push(zeile.slice(5).replace(/^ /, ""));
        }
      }
      abschliessen();
      fertig();
    } catch (e) {
      if ((e as Error).name === "AbortError") fertig();
      else fertig(e as Error);
    }
  })();
  return () => steuerung.abort();
}
