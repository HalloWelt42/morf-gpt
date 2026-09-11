<script lang="ts">
  // Der Chat: Unterhaltungen links, Verlauf und Eingabe in der Mitte, Suchleiste und
  // Fundstellen rechts. Die Antwort entsteht nur aus den rechts ausgewählten Stellen.
  import { onMount, tick } from "svelte";
  import { api, postStrom } from "../lib/api";
  import type { DokumentEintrag, EinsetzbaresWerkzeug, Nachricht, Seite, SerieEintrag, Stelle, SucheAusgabe, Suchparameter, Unterhaltung, UnterhaltungDetail, Werkzeugaufruf } from "../lib/typen";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { rendereMarkdown } from "../lib/markdown";
  import { uhrzeit, vorZeit, zahl } from "../lib/format";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import StelleKarte from "../lib/komponenten/StelleKarte.svelte";
  import Bestaetigung from "../lib/komponenten/Bestaetigung.svelte";

  let { id = "" }: { id?: string } = $props();

  // --- Zustand ---------------------------------------------------------------
  let unterhaltungen = $state<Unterhaltung[]>([]);
  let aktiv = $state<UnterhaltungDetail | null>(null);
  let verlauf = $state<Nachricht[]>([]);
  let frage = $state("");
  let laeuft = $state(false);
  let abbrechen: (() => void) | null = null;
  let stellen = $state<Stelle[]>([]);
  let abgewaehlt = $state<Set<string>>(new Set());
  let hinweise = $state<string[]>([]);
  let hervor = $state<number | null>(null);
  let nurSucheErgebnis = $state(false);
  let serien = $state<SerieEintrag[]>([]);
  let verlaufFeld = $state<HTMLDivElement | null>(null);
  let eingabe = $state<HTMLTextAreaElement | null>(null);
  let loeschDialog = $state(false);
  let umbenennen = $state(false);
  let neuerTitel = $state("");
  let bibliothekStand = $state<{ eingebettet: number; ausgewaehlt: number; chunks: number } | null>(null);
  let werkzeuge = $state<EinsetzbaresWerkzeug[]>([]);
  let gewaehlteWerkzeuge = $state<Set<string>>(new Set());
  let werkzeugwahl = $state<"nutzer" | "modell">("nutzer");
  let werkzeugwahlVorgabe = "nutzer";
  let aufrufe = $state<Werkzeugaufruf[]>([]);
  let werkzeugeOffen = $state(true);

  const VORGABEN: Suchparameter = {
    treffer: 8,
    nachbarn: 0,
    max_je_video: 3,
    mindest_aehnlichkeit: 0.45,
    neubewertung: "aus",
    kandidaten_faktor: 4,
    serie: "",
    von: null,
    bis: null,
    video_ids: [],
    werkart: "",
    dokument_ids: [],
  };
  let parameter = $state<Suchparameter>({ ...VORGABEN });
  let jahr = $state("");
  // Werke-Filter: "" (alles), "video", "dokument" oder "dok:<kennung>" für ein einzelnes Dokument.
  let werkwahl = $state("");
  let dokumente = $state<DokumentEintrag[]>([]);

  function werkwahlAnwenden(): void {
    if (werkwahl.startsWith("dok:")) {
      parameter.werkart = "dokument";
      parameter.dokument_ids = [werkwahl.slice(4)];
    } else {
      parameter.werkart = werkwahl as "" | "video" | "dokument";
      parameter.dokument_ids = [];
    }
  }

  function werkwahlAusParametern(): void {
    const ids = parameter.dokument_ids ?? [];
    werkwahl = ids.length === 1 ? `dok:${ids[0]}` : (parameter.werkart ?? "");
  }
  const jahre = $derived.by(() => {
    const aus: number[] = [];
    const jetzt = new Date().getFullYear();
    for (let j = jetzt; j >= 2020; j--) aus.push(j);
    return aus;
  });

  const gewaehlteIds = $derived(stellen.filter((s) => !abgewaehlt.has(s.chunk_id)).map((s) => s.chunk_id));

  // --- Laden -------------------------------------------------------------------
  async function ladeListe(): Promise<void> {
    try {
      const s = await api.get<{ eintraege: Unterhaltung[] }>("/chat/unterhaltungen?je_seite=200");
      unterhaltungen = s.eintraege;
    } catch (e) {
      meldeFehler(e, "Unterhaltungen laden");
    }
  }

  async function ladeVorgaben(): Promise<void> {
    try {
      const w = await api.get<Record<string, unknown>>("/einstellungen/werte");
      VORGABEN.treffer = Number(w["suche.treffer"]);
      VORGABEN.nachbarn = Number(w["suche.nachbarn"]);
      VORGABEN.max_je_video = Number(w["suche.max_je_video"]);
      VORGABEN.mindest_aehnlichkeit = Number(w["suche.mindest_aehnlichkeit"]);
      VORGABEN.neubewertung = String(w["suche.neubewertung"]);
      VORGABEN.kandidaten_faktor = Number(w["suche.kandidaten_faktor"]);
      werkzeugwahlVorgabe = String(w["chat.werkzeugwahl"] ?? "nutzer");
      if (!aktiv) {
        parameter = { ...VORGABEN };
        werkzeugwahl = werkzeugwahlVorgabe as "nutzer" | "modell";
      }
    } catch {
      // Vorgaben aus dem Code bleiben
    }
    try {
      werkzeuge = await api.get<EinsetzbaresWerkzeug[]>("/werkzeuge/einsetzbar");
      if (!aktiv) gewaehlteWerkzeuge = new Set(werkzeuge.filter((w) => w.vorausgewaehlt).map((w) => w.kennung));
    } catch {
      werkzeuge = [];
    }
    try {
      serien = await api.get<SerieEintrag[]>("/videos/serien");
      dokumente = (await api.get<Seite<DokumentEintrag>>("/dokumente?je_seite=200")).eintraege;
      const u = await api.get<{ videos_ausgewaehlt: number; chunks: number; stufen: { stufe: string; anzahl: number }[] }>("/system/uebersicht");
      bibliothekStand = { eingebettet: u.stufen.find((s) => s.stufe === "eingebettet")?.anzahl ?? 0, ausgewaehlt: u.videos_ausgewaehlt, chunks: u.chunks };
    } catch {
      // nicht kritisch
    }
  }

  async function oeffne(uid: string): Promise<void> {
    if (laeuft) abbrechen?.();
    try {
      aktiv = await api.get<UnterhaltungDetail>(`/chat/unterhaltungen/${uid}`);
      verlauf = aktiv.verlauf;
      parameter = { ...VORGABEN, ...(aktiv.suchparameter as Partial<Suchparameter>) };
      jahr = parameter.von ? parameter.von.slice(0, 4) : "";
      werkwahlAusParametern();
      const gespeichert = aktiv.suchparameter.werkzeuge;
      gewaehlteWerkzeuge = new Set(Array.isArray(gespeichert) ? gespeichert : werkzeuge.filter((w) => w.vorausgewaehlt).map((w) => w.kennung));
      werkzeugwahl = (aktiv.suchparameter.werkzeugwahl ?? werkzeugwahlVorgabe) as "nutzer" | "modell";
      const letzteAntwort = [...verlauf].reverse().find((n) => n.rolle === "assistent");
      aufrufe = (letzteAntwort?.parameter.werkzeugaufrufe as Werkzeugaufruf[] | undefined) ?? [];
      const letzte = [...verlauf].reverse().find((n) => n.rolle === "assistent" && n.stellen.length);
      stellen = letzte ? letzte.stellen : [];
      abgewaehlt = new Set();
      hinweise = [];
      nurSucheErgebnis = false;
      await tick();
      nachUnten();
    } catch (e) {
      meldeFehler(e, "Unterhaltung laden");
      ui.gehe("chat");
    }
  }

  async function neu(): Promise<void> {
    try {
      const u = await api.post<Unterhaltung>("/chat/unterhaltungen", {});
      await ladeListe();
      ui.gehe("chat", u.id);
      await tick();
      eingabe?.focus();
    } catch (e) {
      meldeFehler(e, "Neue Unterhaltung");
    }
  }

  $effect(() => {
    const ziel = id;
    if (ziel && ziel !== aktiv?.id) void oeffne(ziel);
    if (!ziel) {
      aktiv = null;
      verlauf = [];
      stellen = [];
    }
  });

  onMount(() => {
    void ladeVorgaben();
    void ladeListe();
  });

  // --- Fragen ------------------------------------------------------------------
  function nachUnten(): void {
    if (verlaufFeld) verlaufFeld.scrollTop = verlaufFeld.scrollHeight;
  }

  function parameterFuerAnfrage(): Record<string, unknown> {
    const p: Record<string, unknown> = { ...parameter };
    p.von = jahr ? `${jahr}-01-01T00:00:00` : null;
    p.bis = jahr ? `${jahr}-12-31T23:59:59` : null;
    p.werkzeuge = [...gewaehlteWerkzeuge].filter((k) => werkzeuge.some((w) => w.kennung === k));
    p.werkzeugwahl = werkzeugwahl;
    return p;
  }

  async function senden(chunkIds: string[] | null = null, text: string | null = null): Promise<void> {
    const f = (text ?? frage).trim();
    if (!f || laeuft) return;
    if (!aktiv) {
      // Neue Unterhaltung direkt übernehmen statt nachzuladen: Regler, Werkzeugwahl und der
      // gerade entstehende Verlauf bleiben so erhalten, und die Routenbeobachtung lädt nicht erneut.
      const u = await api.post<Unterhaltung>("/chat/unterhaltungen", { suchparameter: parameterFuerAnfrage() });
      aktiv = { ...u, verlauf: [] };
      verlauf = [];
      ui.gehe("chat", u.id);
      void ladeListe();
    }
    if (!aktiv) return;
    const uid = aktiv.id;
    if (text === null) frage = "";
    nurSucheErgebnis = false;
    laeuft = true;
    hervor = null;
    const nutzerRoh: Nachricht = { id: `tmp-${Date.now()}`, rolle: "nutzer", inhalt: f, stellen: [], parameter: {}, modell: "", dauer_ms: null, tokens_ein: null, tokens_aus: null, fehler: "", erstellt: new Date().toISOString() };
    const antwortRoh: Nachricht = { ...nutzerRoh, id: `tmp-a-${Date.now()}`, rolle: "assistent", inhalt: "", streamt: true };
    verlauf = [...verlauf, nutzerRoh, antwortRoh];
    // Nur Schreibzugriffe über die reaktiven Stellvertreter im Verlauf werden gerendert.
    const nutzer = verlauf[verlauf.length - 2];
    const antwort = verlauf[verlauf.length - 1];
    await tick();
    nachUnten();
    abbrechen = postStrom(
      `/chat/unterhaltungen/${uid}/fragen`,
      { frage: f, parameter: parameterFuerAnfrage(), chunk_ids: chunkIds },
      (e) => {
        if (e.art === "treffer") {
          stellen = (e.daten.stellen as Stelle[]) ?? [];
          abgewaehlt = new Set();
          hinweise = (e.daten.hinweise as string[]) ?? [];
          antwort.stellen = stellen;
          aufrufe = (e.daten.werkzeugaufrufe as Werkzeugaufruf[]) ?? [];
          antwort.parameter = { ...antwort.parameter, werkzeugaufrufe: aufrufe };
          nutzer.id = String(e.daten.nachricht_id ?? nutzer.id);
        } else if (e.art === "delta") {
          antwort.inhalt += String(e.daten.text ?? "");
          verlauf = [...verlauf];
          nachUnten();
        } else if (e.art === "fertig") {
          antwort.id = String(e.daten.nachricht_id ?? antwort.id);
          antwort.modell = String(e.daten.modell ?? "");
          antwort.dauer_ms = (e.daten.dauer_ms as number) ?? null;
          antwort.tokens_ein = (e.daten.tokens_ein as number | null) ?? null;
          antwort.tokens_aus = (e.daten.tokens_aus as number | null) ?? null;
          antwort.streamt = false;
          if (aktiv && e.daten.unterhaltung_titel) aktiv.titel = String(e.daten.unterhaltung_titel);
          verlauf = [...verlauf];
        } else if (e.art === "fehler") {
          antwort.fehler = String(e.daten.text ?? "Unbekannter Fehler");
          antwort.streamt = false;
          verlauf = [...verlauf];
          meldungen.fehler(antwort.fehler);
        }
      },
      (fehler) => {
        laeuft = false;
        abbrechen = null;
        antwort.streamt = false;
        if (fehler) {
          antwort.fehler = fehler.message;
          meldeFehler(fehler, "Antwort");
        }
        verlauf = [...verlauf];
        void ladeListe();
      },
    );
  }

  function stoppen(): void {
    abbrechen?.();
  }

  async function nurSuchen(): Promise<void> {
    const f = frage.trim();
    if (!f || laeuft) return;
    laeuft = true;
    try {
      const s = await api.post<SucheAusgabe>("/chat/suche", { frage: f, parameter: parameterFuerAnfrage(), unterhaltung_id: aktiv?.id ?? null });
      stellen = s.stellen;
      abgewaehlt = new Set();
      hinweise = s.hinweise;
      nurSucheErgebnis = true;
    } catch (e) {
      meldeFehler(e, "Suche");
    } finally {
      laeuft = false;
    }
  }

  async function ausAuswahlAntworten(): Promise<void> {
    await senden(gewaehlteIds, frage);
  }

  async function neuAntworten(): Promise<void> {
    const letzteFrage = [...verlauf].reverse().find((n) => n.rolle === "nutzer");
    if (!letzteFrage) return;
    await senden(gewaehlteIds, letzteFrage.inhalt);
  }

  function umschalten(chunkId: string): void {
    const neu = new Set(abgewaehlt);
    if (neu.has(chunkId)) neu.delete(chunkId);
    else neu.add(chunkId);
    abgewaehlt = neu;
  }

  function werkzeugUmschalten(kennung: string): void {
    const neu = new Set(gewaehlteWerkzeuge);
    if (neu.has(kennung)) neu.delete(kennung);
    else neu.add(kennung);
    gewaehlteWerkzeuge = neu;
  }

  function taste(e: KeyboardEvent): void {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void senden();
    }
  }

  function zitatKlick(e: MouseEvent, n: Nachricht): void {
    const a = (e.target as HTMLElement).closest("a.m-zitat") as HTMLAnchorElement | null;
    if (!a) return;
    e.preventDefault();
    const nr = Number(a.dataset.nr);
    if (n.stellen.length && n.stellen !== stellen) {
      stellen = n.stellen;
      abgewaehlt = new Set();
    }
    hervor = nr;
    document.getElementById(`stelle-${nr}`)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  async function titelSpeichern(): Promise<void> {
    if (!aktiv || !neuerTitel.trim()) return;
    try {
      const u = await api.put<Unterhaltung>(`/chat/unterhaltungen/${aktiv.id}`, { titel: neuerTitel.trim() });
      aktiv.titel = u.titel;
      umbenennen = false;
      await ladeListe();
    } catch (e) {
      meldeFehler(e, "Umbenennen");
    }
  }

  async function loeschen(): Promise<void> {
    if (!aktiv) return;
    try {
      await api.del(`/chat/unterhaltungen/${aktiv.id}`);
      loeschDialog = false;
      aktiv = null;
      await ladeListe();
      ui.gehe("chat");
    } catch (e) {
      meldeFehler(e, "Löschen");
    }
  }

  function exportieren(): void {
    if (!aktiv) return;
    const zeilen = [`# ${aktiv.titel}`, ""];
    for (const n of verlauf) {
      zeilen.push(n.rolle === "nutzer" ? `**Frage:** ${n.inhalt}` : n.inhalt, "");
      if (n.rolle === "assistent" && n.stellen.length) {
        zeilen.push("Stellen:");
        n.stellen.forEach((s, i) =>
          zeilen.push(
            s.art === "dokument"
              ? `${i + 1}. ${s.titel}${s.abschnitt ? ` (Kapitel ${s.abschnitt})` : ""}`
              : `${i + 1}. ${s.titel} (${s.serie ? `${s.serie}#${s.folge_nr} ` : ""}${Math.floor(s.start_s / 60)}:${String(Math.floor(s.start_s % 60)).padStart(2, "0")})`,
          ),
        );
        zeilen.push("");
      }
    }
    void navigator.clipboard.writeText(zeilen.join("\n")).then(
      () => meldungen.gut("Unterhaltung als Markdown in die Zwischenablage kopiert"),
      () => meldungen.fehler("Zwischenablage nicht verfügbar"),
    );
  }

  const beispiele = [
    "Was meint morf mit Kasualisierung?",
    "Warum hängen Wettbewerb und Fortschritt laut morf nicht zusammen?",
    "Wie erklärt morf Bewusstsein und Willen?",
  ];
</script>

<aside class="m-seite links">
  <div class="m-seite-kopf">
    <i class="fa-solid fa-comments"></i> Unterhaltungen
    <button class="btn btn-sm btn-primary ms-auto" title="Neue Unterhaltung" onclick={neu}><i class="fa-solid fa-plus"></i> Neu</button>
  </div>
  <div class="m-seite-koerper p-0">
    <div class="list-group list-group-flush">
      {#each unterhaltungen as u (u.id)}
        <a href="#/chat/{u.id}" class="list-group-item list-group-item-action" class:active={aktiv?.id === u.id} onclick={(e) => { e.preventDefault(); ui.gehe("chat", u.id); }}>
          <div class="fw-semibold text-truncate">{u.titel}</div>
          <small class={aktiv?.id === u.id ? "opacity-75" : "text-secondary"}>{vorZeit(u.letzte ?? u.aktualisiert)} - {u.nachrichten} {u.nachrichten === 1 ? "Nachricht" : "Nachrichten"}</small>
        </a>
      {/each}
      {#if !unterhaltungen.length}
        <div class="p-3 text-secondary">Noch keine Unterhaltung.</div>
      {/if}
    </div>
  </div>
</aside>

<section class="m-chat">
  <div class="m-ansicht-kopf">
    {#if aktiv && umbenennen}
      <input class="form-control" style="max-width: 520px" bind:value={neuerTitel} onkeydown={(e) => e.key === "Enter" && titelSpeichern()} title="Neuer Titel der Unterhaltung; Eingabe speichert" />
      <button class="btn btn-sm btn-primary" onclick={titelSpeichern}>Speichern</button>
      <button class="btn btn-sm btn-outline-secondary" onclick={() => (umbenennen = false)}>Abbrechen</button>
    {:else}
      <h1>{aktiv?.titel ?? "Chat"}</h1>
      <span class="m-unter">
        {#if aktiv}Antworten aus den rechts ausgewählten Stellen{:else}Frage stellen, belegte Antwort erhalten{/if}
      </span>
      <InfoKnopf anker="chat" />
    {/if}
    <span class="m-luecke"></span>
    {#if aktiv && !umbenennen}
      <button class="btn btn-sm btn-outline-secondary" title="Unterhaltung umbenennen" onclick={() => { neuerTitel = aktiv?.titel ?? ""; umbenennen = true; }}><i class="fa-solid fa-pen"></i></button>
      <button class="btn btn-sm btn-outline-secondary" title="Als Markdown kopieren" onclick={exportieren}><i class="fa-solid fa-file-export"></i> Export</button>
      <button class="btn btn-sm btn-outline-danger" title="Unterhaltung löschen" onclick={() => (loeschDialog = true)}><i class="fa-solid fa-trash"></i></button>
    {/if}
  </div>

  <div class="m-chat-verlauf" bind:this={verlaufFeld}>
    {#if !verlauf.length}
      <div class="m-leer">
        <i class="fa-solid fa-comment"></i>
        <div class="fs-5 mb-3">Stell eine Frage an die Bibliothek.</div>
        {#if bibliothekStand}
          <div class="text-secondary mb-4">{zahl(bibliothekStand.eingebettet)} von {zahl(bibliothekStand.ausgewaehlt)} Videos eingebettet - die Antwort kennt bislang {zahl(bibliothekStand.chunks)} Stellen.</div>
        {/if}
        <div class="d-flex flex-column gap-2 align-items-center">
          {#each beispiele as b}
            <button class="btn btn-outline-secondary btn-lg" onclick={() => { frage = b; void senden(); }}>{b}</button>
          {/each}
        </div>
      </div>
    {:else}
      {#each verlauf as n (n.id)}
        <div class="m-nachricht {n.rolle}">
          <div class="rolle">{n.rolle === "nutzer" ? "Du" : "m"}</div>
          <div class="koerper">
            {#if n.rolle === "nutzer"}
              <div class="text">{n.inhalt}</div>
              <div class="meta"><span>{uhrzeit(n.erstellt)}</span></div>
            {:else}
              <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
              <div class="text" onclick={(e) => zitatKlick(e, n)}>
                {#if n.inhalt}{@html rendereMarkdown(n.inhalt)}{/if}
                {#if n.streamt}<span class="text-secondary">&#9646;</span>{/if}
                {#if n.fehler}<div class="alert alert-danger py-2 mt-2"><i class="fa-solid fa-triangle-exclamation"></i> {n.fehler}</div>{/if}
              </div>
              <div class="meta">
                {#if n.streamt}
                  <span><i class="fa-solid fa-circle-notch fa-spin"></i> antwortet ...</span>
                  {#if n.stellen.length}<span>Stellen ausgewählt: {n.stellen.length}</span>{/if}
                  <button class="btn btn-sm btn-outline-danger ms-auto" onclick={stoppen} title="Die laufende Antwort abbrechen; der bisherige Text bleibt stehen"><i class="fa-solid fa-stop"></i> Stopp</button>
                {:else}
                  {#if n.modell}<span><i class="fa-solid fa-microchip"></i> {n.modell}</span>{/if}
                  {#if n.dauer_ms !== null}<span><i class="fa-regular fa-clock"></i> {(n.dauer_ms / 1000).toFixed(1).replace(".", ",")} Sekunden</span>{/if}
                  {#if n.stellen.length}<span><i class="fa-solid fa-align-left"></i> {n.stellen.length} Stellen</span>{/if}
                  {#each (n.parameter.werkzeugaufrufe as Werkzeugaufruf[] | undefined) ?? [] as a}
                    <span title={`Argumente: ${JSON.stringify(a.argumente)}${a.fehler ? `\nFehler: ${a.fehler}` : ""}`} class:text-danger={!!a.fehler}><i class="fa-solid fa-plug"></i> {a.titel} ({(a.dauer_ms / 1000).toFixed(1).replace(".", ",")} s{a.fehler ? ", Fehler" : ""})</span>
                  {/each}
                  <span class="ms-auto d-flex gap-1">
                    <button class="btn btn-sm btn-outline-secondary" title="Antwort kopieren" onclick={() => navigator.clipboard.writeText(n.inhalt).then(() => meldungen.gut("Antwort kopiert"))}><i class="fa-regular fa-copy"></i></button>
                    {#if n.stellen.length && !laeuft}
                      <button class="btn btn-sm btn-outline-secondary" title="Mit den ausgewählten Stellen neu antworten lassen" onclick={() => { stellen = n.stellen; void neuAntworten(); }}><i class="fa-solid fa-rotate-right"></i> Neu antworten</button>
                    {/if}
                  </span>
                {/if}
              </div>
            {/if}
          </div>
        </div>
      {/each}
      {#if nurSucheErgebnis && !laeuft}
        <div class="m-nachricht assistent">
          <div class="rolle">m</div>
          <div class="koerper">
            <div class="card">
              <div class="card-body">
                <div class="fs-5 mb-2">{stellen.length} Stellen gefunden - prüfe die Auswahl rechts und lass dann antworten.</div>
                <button class="btn btn-primary btn-lg" onclick={ausAuswahlAntworten} disabled={!gewaehlteIds.length} title="Antwort nur aus den rechts ausgewählten Stellen erzeugen, ohne neue Suche"><i class="fa-solid fa-paper-plane"></i> Aus {gewaehlteIds.length} ausgewählten Stellen antworten</button>
              </div>
            </div>
          </div>
        </div>
      {/if}
    {/if}
  </div>

  <div class="m-chat-eingabe">
    <div class="feld">
      <textarea class="form-control" rows="2" title="Frage eingeben; Eingabe sendet, Umschalt + Eingabe macht eine neue Zeile" placeholder="Frage an die Bibliothek ... (Umschalt + Eingabe für eine neue Zeile)" bind:value={frage} bind:this={eingabe} onkeydown={taste} disabled={laeuft && !nurSucheErgebnis}></textarea>
      <button class="btn btn-outline-secondary btn-lg" title="Nur suchen, noch nicht antworten" onclick={nurSuchen} disabled={laeuft || !frage.trim()}><i class="fa-solid fa-magnifying-glass"></i></button>
      <button class="btn btn-primary btn-lg" title="Senden" onclick={() => senden()} disabled={laeuft || !frage.trim()}><i class="fa-solid fa-paper-plane"></i></button>
    </div>
    <div class="hinweis">Die Antwort entsteht ausschließlich aus den rechts ausgewählten Stellen. Mit der Lupe erst suchen, Stellen prüfen, dann antworten lassen.</div>
  </div>
</section>

<aside class="m-seite">
  <div class="m-seite-kopf"><i class="fa-solid fa-magnifying-glass"></i> Suche und Stellen <InfoKnopf anker="suche-breite" /></div>
  <div class="m-seite-koerper p-0">
    <div class="m-parameter">
      <h6>Breite <InfoKnopf anker="suche-breite" /></h6>
      <div class="m-regler">
        <label for="p-treffer">Treffer</label><span class="wert">{parameter.treffer}</span>
        <input id="p-treffer" type="range" class="form-range" min="1" max="50" bind:value={parameter.treffer} title="Wie viele Stellen höchstens in die Antwort eingehen (1 bis 50). Mehr Stellen geben dem Modell mehr Material, machen die Antwort aber breiter." />
      </div>
      <div class="m-regler">
        <label for="p-nachbarn">Nachbarstücke je Treffer</label><span class="wert">{parameter.nachbarn}</span>
        <input id="p-nachbarn" type="range" class="form-range" min="0" max="3" bind:value={parameter.nachbarn} title="So viele angrenzende Stücke desselben Werks werden jeder Stelle vorn und hinten angefügt (0 bis 3), damit ein Gedanke nicht am Schnitt endet." />
      </div>
      <div class="m-regler">
        <label for="p-jevideo">Höchstens je Werk</label><span class="wert">{parameter.max_je_video === 0 ? "keine Grenze" : parameter.max_je_video}</span>
        <input id="p-jevideo" type="range" class="form-range" min="0" max="10" bind:value={parameter.max_je_video} title="Höchstens so viele Stellen aus demselben Video oder Dokument (0 = keine Grenze). Sorgt für Vielfalt, damit nicht ein einziges Werk die Antwort füllt." />
      </div>
    </div>
    <div class="m-parameter">
      <h6>Genauigkeit <InfoKnopf anker="suche-genauigkeit" /></h6>
      <div class="m-regler">
        <label for="p-min">Mindestähnlichkeit</label><span class="wert">{Number(parameter.mindest_aehnlichkeit).toFixed(2).replace(".", ",")}</span>
        <input id="p-min" type="range" class="form-range" min="0" max="1" step="0.01" title="Stellen mit geringerer Ähnlichkeit zur Frage (0 bis 1) werden verworfen. 0,45 ist ein guter Anfang; bei sehr spezifischen Fragen hilft ein höherer Wert." bind:value={parameter.mindest_aehnlichkeit} />
      </div>
      <div class="mb-1">
        <label class="form-label small mb-1" for="p-neu">Neu-Bewertung</label>
        <select id="p-neu" class="form-select form-select-sm" bind:value={parameter.neubewertung} title="Ordnet die gefundenen Kandidaten in einem zweiten Durchgang genauer: Aus ist am schnellsten; Cross-Encoder heißt, ein kleines lokales Modell liest Frage und Kandidat gemeinsam und bewertet die Passung (etwa eine Sekunde); das Sprachmodell ist am genauesten, aber langsam.">
          <option value="aus">Aus</option>
          <option value="crossencoder">Cross-Encoder (lokal, etwa eine Sekunde)</option>
          <option value="sprachmodell">Sprachmodell (sehr genau, langsam)</option>
        </select>
      </div>
    </div>
    {#if werkzeuge.length}
      <div class="m-parameter">
        <h6 class="d-flex align-items-center gap-2">
          <button class="btn btn-sm btn-link p-0 text-secondary" onclick={() => (werkzeugeOffen = !werkzeugeOffen)} title={werkzeugeOffen ? "Einklappen" : "Ausklappen"}><i class="fa-solid {werkzeugeOffen ? 'fa-caret-down' : 'fa-caret-right'}"></i></button>
          Weitere Quellen ({gewaehlteWerkzeuge.size} von {werkzeuge.length}) <InfoKnopf anker="werkzeuge" />
        </h6>
        {#if werkzeugeOffen}
          <div class="btn-group btn-group-sm w-100 mb-2" role="group" title="Wer entscheidet, welche Werkzeuge laufen">
            <button class="btn btn-outline-secondary" class:active={werkzeugwahl === "nutzer"} onclick={() => (werkzeugwahl = "nutzer")} title="Alle unten eingeschalteten Werkzeuge laufen vor jeder Antwort; ihre Ergebnisse kommen als weitere Stellen dazu.">Ich wähle</button>
            <button class="btn btn-outline-secondary" class:active={werkzeugwahl === "modell"} onclick={() => (werkzeugwahl = "modell")} title="Das Sprachmodell entscheidet je Frage selbst, welche der eingeschalteten Werkzeuge es aufruft (Funktionsaufrufe, mehrere Runden möglich).">Modell wählt</button>
          </div>
          <div class="small text-secondary mb-2">{werkzeugwahl === "nutzer" ? "Alle eingeschalteten Werkzeuge laufen vor jeder Antwort." : "Das Modell entscheidet je Frage, welche der eingeschalteten Werkzeuge es aufruft."}</div>
          <div class="d-flex gap-1 mb-2">
            <button class="btn btn-sm btn-outline-secondary py-0" onclick={() => (gewaehlteWerkzeuge = new Set(werkzeuge.map((w) => w.kennung)))} title="Alle Werkzeuge einschalten">alle</button>
            <button class="btn btn-sm btn-outline-secondary py-0" onclick={() => (gewaehlteWerkzeuge = new Set())} title="Alle Werkzeuge ausschalten; die Antwort kommt dann nur aus der Bibliothek">keine</button>
          </div>
          {#each werkzeuge as w (w.kennung)}
            <div class="form-check form-switch mb-1">
              <input class="form-check-input" type="checkbox" role="switch" id="wz-{w.kennung}" checked={gewaehlteWerkzeuge.has(w.kennung)} onchange={() => werkzeugUmschalten(w.kennung)} title={w.beschreibung || w.titel} />
              <label class="form-check-label small" for="wz-{w.kennung}" title={w.beschreibung}>{w.titel}</label>
            </div>
          {/each}
        {/if}
      </div>
    {/if}
    <div class="m-parameter">
      <h6>Filter</h6>
      <div class="row g-2">
        <div class="col-12">
          <label class="form-label small mb-1" for="p-werke">Werke <InfoKnopf anker="dokumente" finde="Im Chat" /></label>
          <select id="p-werke" class="form-select form-select-sm" bind:value={werkwahl} onchange={werkwahlAnwenden} title="Woraus die Antwort belegt wird: aus Videos und Dokumenten, nur aus Videos, nur aus Dokumenten oder aus einem einzelnen Dokument.">
            <option value="">Videos und Dokumente</option>
            <option value="video">Nur Videos</option>
            <option value="dokument">Nur Dokumente</option>
            {#each dokumente as d (d.id)}<option value={"dok:" + d.id}>Nur: {d.titel}</option>{/each}
          </select>
        </div>
        <div class="col-6">
          <label class="form-label small mb-1" for="p-serie">Serie</label>
          <select id="p-serie" class="form-select form-select-sm" bind:value={parameter.serie} title="Nur Videos dieser Serie durchsuchen; Dokumente haben keine Serie und fallen bei gesetzter Serie weg.">
            <option value="">Alle</option>
            {#each serien.filter((s) => s.serie) as s (s.serie)}<option value={s.serie}>{s.serie} ({s.anzahl})</option>{/each}
          </select>
        </div>
        <div class="col-6">
          <label class="form-label small mb-1" for="p-jahr">Zeitraum</label>
          <select id="p-jahr" class="form-select form-select-sm" bind:value={jahr} title="Nur Werke aus diesem Jahr durchsuchen (Datum der Veröffentlichung von Videos und Dokumenten).">
            <option value="">Alle Jahre</option>
            {#each jahre as j}<option value={String(j)}>{j}</option>{/each}
          </select>
        </div>
      </div>
    </div>

    <div class="p-3">
      <div class="d-flex align-items-center mb-2">
        <h6 class="m-0 small text-uppercase text-secondary">Fundstellen ({stellen.length})</h6>
        <span class="ms-auto small text-secondary">{gewaehlteIds.length} ausgewählt</span>
      </div>
      {#each hinweise as h}
        <div class="alert alert-warning py-2 small"><i class="fa-solid fa-circle-info"></i> {h}</div>
      {/each}
      {#if !stellen.length}
        <div class="text-secondary">Noch keine Suche.</div>
      {/if}
      {#each stellen as s, i (s.chunk_id)}
        <StelleKarte stelle={s} nummer={i + 1} gewaehlt={!abgewaehlt.has(s.chunk_id)} hervorgehoben={hervor === i + 1} onUmschalten={() => umschalten(s.chunk_id)} />
      {/each}
    </div>
  </div>
</aside>

<Bestaetigung bind:offen={loeschDialog} titel="Unterhaltung löschen" bestaetigen="Löschen" gefaehrlich onBestaetigen={loeschen}>
  <p>Die Unterhaltung <b>{aktiv?.titel}</b> mit allen Nachrichten wird gelöscht.</p>
</Bestaetigung>
