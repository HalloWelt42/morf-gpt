#!/usr/bin/env node
// Bildschirmfotos für Hilfe und README: gezielte Ausschnitte aus der laufenden Oberfläche.
//
// Keine Vollbilder, sondern genau die Stelle, um die es im Text geht (ein Regler, eine Karte,
// eine Leiste). Läuft mit Chrome headless und dem DevTools-Protokoll über den WebSocket von
// Node 22, ohne weitere Pakete. Jedes Motiv entsteht zweimal mit demselben Ausschnitt: hell als
// <name>.png und dunkel als <name>-dunkel.png unter frontend/public/hilfe/. Die Maße in
// Bildschirmpixeln stehen in frontend/src/lib/hilfe/bildmasse.json, damit Hilfe und README die
// Bilder 1:1 zeigen. Die Hilfe blendet je nach Thema das passende Bild ein.
//
// Voraussetzung: die Anwendung läuft (./start.sh start), mit echten Daten.
// Nutzung: node tools/bildschirmfotos.mjs [--basis http://127.0.0.1:5460] [--nur name,name]

import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const WURZEL = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ZIEL = path.join(WURZEL, "frontend", "public", "hilfe");
const MASSE = path.join(WURZEL, "frontend", "src", "lib", "hilfe", "bildmasse.json");
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const BREITE = 1500;
const HOEHE = 950;
const PORT = 9333;
const SCHAERFE = 2; // Retina: Gerätemaßstab der Seite; der Ausschnitt selbst wird mit Maßstab 1 geholt,
// sonst multiplizieren sich beide und die Bilder werden vierfach groß.

const argumente = process.argv.slice(2);
const wert = (name, vorgabe) => {
  const i = argumente.indexOf(name);
  return i !== -1 && argumente[i + 1] ? argumente[i + 1] : vorgabe;
};
const BASIS = wert("--basis", "http://127.0.0.1:5460").replace(/\/$/, "");
const NUR = wert("--nur", "").split(",").map((s) => s.trim()).filter(Boolean);

// Hilfsfunktionen, die in der Seite laufen (als Text, weil sie per DevTools ausgewertet werden).
const HELFER = `
window.__foto = {
  rect(el) { el.scrollIntoView({ block: "nearest", inline: "nearest" }); const b = el.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height }; },
  eins(sel) { const el = document.querySelector(sel); if (!el) throw new Error("nicht gefunden: " + sel); return this.rect(el); },
  alle(sel, n) { const l = [...document.querySelectorAll(sel)].slice(0, n ?? 999); if (!l.length) throw new Error("nicht gefunden: " + sel); l[0].scrollIntoView({ block: "start" }); return this.union(l.map((e) => { const b = e.getBoundingClientRect(); return { x: b.x, y: b.y, width: b.width, height: b.height }; })); },
  union(rs) { const x = Math.min(...rs.map((r) => r.x)), y = Math.min(...rs.map((r) => r.y)); return { x, y, width: Math.max(...rs.map((r) => r.x + r.width)) - x, height: Math.max(...rs.map((r) => r.y + r.height)) - y }; },
  mitText(sel, text) { const el = [...document.querySelectorAll(sel)].find((e) => e.textContent.includes(text)); if (!el) throw new Error("kein " + sel + " mit " + text); return el; },
  thema(name) { document.documentElement.setAttribute("data-bs-theme", name); try { localStorage.setItem("m-thema", name); } catch {} },
  setze(el, wert) { const p = Object.getPrototypeOf(el); Object.getOwnPropertyDescriptor(p, "value").set.call(el, wert); el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); },
  warte(ms) { return new Promise((r) => setTimeout(r, ms)); },
};
true`;

