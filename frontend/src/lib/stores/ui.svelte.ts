// Oberflächenzustand: Ansicht (Hash-Route), Thema, Hilfefenster. Persistiert im Browser.

export type Ansicht =
  | "chat"
  | "bibliothek"
  | "video"
  | "stellen"
  | "stelle"
  | "fliessband"
  | "auftrag"
  | "einstellungen";

export interface Route {
  ansicht: Ansicht;
  id: string;
  unter: string;
}

const GUELTIG: Ansicht[] = ["chat", "bibliothek", "video", "stellen", "stelle", "fliessband", "auftrag", "einstellungen"];

function lese(schluessel: string): string | null {
  try {
    return localStorage.getItem(schluessel);
  } catch {
    return null;
  }
}

function schreibe(schluessel: string, wert: string): void {
  try {
    localStorage.setItem(schluessel, wert);
  } catch {
    // Speicher nicht verfügbar
  }
}

function routeAusHash(): Route {
  const roh = location.hash.replace(/^#\/?/, "");
  const [a = "", b = "", c = ""] = roh.split("/");
  const ansicht = (GUELTIG.includes(a as Ansicht) ? a : (lese("m-ansicht") ?? "chat")) as Ansicht;
  return { ansicht, id: decodeURIComponent(b), unter: decodeURIComponent(c) };
}

class UiZustand {
  route = $state<Route>({ ansicht: "chat", id: "", unter: "" });
  thema = $state<"light" | "dark">("light");
  hilfeOffen = $state(false);
  hilfeAnker = $state("");

  constructor() {
    const t = lese("m-thema");
    this.thema = t === "dark" ? "dark" : "light";
    this.route = routeAusHash();
    if (!location.hash) this.gehe(this.route.ansicht, this.route.id, this.route.unter);
    window.addEventListener("hashchange", () => {
      this.route = routeAusHash();
      schreibe("m-ansicht", this.route.ansicht);
    });
    this.themaAnwenden();
  }

  gehe(ansicht: Ansicht, id = "", unter = ""): void {
    const teile = [ansicht, id, unter].filter((t) => t !== "").map(encodeURIComponent);
    const neu = `#/${teile.join("/")}`;
    if (location.hash !== neu) location.hash = neu;
    else this.route = routeAusHash();
    schreibe("m-ansicht", ansicht);
  }

  themaWechseln(): void {
    this.thema = this.thema === "dark" ? "light" : "dark";
    schreibe("m-thema", this.thema);
    this.themaAnwenden();
  }

  private themaAnwenden(): void {
    document.documentElement.setAttribute("data-bs-theme", this.thema);
  }

  hilfe(anker = ""): void {
    this.hilfeAnker = anker;
    this.hilfeOffen = true;
  }

  hilfeSchliessen(): void {
    this.hilfeOffen = false;
  }
}

export const ui = new UiZustand();
