// Typen der Backend-Antworten. Eine Wahrheit je Struktur; die Ansichten importieren von hier.

export interface Gesundheit {
  status: string;
  version: string;
  version_voll: string;
  laeufer_aktiv: boolean;
}

export interface StufenZaehler {
  stufe: string;
  titel: string;
  anzahl: number;
}

export interface Uebersicht {
  version: string;
  version_voll: string;
  videos_gesamt: number;
  videos_ausgewaehlt: number;
  chunks: number;
  einbettungen: number;
  auftraege_wartend: number;
  auftraege_laufend: number;
  auftraege_fehler: number;
  stufen: StufenZaehler[];
  laeufer_aktiv: boolean;
}

export interface Dienst {
  kennung: string;
  titel: string;
  adresse: string;
  erreichbar: boolean;
  hinweis: string;
}

// --- Einstellungen ----------------------------------------------------------
export type EinstellungTyp = "zahl" | "ganzzahl" | "text" | "schalter" | "auswahl";

export interface Auswahloption {
  wert: string;
  titel: string;
}

export interface Einstellung {
  schluessel: string;
  titel: string;
  beschreibung: string;
  typ: EinstellungTyp;
  gruppe: string;
  gruppe_titel: string;
  einheit: string;
  minimum: number | null;
  maximum: number | null;
  schritt: number | null;
  auswahl: Auswahloption[];
  vorgabe: unknown;
  wert: unknown;
  geaendert: boolean;
}

// --- Anbieter ---------------------------------------------------------------
export type AnbieterArt = "sprachmodell" | "einbettung";
export type AnbieterTyp = "lmstudio" | "openai_kompatibel" | "fastembed";

export interface Anbieter {
  id: string;
  name: string;
  typ: AnbieterTyp;
  typ_titel: string;
  art: AnbieterArt;
  basis_url: string;
  modell: string;
  parameter: Record<string, unknown>;
  aktiv: boolean;
  api_schluessel: string;
  hat_schluessel: boolean;
  erstellt: string | null;
}

export interface AnbieterUebersicht {
  anbieter: Anbieter[];
  rollen: Record<string, string>;
  rollen_titel: Record<string, string>;
  typen: Record<string, string>;
}

export interface AnbieterEingabe {
  name: string;
  typ: AnbieterTyp;
  art: AnbieterArt;
  basis_url: string;
  api_schluessel: string | null;
  modell: string;
  parameter: Record<string, unknown>;
  aktiv: boolean;
}

export interface AnbieterPruefung {
  erreichbar: boolean;
  hinweis: string;
  modelle: { id: string; geladen: boolean | null; typ?: string; dimension?: number }[];
}

export interface AnbieterProbe {
  text: string;
  modell: string;
  dauer_ms: number;
}

// --- Seitenweise Listen -----------------------------------------------------
export interface Seite<T> {
  eintraege: T[];
  gesamt: number;
  seite: number;
  je_seite: number;
}