/** Motive: Route, Vorbereitung in der Seite, Ausschnitt (liefert ein Rechteck), Rand in Pixeln. */
function motive(daten) {
  const f = "window.__foto";
  return [
    { name: "kopfleiste", pfad: "#/chat", ausschnitt: `${f}.eins(".m-kopf")`, rand: 0 },
    { name: "chat-antwort", pfad: `#/chat/${daten.unterhaltung}`, warten: 2500, ausschnitt: `${f}.alle(".m-nachricht.assistent", 1)`, rand: 6 },
    { name: "chat-fundstellen", pfad: `#/chat/${daten.unterhaltung}`, warten: 2500, ausschnitt: `${f}.alle(".m-seite:not(.links) .m-stelle", 2)`, rand: 8 },
    { name: "chat-breite", pfad: "#/chat", ausschnitt: `${f}.alle(".m-seite:not(.links) .m-parameter", 2)`, rand: 4 },
    { name: "chat-werkzeuge", pfad: "#/chat", vorher: `const k = document.querySelector('button[title="Ausklappen"]'); if (k) k.click(); await ${f}.warte(400);`, ausschnitt: `${f}.rect(${f}.mitText(".m-parameter", "Weitere Quellen"))`, rand: 4 },
    { name: "chat-filter", pfad: "#/chat", ausschnitt: `${f}.rect(${f}.mitText(".m-parameter", "Filter"))`, rand: 4 },
    { name: "chat-eingabe", pfad: "#/chat", ausschnitt: `${f}.eins(".m-chat-eingabe")`, rand: 4 },
    { name: "bibliothek-liste", pfad: "#/bibliothek", warten: 2500, ausschnitt: `${f}.union([${f}.eins(".m-tabelle-feld thead"), ${f}.alle(".m-tabelle-feld tbody tr", 6)])`, rand: 4 },
    { name: "video-kopf", pfad: `#/video/${daten.video}`, warten: 2500, ausschnitt: `${f}.eins(".m-ansicht-kopf")`, rand: 0 },
    { name: "video-daten", pfad: `#/video/${daten.video}`, warten: 2500, ausschnitt: `${f}.eins(".m-ansicht-koerper .card")`, rand: 4 },
    { name: "video-bearbeiten", pfad: `#/video/${daten.video}`, warten: 2500, vorher: `${f}.mitText("button", "Bearbeiten").click(); await ${f}.warte(500);`, ausschnitt: `${f}.eins(".m-ansicht-koerper .card")`, rand: 4 },
    { name: "video-reiter", pfad: `#/video/${daten.video}`, warten: 2500, ausschnitt: `${f}.eins("ul.nav-tabs")`, rand: 4 },
    { name: "dokumente-liste", pfad: "#/dokumente", warten: 2000, ausschnitt: `${f}.union([${f}.eins(".m-tabelle-feld thead"), ${f}.alle(".m-tabelle-feld tbody tr", 3)])`, rand: 4 },
    { name: "dokument-kapitel", pfad: `#/dokument/${daten.dokument}/10`, warten: 3000, ausschnitt: `(() => { const r = ${f}.union([${f}.eins(".m-kapitel"), ${f}.eins(".m-lesen")]); r.height = Math.min(r.height, 560); return r; })()`, rand: 0 },
    { name: "fliessband-stufen", pfad: "#/fliessband", warten: 2500, ausschnitt: `${f}.eins(".m-band")`, rand: 4 },
    { name: "stellen-liste", pfad: "#/stellen", warten: 2500, ausschnitt: `${f}.alle(".m-ansicht .m-stelle", 3)`, rand: 4 },
    { name: "quellen-neu", pfad: "#/einstellungen/quellen", warten: 2000, vorher: `${f}.setze(document.getElementById("n-typ"), "lokal"); await ${f}.warte(300);`, ausschnitt: `${f}.rect(${f}.mitText(".card", "Neue Quelle"))`, rand: 4 },
    { name: "werkzeuge-mcp", pfad: "#/einstellungen/werkzeuge-verwaltung", warten: 2000, ausschnitt: `${f}.eins(".m-ansicht-koerper .card")`, rand: 4 },
    { name: "anbieter", pfad: "#/einstellungen/anbieter-verwaltung", warten: 2000, ausschnitt: `${f}.eins(".m-ansicht-koerper .card")`, rand: 4 },
    { name: "einstellungen-gruppe", pfad: "#/einstellungen/suche", warten: 2000, ausschnitt: `(() => { const r = ${f}.eins(".m-ansicht-koerper"); r.height = Math.min(r.height, 520); return r; })()`, rand: 0 },
    { name: "umzug", pfad: "#/einstellungen/umzug", warten: 2000, ausschnitt: `${f}.eins(".m-ansicht-koerper .card")`, rand: 4 },
    { name: "hilfe-fenster", pfad: "#/chat", vorher: `localStorage.removeItem("m-hilfe-fenster"); document.querySelector('button[title="Hilfe öffnen oder schließen"]').click(); await ${f}.warte(600); ${f}.setze(document.querySelector(".m-hilfe-suchfeld input"), "Umfang"); await ${f}.warte(500);`, ausschnitt: `${f}.eins(".m-hilfe")`, rand: 0 },
    { name: "spieler", pfad: "#/bibliothek", warten: 2500, vorher: `document.querySelector('button[title="Abspielen"]').click(); await ${f}.warte(2500);`, ausschnitt: `${f}.eins(".m-spieler")`, rand: 0 },
  ];
}

// ---------------------------------------------------------------- DevTools-Verbindung
class DevTools {
  constructor(ws) {
    this.ws = ws;
    this.nr = 0;
    this.offen = new Map();
    ws.addEventListener("message", (e) => {
      const n = JSON.parse(e.data);
      if (n.id && this.offen.has(n.id)) {
        const { ok, nein } = this.offen.get(n.id);
        this.offen.delete(n.id);
        n.error ? nein(new Error(n.error.message)) : ok(n.result);
      }
    });
  }
  ruf(methode, params = {}) {
    const id = ++this.nr;
    return new Promise((ok, nein) => {
      this.offen.set(id, { ok, nein });
      this.ws.send(JSON.stringify({ id, method: methode, params }));
    });
  }
  async werte(ausdruck) {
    const r = await this.ruf("Runtime.evaluate", { expression: ausdruck, awaitPromise: true, returnByValue: true });
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.exception?.description ?? r.exceptionDetails.text);
    return r.result.value;
  }
}

