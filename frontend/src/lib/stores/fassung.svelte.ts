// Neue Fassung auf dem Server: nie ein hartes Neuladen verlangen (Muster aus Orbit und Kellerwolke).
// Die Startseite kommt ohne Zwischenspeicher (backend/app/main.py), Skripte und Gestaltung tragen Prüfsummen im
// Namen. Meldet das Backend eine andere Fassung als die eingebaute, lädt die Seite von selbst neu: in den ersten
// Sekunden nach dem Start sofort, später beim nächsten Ansichtswechsel oder wenn das Fenster wieder nach vorn kommt.
// Nie, solange etwas läuft, das ein Neuladen abbräche (Wiedergabe, Antwortstrom, Hochladen, ungespeicherte
// Eingaben); die Ansichten melden das über `neuladenAufhalten`. Dazwischen steht ein Band mit Knopf. Je Serverfassung
// nur ein selbsttätiger Versuch (Merker in der Sitzung), damit ein hängender Zwischenspeicher keine Schleife auslöst.
// Im Entwicklungsserver ruht der Vergleich: dort hält Vite die Oberfläche selbst frisch, und die eingebaute Fassung
// stammt vom Start des Servers (der Commit-Hook zählt version.json hoch, ohne dass Vite das mitbekommt).
import { onMount } from "svelte";
import { SvelteSet } from "svelte/reactivity";
import { api } from "../api";
import type { Gesundheit } from "../typen";
import { spieler } from "./spieler.svelte";

export const OBERFLAECHE_FASSUNG = __APP_VERSION_VOLL__;
const MERKER = "morf-gpt.neu_geladen";
const START_FENSTER_MS = 10_000;
const PRUEFEN_MS = 60_000;

export const fassung = $state<{ neu: string | null }>({ neu: null });

export type Anlass = "start" | "takt" | "ortswechsel" | "sichtbar";

const aufhalter = new SvelteSet<() => boolean>();

/** Während der Lebenszeit der aufrufenden Ansicht hält `bedingung` (wenn wahr) das selbsttätige Neuladen auf. */
export function neuladenAufhalten(bedingung: () => boolean): void {
  onMount(() => {
    aufhalter.add(bedingung);
    return () => {
      aufhalter.delete(bedingung);
    };
  });
}

// Nichts, was ein Neuladen abbrechen würde: keine Wiedergabe und keine Ansicht, die gerade etwas tut.
export function ruhig(): boolean {
  if (spieler.laeuft) return false;
  for (const bedingung of aufhalter) if (bedingung()) return false;
  return true;
}

function erlaubt(neu: string): boolean {
  try {
    if (sessionStorage.getItem(MERKER) === neu) return false;
    sessionStorage.setItem(MERKER, neu);
  } catch {
    // ohne Sitzungsspeicher kein Merker: dann lieber einmal laden als nie
  }
  return true;
}

export function vielleichtNeuLaden(anlass: Anlass): void {
  const neu = fassung.neu;
  if (!neu || anlass === "takt" || !ruhig()) return;
  if (anlass === "start" && performance.now() > START_FENSTER_MS) return;
  if (erlaubt(neu)) location.reload();
}

async function fassungPruefen(anlass: Anlass): Promise<void> {
  try {
    const server = (await api.get<Gesundheit>("/system/health")).version_voll;
    fassung.neu = server !== OBERFLAECHE_FASSUNG ? server : null;
  } catch {
    return; // ohne Backend bleibt alles, wie es ist
  }
  vielleichtNeuLaden(anlass);
}

function sichtbar(): void {
  if (document.visibilityState === "visible") void fassungPruefen("sichtbar");
}

function ortswechsel(): void {
  vielleichtNeuLaden("ortswechsel");
}

export function fassungVerfolgen(): () => void {
  if (import.meta.env.DEV) return () => {};
  void fassungPruefen("start");
  const takt = window.setInterval(() => void fassungPruefen("takt"), PRUEFEN_MS);
  document.addEventListener("visibilitychange", sichtbar);
  window.addEventListener("hashchange", ortswechsel);
  return () => {
    window.clearInterval(takt);
    document.removeEventListener("visibilitychange", sichtbar);
    window.removeEventListener("hashchange", ortswechsel);
  };
}
