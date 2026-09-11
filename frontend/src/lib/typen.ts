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
  dokumente: number;
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

// --- Seitenweise Listen -----------------------------------------------------
export interface Seite<T> {
  eintraege: T[];
  gesamt: number;
  seite: number;
  je_seite: number;
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

// --- Videos -------------------------------------------------------------------
export interface OffenerAuftrag {
  id: string;
  art: string;
  art_titel: string;
  status: string;
  fortschritt: number;
  meldung: string;
}

export interface VideoEintrag {
  id: string;
  extern_id: string;
  titel: string;
  serie: string;
  folge_nr: number | null;
  veroeffentlicht: string | null;
  dauer_s: number | null;
  typ: string;
  stufe: string;
  stufe_titel: string;
  ausgewaehlt: boolean;
  auswahl_manuell: boolean;
  fehler: string;
  original_url: string;
  miniatur_url: string | null;
  hat_audio: boolean;
  chunks_anzahl: number;
  offener_auftrag: OffenerAuftrag | null;
}

export interface SerieEintrag {
  serie: string;
  anzahl: number;
  ausgewaehlt: number;
  min_folge: number | null;
  max_folge: number | null;
}

export interface AudioInfo {
  id: string;
  pfad: string;
  format: string;
  dauer_s: number | null;
  groesse_bytes: number | null;
  abtastrate: number | null;
  kanaele: number | null;
  bezugsweg: string;
  datei_vorhanden: boolean;
  erstellt: string;
}

export interface TranskriptMeta {
  id: string;
  engine: string;
  modell: string;
  sprache: string;
  zeichen: number;
  segmente_anzahl: number;
  dauer_verarbeitung_s: number | null;
  erstellt: string;
}

export interface Thema {
  titel: string;
  start_s: number;
  end_s: number;
  kurz: string;
}

export interface KorrekturMeta {
  id: string;
  transkript_id: string | null;
  engine: string;
  anbieter: string;
  modell: string;
  absaetze_anzahl: number;
  themen: Thema[];
  zusammenfassung: string;
  aehnlichkeit: number | null;
  bloecke_gesamt: number;
  bloecke_verworfen: number;
  dauer_verarbeitung_s: number | null;
  manuell_bearbeitet: boolean;
  erstellt: string;
}

export interface AuftragKurz {
  id: string;
  art: string;
  art_titel: string;
  status: string;
  fortschritt: number;
  meldung: string;
  fehler: string;
  versuche: number;
  gestartet: string | null;
  beendet: string | null;
  erstellt: string;
}

export interface VideoDetail extends VideoEintrag {
  beschreibung: string;
  aufrufe: number | null;
  schlagworte: string[];
  kanal_name: string;
  quelle_id: string | null;
  quelle_typ: string;
  tubevault_url: string;
  quelle_heruntergeladen: boolean;
  datei_pfad: string;
  felder_manuell: string[];
  prioritaet: number;
  notizen: string;
  metadaten_original: Record<string, unknown>;
  audio: AudioInfo | null;
  transkript: TranskriptMeta | null;
  korrektur: KorrekturMeta | null;
  auftraege: AuftragKurz[];
  erstellt: string;
  aktualisiert: string;
}

export interface AuswahlregelAusgabe {
  mindest_dauer_s: number;
  typen: string[];
  nur_heruntergeladene: boolean;
}

export interface AuswahlRegelErgebnis {
  regel: AuswahlregelAusgabe;
  geprueft: number;
  aufgenommen: number;
  entfernt: number;
  unveraendert: number;
  auftraege_angelegt: number;
  auftraege_abgebrochen: number;
}

export interface AuswahlStapelErgebnis {
  angefragt: number;
  geaendert: number;
  unveraendert: number;
  nicht_gefunden: number;
  auftraege_angelegt: number;
  auftraege_abgebrochen: number;
}

export interface ZuruecksetzErgebnis {
  video_id: string;
  stufe_vorher: string;
  stufe_nachher: string;
  geloescht: Record<string, number>;
  auftraege_abgebrochen: number;
  folgeauftrag_id: string | null;
}

// --- Transkript / Korrektur -------------------------------------------------
export interface Wort {
  wort: string;
  start_s: number;
  end_s: number;
}

export interface Segment {
  index: number;
  start_s: number;
  end_s: number;
  text: string;
  woerter: Wort[];
}

export interface Transkript {
  id: string;
  video_id: string;
  engine: string;
  modell: string;
  sprache: string;
  zeichen: number;
  segmente_anzahl: number;
  dauer_verarbeitung_s: number | null;
  aktuell: boolean;
  erstellt: string;
  volltext: string;
  segmente: Segment[];
}

export interface Absatz {
  start_s: number;
  end_s: number;
  text: string;
  block: number;
  verworfen: boolean;
}

export interface Korrektur {
  id: string;
  video_id: string;
  transkript_id: string | null;
  engine: string;
  anbieter: string;
  modell: string;
  absaetze: Absatz[];
  themen: Thema[];
  zusammenfassung: string;
  aehnlichkeit: number | null;
  bloecke_gesamt: number;
  bloecke_verworfen: number;
  dauer_verarbeitung_s: number | null;
  manuell_bearbeitet: boolean;
  aktuell: boolean;
  erstellt: string;
}

export interface BlockVergleich {
  index: number;
  start_s: number;
  end_s: number;
  roh: string;
  korrigiert: string;
  absaetze: Absatz[];
  aehnlichkeit: number | null;
  verworfen: boolean;
  grund: string;
  vorschlag: string;
}

export interface Vergleich {
  korrektur_id: string;
  video_id: string;
  bloecke: BlockVergleich[];
  gesamt: number;
}

// --- Chunks -------------------------------------------------------------------
export interface ChunkEintrag {
  id: string;
  werkart: "video" | "dokument";
  video_id: string;
  video_titel: string;
  serie: string;
  folge_nr: number | null;
  original_url: string;
  miniatur_url: string | null;
  dokument_id: string;
  abschnitt: string;
  abschnitt_nr: number | null;
  position_von: number | null;
  reihenfolge: number;
  anzahl_im_video: number;
  text: string;
  start_s: number;
  end_s: number;
  zeichen: number;
  thema: string;
  ueberlappung_vor: number;
  ueberlappung_nach: number;
  manuell_bearbeitet: boolean;
  einbettungen: string[];
  erstellt: string;
  aktualisiert: string;
}

export interface Nachbar {
  id: string;
  reihenfolge: number;
  start_s: number;
  end_s: number;
  text: string;
}

export interface EinbettungInfo {
  modell: string;
  anbieter: string;
  dimension: number;
  erstellt: string;
}

export interface ChunkDetail extends ChunkEintrag {
  vorheriger: Nachbar | null;
  naechster: Nachbar | null;
  einbettung_details: EinbettungInfo[];
  korrektur_id: string | null;
}

// --- Aufträge -----------------------------------------------------------------
export interface AuftragEintrag {
  id: string;
  art: string;
  art_titel: string;
  video_id: string | null;
  video_titel: string;
  video_serie: string;
  video_folge_nr: number | null;
  status: string;
  prioritaet: number;
  versuche: number;
  fortschritt: number;
  meldung: string;
  fehler: string;
  gestartet: string | null;
  beendet: string | null;
  herzschlag: string | null;
  erstellt: string;
  laufzeit_s: number | null;
}

export interface AuftragDetail extends AuftragEintrag {
  parameter: Record<string, unknown>;
  ergebnis: Record<string, unknown>;
  protokoll_anzahl: number;
}

export interface ProtokollZeile {
  id: number;
  zeit: string;
  stufe: string;
  text: string;
}

export interface ProtokollSeite {
  eintraege: ProtokollZeile[];
  gesamt: number;
  ab: number;
  anzahl: number;
}

export interface ArtUebersicht {
  art: string;
  titel: string;
  wartend: number;
  laufend: number;
  fertig: number;
  fehler: number;
  abgebrochen: number;
  pausiert: boolean;
  pausierbar: boolean;
  parallel: number;
  durchsatz_fenster: number;
  mittlere_dauer_s: number | null;
  restzeit_s: number | null;
}

export interface BandUebersicht {
  arten: ArtUebersicht[];
  automatik: boolean;
  laeufer_aktiv: boolean;
  durchsatz_fenster_s: number;
  wartend_gesamt: number;
  laufend_gesamt: number;
  fehler_gesamt: number;
}

// --- Chat ---------------------------------------------------------------------
export interface Suchparameter {
  werkzeuge?: string[];
  werkzeugwahl?: "nutzer" | "modell";
  treffer: number;
  nachbarn: number;
  max_je_video: number;
  mindest_aehnlichkeit: number;
  neubewertung: string;
  kandidaten_faktor: number;
  serie: string;
  von: string | null;
  bis: string | null;
  video_ids: string[];
  werkart?: "" | "video" | "dokument";
  dokument_ids?: string[];
}

export interface Stelle {
  chunk_id: string;
  video_id: string;
  titel: string;
  serie: string;
  folge_nr: number | null;
  start_s: number;
  end_s: number;
  text: string;
  wert: number;
  reihenfolge: number;
  thema: string;
  original_url: string;
  miniatur: string;
  ueberlappung_vor: number;
  bewertung: number | null;
  art: "bibliothek" | "dokument" | "werkzeug";
  werkzeug: string;
  quelle_url: string;
  dokument_id: string;
  abschnitt: string;
  abschnitt_nr: number | null;
  seite_von: number | null;
  position_von: number | null;
  werk_id: string;
  benutzt?: boolean;
}

export interface Werkzeugaufruf {
  kennung: string;
  titel: string;
  argumente: Record<string, unknown>;
  herkunft: string;
  dauer_ms: number;
  stellen: number;
  text: string;
  fehler: string;
  runde: number;
}

export interface Unterhaltung {
  id: string;
  titel: string;
  suchparameter: Partial<Suchparameter>;
  nachrichten: number;
  letzte: string | null;
  erstellt: string;
  aktualisiert: string;
}

export interface Nachricht {
  id: string;
  rolle: "nutzer" | "assistent";
  inhalt: string;
  stellen: Stelle[];
  parameter: Record<string, unknown>;
  modell: string;
  dauer_ms: number | null;
  tokens_ein: number | null;
  tokens_aus: number | null;
  fehler: string;
  erstellt: string;
  // nur im Browser während des Streamens
  streamt?: boolean;
}

export interface UnterhaltungDetail extends Unterhaltung {
  verlauf: Nachricht[];
}

export interface SucheAusgabe {
  stellen: Stelle[];
  hinweise: string[];
  einbettungsmodell: string;
  neubewertung: string;
  parameter: Suchparameter;
}

// --- Quellen ----------------------------------------------------------------
export interface Quelle {
  id: string;
  typ: string;
  typ_titel: string;
  name: string;
  basis_url: string;
  adresse_zentral: boolean;
  kanal_id: string;
  kanal_name: string;
  kanal_beschreibung: string;
  regeln: Record<string, unknown>;
  aktiv: boolean;
  zuletzt_abgeglichen: string | null;
  erstellt: string;
  videos: number;
  videos_ausgewaehlt: number;
}

/** Von Hand gepflegte Metadaten eines Videos (PUT /videos/{id}). */
export interface VideoPflege {
  titel?: string;
  beschreibung?: string;
  veroeffentlicht?: string | null;
  dauer_s?: number;
  typ?: string;
  original_url?: string;
  kanal_name?: string;
  serie?: string;
  folge_nr?: number;
  folge_nr_loeschen?: boolean;
  schlagworte?: string[];
  handpflege_aufheben?: boolean;
}

export interface KanalAusgabe {
  kanal_id: string;
  name: string;
  beschreibung: string;
  videos_gesamt: number | null;
  videos_heruntergeladen: number | null;
}

export interface VorschauEintrag {
  extern_id: string;
  titel: string;
  veroeffentlicht: string | null;
  dauer_s: number | null;
  typ: string;
  heruntergeladen: boolean;
  wuerde_aufgenommen: boolean;
  bekannt: boolean;
}

// --- Export -------------------------------------------------------------------
export interface ExportStatus {
  laeuft: boolean;
  gestartet: string | null;
  mit_transkripten: boolean;
  fortschritt: number;
  meldung: string;
  letzte_datei: string | null;
  fehler: string;
}

export interface PaketInfo {
  name: string;
  groesse_bytes: number;
  erstellt: string;
}

export interface AuftragAusgabe {
  auftrag_id: string | null;
  hinweis: string;
}

// --- Werkzeuge ----------------------------------------------------------------
export interface EntdecktesWerkzeug {
  name: string;
  titel: string;
  beschreibung: string;
  parameter_schema: Record<string, unknown>;
  aktiv?: boolean;
}

export interface EinsetzbaresWerkzeug {
  kennung: string;
  titel: string;
  name: string;
  beschreibung: string;
  typ: string;
  werkzeug_id: string;
  parameter: string[];
  pflicht: string[];
  vorausgewaehlt: boolean;
}

export interface Werkzeug {
  id: string;
  name: string;
  typ: string;
  typ_titel: string;
  beschreibung: string;
  konfiguration: Record<string, unknown>;
  entdeckt: EntdecktesWerkzeug[];
  aktiv: boolean;
  vorausgewaehlt: boolean;
  zuletzt_geprueft: string | null;
  pruefung: { ok?: boolean; hinweis?: string };
  einsetzbar: EinsetzbaresWerkzeug[];
  erstellt: string | null;
}

export interface WerkzeugUebersicht {
  werkzeuge: Werkzeug[];
  typen: Record<string, string>;
  transporte: Record<string, string>;
}

export interface WerkzeugEingabe {
  name: string;
  typ: string;
  beschreibung: string;
  konfiguration: Record<string, unknown>;
  aktiv: boolean;
  vorausgewaehlt: boolean;
}

export interface WerkzeugPruefung {
  ok: boolean;
  hinweis: string;
  entdeckt: EntdecktesWerkzeug[];
}

export interface WerkzeugProbe {
  argumente: Record<string, unknown>;
  herkunft: string;
  dauer_ms: number;
  stellen: number;
  text: string;
  fehler: string;
}

// --- Dokumente ---------------------------------------------------------------
export interface AbschnittEintrag {
  id: string;
  reihenfolge: number;
  ebene: number;
  titel: string;
  zeichen: number;
  anker: string;
  seite_von: number | null;
  seite_bis: number | null;
  chunks_anzahl: number;
}

export interface AbschnittText extends AbschnittEintrag {
  text: string;
}

export interface DokumentEintrag {
  id: string;
  titel: string;
  autor: string;
  art: string;
  art_titel: string;
  sprache: string;
  veroeffentlicht: string | null;
  dateiname: string;
  groesse_bytes: number | null;
  zeichen: number;
  abschnitte_anzahl: number;
  chunks_anzahl: number;
  stufe: string;
  stufe_titel: string;
  fehler: string;
  offener_auftrag: OffenerAuftrag | null;
  erstellt: string;
  aktualisiert: string;
}

export interface DokumentDetail extends DokumentEintrag {
  beschreibung: string;
  notizen: string;
  prioritaet: number;
  felder_manuell: string[];
  metadaten_original: Record<string, unknown>;
  abschnitte: AbschnittEintrag[];
  auftraege: AuftragKurz[];
}

export interface DokumentInhalt {
  id: string;
  titel: string;
  abschnitte: AbschnittText[];
}

export interface DokumentAenderung {
  titel?: string;
  autor?: string;
  sprache?: string;
  beschreibung?: string;
  veroeffentlicht?: string | null;
  notizen?: string;
  prioritaet?: number;
  handpflege_aufheben?: boolean;
}

export interface EigenerText {
  titel: string;
  text: string;
  autor: string;
  art: "markdown" | "text";
}

export interface DokumentArt {
  kennung: string;
  titel: string;
  endungen: string[];
}