const schlaf = (ms) => new Promise((r) => setTimeout(r, ms));

async function chromeStarten(profil) {
  const kind = spawn(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--hide-scrollbars",
      "--mute-audio",
      "--autoplay-policy=no-user-gesture-required",
      `--remote-debugging-port=${PORT}`,
      "--remote-allow-origins=*",
      `--user-data-dir=${profil}`,
      `--window-size=${BREITE},${HOEHE}`,
      "about:blank",
    ],
    { stdio: "ignore" },
  );
  for (let i = 0; i < 50; i++) {
    try {
      const liste = await (await fetch(`http://127.0.0.1:${PORT}/json`)).json();
      const seite = liste.find((z) => z.type === "page");
      if (seite) return { kind, ws: seite.webSocketDebuggerUrl };
    } catch {
      // Chrome startet noch
    }
    await schlaf(200);
  }
  kind.kill();
  throw new Error("Chrome antwortet nicht auf dem Debug-Port");
}

async function daten() {
  const hole = async (p) => (await fetch(`${BASIS}/api${p}`)).json();
  const unterhaltungen = (await hole("/chat/unterhaltungen?je_seite=100")).eintraege ?? [];
  const mitAntwort = unterhaltungen.find((u) => u.nachrichten >= 2) ?? unterhaltungen[0];
  const videos = (await hole("/videos?stufe=eingebettet&je_seite=1")).eintraege ?? [];
  const dokumente = (await hole("/dokumente?je_seite=1")).eintraege ?? [];
  return { unterhaltung: mitAntwort?.id ?? "", video: videos[0]?.id ?? "", dokument: dokumente[0]?.id ?? "" };
}

async function main() {
  fs.mkdirSync(ZIEL, { recursive: true });
  const d = await daten();
  const profil = fs.mkdtempSync(path.join(os.tmpdir(), "morf-fotos-"));
  const { kind, ws: adresse } = await chromeStarten(profil);
  const ws = new WebSocket(adresse);
  await new Promise((ok, nein) => {
    ws.addEventListener("open", ok);
    ws.addEventListener("error", nein);
  });
  const dt = new DevTools(ws);
  let fehler = 0;
  const masse = fs.existsSync(MASSE) ? JSON.parse(fs.readFileSync(MASSE, "utf8")) : {};
  try {
    await dt.ruf("Page.enable");
    await dt.ruf("Emulation.setDeviceMetricsOverride", { width: BREITE, height: HOEHE, deviceScaleFactor: SCHAERFE, mobile: false });
    // Erst einmal laden, damit Schriften und Daten da sind.
    await dt.ruf("Page.navigate", { url: `${BASIS}/#/chat` });
    await schlaf(3000);
    for (const m of motive(d)) {
      if (NUR.length && !NUR.includes(m.name)) continue;
      try {
        await dt.ruf("Page.navigate", { url: `${BASIS}/${m.pfad}` });
        await schlaf(m.warten ?? 1800);
        await dt.werte(HELFER);
        if (m.vorher) await dt.werte(`(async () => { ${m.vorher} })()`);
        await dt.werte(`${"window.__foto"}.thema("light")`);
        await schlaf(250);
        const r = await dt.werte(m.ausschnitt);
        const rand = m.rand ?? 0;
        const clip = { x: Math.max(0, r.x - rand), y: Math.max(0, r.y - rand), width: Math.min(BREITE, r.width + 2 * rand), height: Math.min(HOEHE, r.height + 2 * rand), scale: 1 };
        // Derselbe Ausschnitt in beiden Themen: erst hell, dann dunkel, ohne neu zu messen.
        const hell = await dt.ruf("Page.captureScreenshot", { format: "png", clip, captureBeyondViewport: false });
        fs.writeFileSync(path.join(ZIEL, `${m.name}.png`), Buffer.from(hell.data, "base64"));
        await dt.werte(`${"window.__foto"}.thema("dark")`);
        await schlaf(350);
        const dunkel = await dt.ruf("Page.captureScreenshot", { format: "png", clip, captureBeyondViewport: false });
        fs.writeFileSync(path.join(ZIEL, `${m.name}-dunkel.png`), Buffer.from(dunkel.data, "base64"));
        await dt.werte(`${"window.__foto"}.thema("light")`);
        masse[m.name] = { breite: Math.round(clip.width), hoehe: Math.round(clip.height) };
        console.log(`${m.name}: ${Math.round(clip.width)} x ${Math.round(clip.height)} (hell und dunkel)`);
      } catch (e) {
        fehler++;
        console.error(`${m.name}: FEHLER ${e.message}`);
      }
    }
  } finally {
    fs.writeFileSync(MASSE, JSON.stringify(Object.fromEntries(Object.entries(masse).sort()), null, 2) + "\n");
    ws.close();
    kind.kill();
    await schlaf(500); // Chrome schreibt beim Beenden noch ins Profil
    fs.rmSync(profil, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
  }
  if (fehler) process.exitCode = 1;
}

main().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
