<script lang="ts">
  // Werkzeuge: fremde Dienste anlegen (HTTP-Dienst, MCP-Server), prüfen, entdeckte Werkzeuge
  // freischalten, Probe mit einer Frage, im Chat vorauswählen.
  import { onMount } from "svelte";
  import { api } from "../../lib/api";
  import type { Werkzeug, WerkzeugEingabe, WerkzeugPruefung, WerkzeugProbe, WerkzeugUebersicht } from "../../lib/typen";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import { vorZeit } from "../../lib/format";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Bestaetigung from "../../lib/komponenten/Bestaetigung.svelte";

  interface Kopfzeile {
    name: string;
    wert: string;
    geheim: boolean;
  }

  let daten = $state<WerkzeugUebersicht | null>(null);
  let bearbeiten = $state<string | null>(null);
  let formular = $state<WerkzeugEingabe>(leer("mcp"));
  let kopfzeilen = $state<Kopfzeile[]>([]);
  let parameterText = $state("");
  let beschaeftigt = $state(false);
  let pruefungen = $state<Record<string, WerkzeugPruefung | "laeuft">>({});
  let proben = $state<Record<string, WerkzeugProbe | "laeuft" | undefined>>({});
  let probeFrage = $state<Record<string, string>>({});
  let probeKennung = $state<Record<string, string>>({});
  let loeschDialog = $state(false);
  let loeschZiel = $state<Werkzeug | null>(null);
  let offen = $state<Record<string, boolean>>({});

  const VORLAGEN: { titel: string; werte: WerkzeugEingabe }[] = [
    {
      titel: "MCP-Server",
      werte: { name: "", typ: "mcp", beschreibung: "", konfiguration: { url: "", transport: "streamable_http", kopfzeilen: [] }, aktiv: true, vorausgewaehlt: false },
    },
    {
      titel: "HTTP-Dienst mit JSON-Antwort",
      werte: { name: "", typ: "http_json", beschreibung: "Sucht im Netz und liefert Treffer mit Text und Adresse", konfiguration: { url: "https://dienst.example/suche?q={frage}", methode: "GET", kopfzeilen: [], rumpf: "", antwort_text: "ergebnisse[].text", antwort_titel: "ergebnisse[].titel", antwort_url: "ergebnisse[].url", parameter: [{ name: "frage", beschreibung: "Die Suchanfrage", pflicht: true }] }, aktiv: true, vorausgewaehlt: false },
    },
  ];

  function leer(typ: "mcp" | "http_json"): WerkzeugEingabe {
    const konfiguration: Record<string, unknown> =
      typ === "mcp"
        ? { url: "", transport: "streamable_http", kopfzeilen: [] }
        : { url: "", methode: "GET", kopfzeilen: [], rumpf: "", antwort_text: "", antwort_titel: "", antwort_url: "", parameter: [{ name: "frage", beschreibung: "Die Suchanfrage oder Frage", pflicht: true }] };
    return { name: "", typ, beschreibung: "", konfiguration, aktiv: true, vorausgewaehlt: false };
  }

  async function laden(): Promise<void> {
    try {
      daten = await api.get<WerkzeugUebersicht>("/werkzeuge");
    } catch (e) {
      meldeFehler(e, "Werkzeuge laden");
    }
  }

  function neu(vorlage?: WerkzeugEingabe): void {
    bearbeiten = "neu";
    formular = vorlage ? JSON.parse(JSON.stringify(vorlage)) : leer("mcp");
    kopfzeilen = ((formular.konfiguration.kopfzeilen as Kopfzeile[] | undefined) ?? []).map((k) => ({ ...k }));
    parameterText = JSON.stringify(formular.konfiguration.parameter ?? [], null, 1);
  }

  function bearbeite(w: Werkzeug): void {
    bearbeiten = w.id;
    formular = { name: w.name, typ: w.typ, beschreibung: w.beschreibung, konfiguration: JSON.parse(JSON.stringify(w.konfiguration)), aktiv: w.aktiv, vorausgewaehlt: w.vorausgewaehlt };
    kopfzeilen = ((w.konfiguration.kopfzeilen as Kopfzeile[] | undefined) ?? []).map((k) => ({ ...k }));
    parameterText = JSON.stringify(w.konfiguration.parameter ?? [{ name: "frage", beschreibung: "Die Suchanfrage oder Frage", pflicht: true }], null, 1);
  }

  function typWechsel(): void {
    const t = formular.typ as "mcp" | "http_json";
    const basis = leer(t);
    formular = { ...basis, name: formular.name, beschreibung: formular.beschreibung, aktiv: formular.aktiv, vorausgewaehlt: formular.vorausgewaehlt };
    kopfzeilen = [];
    parameterText = JSON.stringify(basis.konfiguration.parameter ?? [], null, 1);
  }

  async function speichern(): Promise<void> {
    beschaeftigt = true;
    try {
      const konfiguration: Record<string, unknown> = { ...formular.konfiguration, kopfzeilen: kopfzeilen.filter((k) => k.name.trim()) };
      if (formular.typ === "http_json") {
        try {
          konfiguration.parameter = JSON.parse(parameterText || "[]");
        } catch {
          throw new Error("Die Parameterliste ist kein gültiges JSON");
        }
      }
      const eingabe = { ...formular, konfiguration };
      if (bearbeiten === "neu") await api.post<Werkzeug>("/werkzeuge", eingabe);
      else await api.put<Werkzeug>(`/werkzeuge/${bearbeiten}`, eingabe);
      meldungen.gut("Werkzeug gespeichert");
      bearbeiten = null;
      await laden();
    } catch (e) {
      meldeFehler(e, "Werkzeug speichern");
    } finally {
      beschaeftigt = false;
    }
  }

  async function pruefen(w: Werkzeug): Promise<void> {
    pruefungen[w.id] = "laeuft";
    try {
      pruefungen[w.id] = await api.post<WerkzeugPruefung>(`/werkzeuge/${w.id}/pruefen`);
      await laden();
    } catch (e) {
      pruefungen[w.id] = { ok: false, hinweis: e instanceof Error ? e.message : String(e), entdeckt: [] };
    }
  }

  async function entdecktSchalten(w: Werkzeug, name: string, aktiv: boolean): Promise<void> {
    try {
      await api.put(`/werkzeuge/${w.id}/entdeckt`, { name, aktiv });
      await laden();
    } catch (e) {
      meldeFehler(e, "Freischalten");
    }
  }

  async function probe(w: Werkzeug): Promise<void> {
    proben[w.id] = "laeuft";
    try {
      proben[w.id] = await api.post<WerkzeugProbe>(`/werkzeuge/${w.id}/probe`, { kennung: probeKennung[w.id] || w.einsetzbar[0]?.kennung || null, frage: probeFrage[w.id] || "Wie ist das Wetter heute in Leipzig?" });
    } catch (e) {
      proben[w.id] = undefined;
      meldeFehler(e, `Probe ${w.name}`);
    }
  }

  async function umschalten(w: Werkzeug, feld: "aktiv" | "vorausgewaehlt"): Promise<void> {
    try {
      await api.put(`/werkzeuge/${w.id}`, { name: w.name, typ: w.typ, beschreibung: w.beschreibung, konfiguration: w.konfiguration, aktiv: feld === "aktiv" ? !w.aktiv : w.aktiv, vorausgewaehlt: feld === "vorausgewaehlt" ? !w.vorausgewaehlt : w.vorausgewaehlt });
      await laden();
    } catch (e) {
      meldeFehler(e, "Ändern");
    }
  }

  async function loeschen(): Promise<void> {
    if (!loeschZiel) return;
    beschaeftigt = true;
    try {
      await api.del(`/werkzeuge/${loeschZiel.id}`);
      meldungen.gut("Werkzeug gelöscht");
      loeschDialog = false;
      await laden();
    } catch (e) {
      meldeFehler(e, "Löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  onMount(() => void laden());
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <h1>Werkzeuge</h1>
    <span class="m-unter">Fremde Dienste, die der Chat neben der Bibliothek befragen kann</span>
    <InfoKnopf anker="werkzeuge" />
    <span class="m-luecke"></span>
    <div class="dropdown">
      <button class="btn btn-sm btn-primary dropdown-toggle" data-bs-toggle="dropdown"><i class="fa-solid fa-plus"></i> Neues Werkzeug</button>
      <ul class="dropdown-menu dropdown-menu-end">
        {#each VORLAGEN as v}<li><button class="dropdown-item" onclick={() => neu(v.werte)}>{v.titel}</button></li>{/each}
      </ul>
    </div>
  </div>
  <div class="m-ansicht-koerper">
    {#if !daten}
      <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Werkzeuge werden geladen.</div>
    {:else}
      {#if bearbeiten === "neu"}
        <div class="card mb-3 border-primary"><div class="card-header fw-semibold">Neues Werkzeug</div><div class="card-body">{@render formularInhalt()}</div></div>
      {/if}
      {#if !daten.werkzeuge.length && bearbeiten !== "neu"}
        <div class="m-leer"><i class="fa-solid fa-plug"></i>Noch kein Werkzeug. Über "Neues Werkzeug" einen MCP-Server oder einen HTTP-Dienst anbinden.</div>
      {/if}
      {#each daten.werkzeuge as w (w.id)}
        <div class="card mb-3" class:opacity-50={!w.aktiv}>
          <div class="card-body">
            <div class="d-flex align-items-start gap-3 flex-wrap">
              <div class="flex-grow-1" style="min-width: 0">
                <div class="d-flex align-items-center gap-2 flex-wrap">
                  {#if w.pruefung && "ok" in w.pruefung}<span class="m-status-punkt" class:aus={!w.pruefung.ok}></span>{/if}
                  <span class="fs-5 fw-semibold">{w.name}</span>
                  <span class="badge text-bg-secondary">{w.typ_titel}</span>
                  {#if w.vorausgewaehlt}<span class="badge text-bg-success">im Chat vorausgewählt</span>{/if}
                  {#if !w.aktiv}<span class="badge text-bg-dark">deaktiviert</span>{/if}
                </div>
                <div class="text-secondary mt-1">{w.beschreibung || "Ohne Beschreibung - das Modell weiß dann nicht, wofür das Werkzeug taugt."}</div>
                <div class="small text-secondary mt-1">{String(w.konfiguration.url ?? "")}{w.typ === "mcp" ? ` · ${daten.transporte[String(w.konfiguration.transport ?? "")] ?? ""}` : ` · ${String(w.konfiguration.methode ?? "GET")}`}</div>
                {#if w.zuletzt_geprueft}
                  <div class="small mt-1" class:text-success={w.pruefung.ok} class:text-danger={!w.pruefung.ok}><i class="fa-solid {w.pruefung.ok ? 'fa-circle-check' : 'fa-circle-xmark'}"></i> {w.pruefung.hinweis} <span class="text-secondary">(geprüft {vorZeit(w.zuletzt_geprueft)})</span></div>
                {/if}
                {#if pruefungen[w.id] === "laeuft"}<div class="small text-secondary mt-1"><i class="fa-solid fa-circle-notch fa-spin"></i> wird geprüft ...</div>{/if}
              </div>
              <div class="d-flex gap-2 flex-wrap">
                <button class="btn btn-sm btn-outline-secondary" onclick={() => pruefen(w)}><i class="fa-solid fa-stethoscope"></i> Prüfen</button>
                <button class="btn btn-sm btn-outline-secondary" onclick={() => (offen[w.id] = !offen[w.id])}><i class="fa-solid fa-vial"></i> Probe</button>
                <button class="btn btn-sm btn-outline-secondary" onclick={() => bearbeite(w)}><i class="fa-solid fa-pen"></i> Bearbeiten</button>
                <button class="btn btn-sm btn-outline-secondary" onclick={() => umschalten(w, "vorausgewaehlt")}>{w.vorausgewaehlt ? "Nicht vorauswählen" : "Im Chat vorauswählen"}</button>
                <button class="btn btn-sm btn-outline-secondary" onclick={() => umschalten(w, "aktiv")}>{w.aktiv ? "Deaktivieren" : "Aktivieren"}</button>
                <button class="btn btn-sm btn-outline-danger" title="Löschen" onclick={() => { loeschZiel = w; loeschDialog = true; }}><i class="fa-solid fa-trash"></i></button>
              </div>
            </div>

            {#if w.typ === "mcp" && w.entdeckt.length}
              <div class="mt-3">
                <div class="small text-uppercase text-secondary fw-semibold mb-1">Entdeckte Werkzeuge ({w.entdeckt.filter((e) => e.aktiv !== false).length} von {w.entdeckt.length} freigeschaltet) <InfoKnopf anker="werkzeuge" /></div>
                <div class="row g-2">
                  {#each w.entdeckt as e (e.name)}
                    <div class="col-md-6 col-xl-4">
                      <div class="form-check form-switch">
                        <input class="form-check-input" type="checkbox" role="switch" id="e-{w.id}-{e.name}" checked={e.aktiv !== false} onchange={(ev) => entdecktSchalten(w, e.name, (ev.target as HTMLInputElement).checked)} />
                        <label class="form-check-label" for="e-{w.id}-{e.name}" title={e.beschreibung}><b>{e.titel || e.name}</b> <span class="text-secondary small">{(e.beschreibung || "").slice(0, 90)}</span></label>
                      </div>
                    </div>
                  {/each}
                </div>
              </div>
            {:else if w.typ === "mcp"}
              <div class="mt-2 text-secondary small">Noch keine Werkzeuge entdeckt - auf Prüfen klicken.</div>
            {/if}

            {#if offen[w.id]}
              <div class="mt-3 p-3 bg-body-tertiary">
                <div class="row g-2 align-items-end">
                  {#if w.einsetzbar.length > 1}
                    <div class="col-md-4"><label class="form-label small mb-1" for="pk-{w.id}">Werkzeug</label><select class="form-select form-select-sm" id="pk-{w.id}" bind:value={probeKennung[w.id]}>{#each w.einsetzbar as e (e.kennung)}<option value={e.kennung}>{e.titel}</option>{/each}</select></div>
                  {/if}
                  <div class="col-md-6"><label class="form-label small mb-1" for="pf-{w.id}">Frage für die Probe</label><input class="form-control form-control-sm" id="pf-{w.id}" placeholder="Wie ist das Wetter heute in Leipzig?" bind:value={probeFrage[w.id]} /></div>
                  <div class="col-md-2"><button class="btn btn-sm btn-primary w-100" onclick={() => probe(w)} disabled={proben[w.id] === "laeuft"}>{#if proben[w.id] === "laeuft"}<i class="fa-solid fa-circle-notch fa-spin"></i>{:else}Probe senden{/if}</button></div>
                </div>
                {#if proben[w.id] && proben[w.id] !== "laeuft"}
                  {@const p = proben[w.id] as WerkzeugProbe}
                  <div class="mt-2 small text-secondary">Argumente ({p.herkunft}): <code>{JSON.stringify(p.argumente)}</code> &middot; {p.dauer_ms} Millisekunden &middot; {p.stellen} Fundstücke</div>
                  {#if p.fehler}<div class="text-danger mt-1">{p.fehler}</div>{/if}
                  {#if p.text}<pre class="mt-2 mb-0" style="white-space: pre-wrap; max-height: 260px; overflow: auto; font-family: inherit">{p.text}</pre>{/if}
                {/if}
              </div>
            {/if}

            {#if bearbeiten === w.id}
              <hr />
              {@render formularInhalt()}
            {/if}
          </div>
        </div>
      {/each}
    {/if}
  </div>
</section>

{#snippet formularInhalt()}
  <div class="row g-3">
    <div class="col-md-4"><label class="form-label" for="w-name">Name</label><input class="form-control" id="w-name" bind:value={formular.name} placeholder="z. B. Recherche" /></div>
    <div class="col-md-3">
      <label class="form-label" for="w-typ">Typ</label>
      <select class="form-select" id="w-typ" bind:value={formular.typ} onchange={typWechsel} disabled={bearbeiten !== "neu"}>
        {#each Object.entries(daten?.typen ?? {}) as [k, t] (k)}<option value={k}>{t}</option>{/each}
      </select>
    </div>
    <div class="col-md-5"><label class="form-label" for="w-besch">Beschreibung für das Modell <InfoKnopf anker="werkzeuge" /></label><input class="form-control" id="w-besch" bind:value={formular.beschreibung} placeholder="Wofür das Werkzeug taugt und wann es gefragt werden soll" /></div>
    <div class="col-md-8"><label class="form-label" for="w-url">Adresse{formular.typ === "http_json" ? " (Platzhalter {frage} und {parametername})" : ""}</label><input class="form-control" id="w-url" bind:value={formular.konfiguration.url} placeholder={formular.typ === "mcp" ? "http://127.0.0.1:8000/mcp/" : "https://dienst.example/suche?q={frage}"} /></div>
    {#if formular.typ === "mcp"}
      <div class="col-md-4"><label class="form-label" for="w-tr">Transport</label><select class="form-select" id="w-tr" bind:value={formular.konfiguration.transport}>{#each Object.entries(daten?.transporte ?? {}) as [k, t] (k)}<option value={k}>{t}</option>{/each}</select></div>
    {:else}
      <div class="col-md-4"><label class="form-label" for="w-me">Methode</label><select class="form-select" id="w-me" bind:value={formular.konfiguration.methode}><option value="GET">GET</option><option value="POST">POST</option></select></div>
      {#if formular.konfiguration.methode === "POST"}
        <div class="col-12"><label class="form-label" for="w-rumpf">Rumpf (JSON-Vorlage mit Platzhaltern)</label><textarea class="form-control" id="w-rumpf" rows="2" bind:value={formular.konfiguration.rumpf} placeholder={'{"query": "{frage}"}'}></textarea></div>
      {/if}
      <div class="col-md-4"><label class="form-label" for="w-at">Pfad zum Antworttext</label><input class="form-control" id="w-at" bind:value={formular.konfiguration.antwort_text} placeholder="ergebnisse[].text" /></div>
      <div class="col-md-4"><label class="form-label" for="w-ati">Pfad zum Titel (optional)</label><input class="form-control" id="w-ati" bind:value={formular.konfiguration.antwort_titel} placeholder="ergebnisse[].titel" /></div>
      <div class="col-md-4"><label class="form-label" for="w-au">Pfad zur Quelladresse (optional)</label><input class="form-control" id="w-au" bind:value={formular.konfiguration.antwort_url} placeholder="ergebnisse[].url" /></div>
      <div class="col-12"><label class="form-label" for="w-par">Parameter (JSON-Liste: name, beschreibung, pflicht)</label><textarea class="form-control" id="w-par" rows="3" bind:value={parameterText} style="font-family: ui-monospace, monospace; font-size: 0.9rem"></textarea></div>
    {/if}
    <div class="col-12">
      <label class="form-label">Kopfzeilen (z. B. Authorization) <span class="text-secondary">- geheime Werte bleiben hier lesbar, im Protokoll maskiert</span></label>
      {#each kopfzeilen as k, i (i)}
        <div class="d-flex gap-2 mb-2">
          <input class="form-control" style="max-width: 240px" placeholder="Name" bind:value={k.name} />
          <input class="form-control" placeholder="Wert" bind:value={k.wert} />
          <div class="form-check form-switch d-flex align-items-center gap-2 mb-0" style="min-width: 110px"><input class="form-check-input" type="checkbox" role="switch" id="kg-{i}" bind:checked={k.geheim} /><label class="form-check-label small" for="kg-{i}">geheim</label></div>
          <button class="btn btn-outline-danger" onclick={() => (kopfzeilen = kopfzeilen.filter((_, j) => j !== i))} title="Kopfzeile entfernen"><i class="fa-solid fa-xmark"></i></button>
        </div>
      {/each}
      <button class="btn btn-sm btn-outline-secondary" onclick={() => (kopfzeilen = [...kopfzeilen, { name: "", wert: "", geheim: false }])}><i class="fa-solid fa-plus"></i> Kopfzeile</button>
    </div>
    <div class="col-12 d-flex gap-3 align-items-center flex-wrap">
      <div class="form-check form-switch"><input class="form-check-input" type="checkbox" role="switch" id="w-aktiv" bind:checked={formular.aktiv} /><label class="form-check-label" for="w-aktiv">aktiv</label></div>
      <div class="form-check form-switch"><input class="form-check-input" type="checkbox" role="switch" id="w-vor" bind:checked={formular.vorausgewaehlt} /><label class="form-check-label" for="w-vor">im Chat vorauswählen</label></div>
      <span class="ms-auto"></span>
      <button class="btn btn-outline-secondary" onclick={() => (bearbeiten = null)} disabled={beschaeftigt}>Abbrechen</button>
      <button class="btn btn-primary" onclick={speichern} disabled={beschaeftigt || !formular.name || !String(formular.konfiguration.url ?? "").trim()}>{#if beschaeftigt}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if} Speichern</button>
    </div>
  </div>
{/snippet}

<Bestaetigung bind:offen={loeschDialog} titel="Werkzeug löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Das Werkzeug <b>{loeschZiel?.name}</b> wird entfernt. Unterhaltungen, die es benutzt haben, behalten ihre gespeicherten Ergebnisse.</p>
</Bestaetigung>
