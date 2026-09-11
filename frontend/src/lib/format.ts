// Darstellung von Zahlen, Zeiten und Daten - deutsch, ohne Abkürzungen.

const zahlFormat = new Intl.NumberFormat("de-DE");
const dezimalFormat = new Intl.NumberFormat("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function zahl(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  return zahlFormat.format(n);
}

export function dezimal(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  return dezimalFormat.format(n);
}

/** Sekunden als Zeitmarke: 3:05, 12:49, 1:31:07. */
export function zeitmarke(sekunden: number | null | undefined): string {
  if (sekunden === null || sekunden === undefined || Number.isNaN(sekunden)) return "-";
  const s = Math.max(0, Math.floor(sekunden));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const r = s % 60;
  const mm = h > 0 ? String(m).padStart(2, "0") : String(m);
  return `${h > 0 ? `${h}:` : ""}${mm}:${String(r).padStart(2, "0")}`;
}

/** Dauer in Worten: 35 Minuten, 5 Tage 18 Stunden, 40 Sekunden. */
export function dauerWorte(sekunden: number | null | undefined): string {
  if (sekunden === null || sekunden === undefined || Number.isNaN(sekunden)) return "-";
  const s = Math.max(0, Math.round(sekunden));
  if (s < 60) return `${s} ${s === 1 ? "Sekunde" : "Sekunden"}`;
  const min = Math.floor(s / 60);
  if (min < 60) return `${min} ${min === 1 ? "Minute" : "Minuten"}`;
  const h = Math.floor(min / 60);
  const restMin = min % 60;
  if (h < 24) return `${h} ${h === 1 ? "Stunde" : "Stunden"}${restMin ? ` ${restMin} Minuten` : ""}`;
  const tage = Math.floor(h / 24);
  const restH = h % 24;
  return `${tage} ${tage === 1 ? "Tag" : "Tage"}${restH ? ` ${restH} Stunden` : ""}`;
}

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined) return "-";
  if (n < 1024) return `${n} Byte`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} Kilobyte`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1).replace(".", ",")} Megabyte`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2).replace(".", ",")} Gigabyte`;
}

const datumFormat = new Intl.DateTimeFormat("de-DE", { day: "numeric", month: "long", year: "numeric" });
const datumZeitFormat = new Intl.DateTimeFormat("de-DE", {
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const uhrzeitFormat = new Intl.DateTimeFormat("de-DE", { hour: "2-digit", minute: "2-digit", second: "2-digit" });

export function datum(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : datumFormat.format(d);
}

export function datumZeit(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : datumZeitFormat.format(d);
}

export function uhrzeit(iso: string | null | undefined): string {
  if (!iso) return "-";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : uhrzeitFormat.format(d);
}

/** "vor 12 Minuten", "vor 2 Stunden", "gerade eben". */
export function vorZeit(iso: string | null | undefined): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return iso;
  const diff = Math.max(0, (Date.now() - t) / 1000);
  if (diff < 10) return "gerade eben";
  return `vor ${dauerWorte(diff)}`;
}

/** Serie und Folge als Kurzform: mmM#377. */
export function folge(serie: string | null | undefined, nr: number | null | undefined): string {
  if (!serie) return "";
  return nr === null || nr === undefined ? serie : `${serie}#${nr}`;
}

/** YouTube-Adresse mit Zeitmarke. */
export function youtubeMitZeit(url: string, sekunden: number | null | undefined): string {
  if (!url) return "";
  const s = Math.max(0, Math.floor(sekunden ?? 0));
  if (!s) return url;
  return `${url}${url.includes("?") ? "&" : "?"}t=${s}`;
}
