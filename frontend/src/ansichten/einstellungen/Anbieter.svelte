<script lang="ts">
  // Anbieter verwalten: Rollen, Karten je Anbieter, Prüfen, Probe, Bearbeiten, Anlegen.
  import { onMount } from "svelte";
  import { api } from "../../lib/api";
  import type { Anbieter, AnbieterEingabe, AnbieterPruefung, AnbieterProbe, AnbieterUebersicht } from "../../lib/typen";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Bestaetigung from "../../lib/komponenten/Bestaetigung.svelte";

  let daten = $state<AnbieterUebersicht | null>(null);
  let pruefungen = $state<Record<string, AnbieterPruefung | "laeuft">>({});
  let proben = $state<Record<string, AnbieterProbe | "laeuft" | undefined>>({});
  let offen = $state<Record<string, boolean>>({});
  let bearbeiten = $state<string | null>(null); // Anbieter-Kennung oder "neu"
  let formular = $state<AnbieterEingabe>(leer());
  let beschaeftigt = $state(false);
  let loeschDialog = $state(false);
  let loeschZiel = $state<Anbieter | null>(null);

  function leer(): AnbieterEingabe {
    return { name: "", typ: "lmstudio", art: "sprachmodell", basis_url: "http://127.0.0.1:1234/v1", api_schluessel: "", modell: "", parameter: {}, aktiv: true };
  }

  async function laden(): Promise<void> {
    try {
      daten = await api.get<AnbieterUebersicht>("/anbieter");
    } catch (e) {
      meldeFehler(e, "Anbieter laden");
    }
  }

  async function rolle(r: string, ev: Event): Promise<void> {
    const id = (ev.target as HTMLSelectElement).value;
    try {
      const rollen = await api.put<Record<string, string>>("/anbieter/rollen", { rolle: r, anbieter_id: id });
      if (daten) daten.rollen = rollen;
      meldungen.gut("Rolle zugewiesen");
    } catch (e) {
      meldeFehler(e, "Rolle zuweisen");
      void laden();
    }
  }

  async function pruefen(a: Anbieter): Promise<void> {
    pruefungen[a.id] = "laeuft";
    try {
      pruefungen[a.id] = await api.post<AnbieterPruefung>(`/anbieter/${a.id}/pruefen`);
    } catch (e) {
      pruefungen[a.id] = { erreichbar: false, hinweis: e instanceof Error ? e.message : String(e), modelle: [] };
    }
  }

  async function probe(a: Anbieter): Promise<void> {
    proben[a.id] = "laeuft";
    try {
      proben[a.id] = await api.post<AnbieterProbe>(`/anbieter/${a.id}/probe`);
    } catch (e) {
      proben[a.id] = undefined;
      meldeFehler(e, `Probe ${a.name}`);
    }
  }

  function bearbeite(a: Anbieter): void {
    bearbeiten = a.id;
    formular = { name: a.name, typ: a.typ, art: a.art, basis_url: a.basis_url, api_schluessel: a.api_schluessel, modell: a.modell, parameter: { ...a.parameter }, aktiv: a.aktiv };
  }

  function neu(): void {
    bearbeiten = "neu";
    formular = leer();
  }

  async function speichern(): Promise<void> {
    beschaeftigt = true;
    try {
      if (bearbeiten === "neu") await api.post<Anbieter>("/anbieter", formular);
      else await api.put<Anbieter>(`/anbieter/${bearbeiten}`, formular);
      meldungen.gut("Anbieter gespeichert");
      bearbeiten = null;
      await laden();
    } catch (e) {
      meldeFehler(e, "Anbieter speichern");
    } finally {
      beschaeftigt = false;
    }
  }

  async function aktivUmschalten(a: Anbieter): Promise<void> {
    try {
      await api.put<Anbieter>(`/anbieter/${a.id}`, { name: a.name, typ: a.typ, art: a.art, basis_url: a.basis_url, api_schluessel: null, modell: a.modell, parameter: a.parameter, aktiv: !a.aktiv });
      await laden();
    } catch (e) {
      meldeFehler(e, "Anbieter ändern");
    }
  }

  async function loeschen(): Promise<void> {
    if (!loeschZiel) return;
    beschaeftigt = true;
    try {
      await api.del(`/anbieter/${loeschZiel.id}`);
      meldungen.gut("Anbieter gelöscht");
      loeschDialog = false;
      await laden();
    } catch (e) {
      meldeFehler(e, "Anbieter löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function kopiere(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      meldungen.gut("In die Zwischenablage kopiert");
    } catch {
      meldungen.fehler("Zwischenablage nicht verfügbar");
    }
  }

  function verdeckt(s: string): string {
    return s ? "********" + s.slice(-4) : "";
  }

  function typWechsel(): void {
    if (formular.typ === "fastembed") {
      formular.art = "einbettung";
      formular.basis_url = "";
      if (!formular.modell) formular.modell = "BAAI/bge-m3";
    } else if (formular.typ === "lmstudio" && !formular.basis_url) formular.basis_url = "http://127.0.0.1:1234/v1";
  }

  onMount(() => void laden());
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <h1>Anbieter</h1>
    <span class="m-unter">Sprachmodelle und Einbettungen; die Rollen bestimmen, wer was tut</span>
    <InfoKnopf anker="anbieter" />
    <span class="m-luecke"></span>
    <button class="btn btn-sm btn-primary" onclick={neu}><i class="fa-solid fa-plus"></i> Neuer Anbieter</button>
  </div>
  <div class="m-ansicht-koerper">
    {#if !daten}
      <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Anbieter werden geladen.</div>
    {:else}
      <div class="card mb-3">
        <div class="card-header fw-semibold">Rollen <InfoKnopf anker="anbieter" /></div>
        <div class="card-body">
          {#each Object.entries(daten.rollen_titel) as [r, titel] (r)}
            <div class="row g-2 align-items-center mb-2">
              <div class="col-md-4 fw-semibold">{titel}</div>
              <div class="col-md-8">
                <select class="form-select" value={daten.rollen[r] ?? ""} onchange={(ev) => rolle(r, ev)}>
                  <option value="" disabled>Bitte wählen</option>
                  {#each daten.anbieter.filter((a) => a.art === (r === "einbettung" ? "einbettung" : "sprachmodell")) as a (a.id)}
                    <option value={a.id}>{a.name} ({a.modell}){a.aktiv ? "" : " - deaktiviert"}</option>
                  {/each}
                </select>
              </div>
            </div>
          {/each}
        </div>
      </div>

      {#if bearbeiten === "neu"}
        <div class="card mb-3 border-primary">
          <div class="card-header fw-semibold">Neuer Anbieter</div>
          <div class="card-body">{@render formularInhalt()}</div>
        </div>
      {/if}

      {#each daten.anbieter as a (a.id)}
        <div class="card mb-3" class:opacity-50={!a.aktiv}>
          <div class="card-body">
            <div class="d-flex align-items-start gap-3 flex-wrap">
              <div class="flex-grow-1">
                <div class="d-flex align-items-center gap-2">
                  {#if pruefungen[a.id] && pruefungen[a.id] !== "laeuft"}
                    <span class="m-status-punkt" class:aus={!(pruefungen[a.id] as AnbieterPruefung).erreichbar}></span>
                  {/if}
                  <span class="fs-5 fw-semibold">{a.name}</span>
                  <span class="badge text-bg-secondary">{a.typ_titel}</span>
                  <span class="badge {a.art === 'einbettung' ? 'text-bg-info' : 'text-bg-primary'}">{a.art === "einbettung" ? "Einbettung" : "Sprachmodell"}</span>
                  {#each Object.entries(daten.rollen).filter(([, id]) => id === a.id) as [r] (r)}
                    <span class="badge text-bg-success">{daten.rollen_titel[r]}</span>
                  {/each}
                  {#if !a.aktiv}<span class="badge text-bg-dark">deaktiviert</span>{/if}
                </div>
                <div class="text-secondary mt-1">
                  Modell <code>{a.modell || "-"}</code>
                  {#if a.basis_url}&middot; {a.basis_url}{/if}
                  {#if a.parameter.dimension}&middot; {String(a.parameter.dimension)} Dimensionen{/if}
                </div>
                {#if a.hat_schluessel}
                  <div class="mt-1 d-flex align-items-center gap-2">
                    <span class="text-secondary">Schlüssel</span>
                    <code>{offen[a.id] ? a.api_schluessel : verdeckt(a.api_schluessel)}</code>
                    {#if !offen[a.id]}<button class="btn btn-sm btn-link p-0" title="Schlüssel aufdecken" onclick={() => (offen[a.id] = true)}><i class="fa-regular fa-eye"></i></button>{/if}
                    <button class="btn btn-sm btn-link p-0" title="Schlüssel kopieren" onclick={() => kopiere(a.api_schluessel)}><i class="fa-regular fa-copy"></i></button>
                  </div>
                {/if}
                {#if pruefungen[a.id] === "laeuft"}
                  <div class="mt-2 text-secondary"><i class="fa-solid fa-circle-notch fa-spin"></i> wird geprüft ...</div>
                {:else if pruefungen[a.id]}
                  {@const p = pruefungen[a.id] as AnbieterPruefung}
                  <div class="mt-2" class:text-success={p.erreichbar} class:text-danger={!p.erreichbar}>
                    <i class="fa-solid {p.erreichbar ? 'fa-circle-check' : 'fa-circle-xmark'}"></i> {p.hinweis}
                    {#if p.modelle.length}
                      <span class="text-secondary">&middot; {p.modelle.length} Modelle{p.modelle.some((m) => m.geladen) ? `, geladen: ${p.modelle.filter((m) => m.geladen).map((m) => m.id).join(", ")}` : ""}</span>
                    {/if}
                  </div>
                {/if}
                {#if proben[a.id] === "laeuft"}
                  <div class="mt-1 text-secondary"><i class="fa-solid fa-circle-notch fa-spin"></i> Probe läuft (bei kaltem Modell dauert der erste Aufruf länger) ...</div>
                {:else if proben[a.id]}
                  {@const pr = proben[a.id] as AnbieterProbe}
                  <div class="mt-1"><i class="fa-solid fa-vial text-primary"></i> Antwort in {(pr.dauer_ms / 1000).toFixed(1).replace(".", ",")} Sekunden ({pr.modell}): <em>{pr.text}</em></div>
                {/if}
              </div>
              <div class="d-flex gap-2 flex-wrap">
                <button class="btn btn-sm btn-outline-secondary" onclick={() => pruefen(a)}><i class="fa-solid fa-stethoscope"></i> Prüfen</button>
                <button class="btn btn-sm btn-outline-secondary" onclick={() => probe(a)}><i class="fa-solid fa-vial"></i> Probe senden</button>
                <button class="btn btn-sm btn-outline-secondary" onclick={() => bearbeite(a)}><i class="fa-solid fa-pen"></i> Bearbeiten</button>
                <button class="btn btn-sm btn-outline-secondary" onclick={() => aktivUmschalten(a)}>{a.aktiv ? "Deaktivieren" : "Aktivieren"}</button>
                <button class="btn btn-sm btn-outline-danger" title="Löschen" onclick={() => { loeschZiel = a; loeschDialog = true; }}><i class="fa-solid fa-trash"></i></button>
              </div>
            </div>
            {#if bearbeiten === a.id}
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
    <div class="col-md-6">
      <label class="form-label" for="f-name">Name</label>
      <input class="form-control" id="f-name" bind:value={formular.name} placeholder="z. B. LM Studio - Chat" />
    </div>
    <div class="col-md-3">
      <label class="form-label" for="f-typ">Typ</label>
      <select class="form-select" id="f-typ" bind:value={formular.typ} onchange={typWechsel}>
        {#each Object.entries(daten?.typen ?? {}) as [k, t] (k)}<option value={k}>{t}</option>{/each}
      </select>
    </div>
    <div class="col-md-3">
      <label class="form-label" for="f-art">Art</label>
      <select class="form-select" id="f-art" bind:value={formular.art} disabled={formular.typ === "fastembed"}>
        <option value="sprachmodell">Sprachmodell</option>
        <option value="einbettung">Einbettung</option>
      </select>
    </div>
    {#if formular.typ !== "fastembed"}
      <div class="col-md-6">
        <label class="form-label" for="f-url">Basisadresse</label>
        <input class="form-control" id="f-url" bind:value={formular.basis_url} placeholder="https://inference.hetzner.com/api/v1" />
      </div>
      <div class="col-md-6">
        <label class="form-label" for="f-key">Schlüssel <span class="text-secondary">(leer lassen, wenn keiner nötig ist)</span></label>
        <input class="form-control" id="f-key" bind:value={formular.api_schluessel} />
      </div>
    {/if}
    <div class="col-md-6">
      <label class="form-label" for="f-modell">Modell</label>
      <input class="form-control" id="f-modell" bind:value={formular.modell} placeholder={formular.typ === "fastembed" ? "BAAI/bge-m3" : "Modellkennung beim Anbieter"} />
    </div>
    {#if formular.art === "einbettung"}
      <div class="col-md-3">
        <label class="form-label" for="f-dim">Dimension</label>
        <input class="form-control" id="f-dim" type="number" value={(formular.parameter.dimension as number | undefined) ?? 1024} onchange={(ev) => (formular.parameter.dimension = Number((ev.target as HTMLInputElement).value))} />
      </div>
    {/if}
    <div class="col-md-3 d-flex align-items-end">
      <div class="form-check form-switch">
        <input class="form-check-input" type="checkbox" role="switch" id="f-aktiv" bind:checked={formular.aktiv} />
        <label class="form-check-label" for="f-aktiv">aktiv</label>
      </div>
    </div>
    <div class="col-12 d-flex gap-2">
      <button class="btn btn-primary" onclick={speichern} disabled={beschaeftigt || !formular.name}>{#if beschaeftigt}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if} Speichern</button>
      <button class="btn btn-outline-secondary" onclick={() => (bearbeiten = null)} disabled={beschaeftigt}>Abbrechen</button>
    </div>
  </div>
{/snippet}

<Bestaetigung bind:offen={loeschDialog} titel="Anbieter löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Der Anbieter <b>{loeschZiel?.name}</b> wird entfernt. Ist er einer Rolle zugewiesen, muss die Rolle vorher umgestellt werden.</p>
</Bestaetigung>
