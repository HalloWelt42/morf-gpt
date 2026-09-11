// Themen der Hilfe: eine Markdown-Datei je Thema unter ./themen/*.md mit Kopf (Frontmatter):
//   ---
//   titel: Schritt 1: Audio beschaffen
//   unterzeile: Die Tonspur wird geholt ...
//   kategorie: Werkstatt
//   symbol: fa-headphones
//   stichworte: audio, ffmpeg
//   ---
//   ... Markdown ...
// Vite liest die Dateien beim Bauen ein (import.meta.glob mit ?raw); der Rumpf wird mit marked zu
// HTML und durch DOMPurify geführt. Die Dateien sind eigene, fest mitgelieferte Inhalte, kein
// Nutzertext; nur deshalb ist die Ausgabe per {@html} im Fenster unbedenklich.
import { marked } from "marked";
import DOMPurify from "dompurify";
import bildmasse from "./bildmasse.json";

export interface Thema {
  anker: string;
  titel: string;
  unterzeile: string;
  kategorie: string;
  symbol: string;
  stichworte: string[];
  markdown: string;
  html: string;
}

/** Feste Reihenfolge der Themen; nicht Aufgeführtes folgt alphabetisch. */
const REIHENFOLGE = [
  "erste-schritte",
  "begriffe",
  "chat",
  "suche-breite",
  "suche-genauigkeit",
  "fundstellen",
  "spieler",
  "quellen",
  "pflege",
  "dokumente",
  "stufe-abgleich",
  "stufe-audio",
  "stufe-transkription",
  "stufe-korrektur",
  "stufe-stueckelung",
  "stufe-einbettung",
  "bibliothek",
  "video",
  "korrektur",
  "stellen",
  "fliessband",
  "anbieter",
  "werkzeuge",
  "einstellungen",
  "umzug",
];

const KOPF_MUSTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?([\s\S]*)$/;

function kopfLesen(quelle: string): { meta: Record<string, string>; rumpf: string } {
  const treffer = quelle.match(KOPF_MUSTER);
  if (!treffer) return { meta: {}, rumpf: quelle };
  const meta: Record<string, string> = {};
  for (const zeile of treffer[1].split(/\r?\n/)) {
    const i = zeile.indexOf(":");
    if (i > 0) meta[zeile.slice(0, i).trim()] = zeile.slice(i + 1).trim();
  }
  return { meta, rumpf: treffer[2] };
}

type Bildmasse = Record<string, { breite: number; hoehe: number }>;
const MASSE = bildmasse as Bildmasse;
const BILD = /<img src="\/hilfe\/([a-z0-9-]+)\.png" alt="([^"]*)">/g;

/** Bilder der Hilfe: je Thema eine Fassung (hell, dunkel) mit demselben Ausschnitt, gezeigt in Bildschirmpixeln (1:1). */
function bilderJeThema(html: string): string {
  return html.replace(BILD, (_treffer, name: string, alt: string) => {
    const m = MASSE[name];
    const masse = m ? ` width="${m.breite}" height="${m.hoehe}"` : "";
    return (
      `<span class="m-bild">` +
      `<img class="hell" src="/hilfe/${name}.png"${masse} alt="${alt}" loading="lazy">` +
      `<img class="dunkel" src="/hilfe/${name}-dunkel.png"${masse} alt="${alt}" loading="lazy">` +
      `</span>`
    );
  });
}

function rendere(markdown: string): string {
  const html = marked.parse(markdown, { async: false, gfm: true, breaks: false }) as string;
  return DOMPurify.sanitize(bilderJeThema(html), { ADD_ATTR: ["target", "rel", "loading"] });
}

const rohdateien = import.meta.glob("./themen/*.md", { query: "?raw", import: "default", eager: true }) as Record<string, string>;

const themen: Record<string, Thema> = {};
for (const [pfad, quelle] of Object.entries(rohdateien)) {
  const anker = pfad.replace(/^.*\//, "").replace(/\.md$/, "");
  const { meta, rumpf } = kopfLesen(quelle);
  themen[anker] = {
    anker,
    titel: meta.titel ?? anker,
    unterzeile: meta.unterzeile ?? "",
    kategorie: meta.kategorie ?? "Allgemein",
    symbol: meta.symbol ?? "fa-circle-info",
    stichworte: (meta.stichworte ?? "").split(",").map((s) => s.trim()).filter(Boolean),
    markdown: rumpf.trim(),
    html: rendere(rumpf),
  };
}

export function holeThema(anker: string): Thema | null {
  return themen[anker] ?? null;
}

export function gibtThema(anker: string): boolean {
  return anker in themen;
}

export function alleThemen(): Thema[] {
  return Object.values(themen).sort((a, b) => {
    const ia = REIHENFOLGE.indexOf(a.anker);
    const ib = REIHENFOLGE.indexOf(b.anker);
    if (ia !== -1 || ib !== -1) return (ia === -1 ? 999 : ia) - (ib === -1 ? 999 : ib);
    return a.titel.localeCompare(b.titel, "de");
  });
}

// Für die Suche: je Thema die Texte seiner Textknoten aus einem einmal aufgebauten, losgelösten
// DOM. So zählt die Suche genau die Vorkommen, die das Fenster später hervorhebt.
const knotenSpeicher: Record<string, string[]> = {};

function textknoten(anker: string): string[] {
  if (knotenSpeicher[anker]) return knotenSpeicher[anker];
  const thema = themen[anker];
  if (!thema || typeof document === "undefined") return [];
  const el = document.createElement("div");
  el.innerHTML = thema.html;
  const laeufer = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const texte: string[] = [];
  while (laeufer.nextNode()) texte.push(laeufer.currentNode.nodeValue ?? "");
  knotenSpeicher[anker] = texte;
  return texte;
}

/** Zahl der Vorkommen eines Begriffs im Text eines Themas (knotenweise, wie die Hervorhebung). */
export function zaehleTreffer(anker: string, begriff: string): number {
  const nadel = begriff.trim().toLowerCase();
  if (!nadel) return 0;
  let treffer = 0;
  for (const text of textknoten(anker)) {
    const klein = text.toLowerCase();
    let pos = 0;
    let i: number;
    while ((i = klein.indexOf(nadel, pos)) !== -1) {
      treffer++;
      pos = i + nadel.length;
    }
  }
  return treffer;
}
