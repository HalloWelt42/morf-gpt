<script lang="ts">
  // Ein Stück bearbeiten: großes Textfeld, Teilen an der Cursorposition, Speichern und neu einbetten.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import type { ChunkDetail } from "../lib/typen";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { zahl, zeitmarke, datumZeit } from "../lib/format";
  import { spieleVideo } from "../lib/spielen";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";

  let { id }: { id: string } = $props();

  let c = $state<ChunkDetail | null>(null);
  let text = $state("");
  let feld = $state<HTMLTextAreaElement | null>(null);
  let beschaeftigt = $state(false);
  let ziel = $state(3000);

  const geaendert = $derived(c !== null && text !== c.text);

  async function laden(): Promise<void> {
    try {
      c = await api.get<ChunkDetail>(`/chunks/${id}`);
      text = c.text;
      const w = await api.get<Record<string, unknown>>("/einstellungen/werte");
      ziel = Number(w["stueckelung.ziel_zeichen"] ?? 3000);
    } catch (e) {
      meldeFehler(e, "Stück laden");
      ui.gehe("stellen");
    }
  }

  async function speichern(): Promise<void> {
    if (!c) return;
    beschaeftigt = true;
    try {
      const r = await api.put<{ chunk: ChunkDetail; hinweis: string }>(`/chunks/${c.id}`, { text });
      c = r.chunk;
      text = c.text;
      const e = await api.post<{ modell: string }>(`/chunks/${c.id}/einbetten`);
      meldungen.gut(`Gespeichert und neu eingebettet (${e.modell})`);
      c = await api.get<ChunkDetail>(`/chunks/${id}`);
    } catch (e) {
      meldeFehler(e, "Speichern");
    } finally {
      beschaeftigt = false;
    }
  }

  async function teilen(): Promise<void> {
    if (!c || !feld) return;
    const pos = feld.selectionStart;
    if (pos < 1 || pos >= text.length - 1) {
      meldungen.fehler("Cursor in den Text setzen, wo geteilt werden soll");
      return;
    }
    if (geaendert) {
      meldungen.fehler("Erst speichern, dann teilen");
      return;
    }
    beschaeftigt = true;
    try {
      const r = await api.post<{ chunk: ChunkDetail; hinweis: string }>(`/chunks/${c.id}/teilen`, { position: pos });
      meldungen.gut(r.hinweis);
      c = r.chunk;
      text = c.text;
    } catch (e) {
      meldeFehler(e, "Teilen");
    } finally {
      beschaeftigt = false;
    }
  }

  onMount(() => void laden());
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <button class="btn btn-sm btn-outline-secondary" title="Zurück zu den Textstellen" onclick={() => ui.gehe("stellen")}><i class="fa-solid fa-arrow-left"></i></button>
    {#if c}
      <h1>Stück {c.reihenfolge} von {c.anzahl_im_video} - {c.video_titel}</h1>
      {#if c.serie}<Abzeichen serie={c.serie} folgeNr={c.folge_nr} />{/if}
      <span class="m-unter">{zeitmarke(c.start_s)} bis {zeitmarke(c.end_s)}{#if c.thema} &middot; {c.thema}{/if}</span>
      <InfoKnopf anker="stellen" />
      <span class="m-luecke"></span>
      <button class="btn btn-sm btn-outline-primary" onclick={() => spieleVideo(c!.video_id, c!.start_s)}><i class="fa-solid fa-play"></i> Abspielen</button>
      <button class="btn btn-sm btn-outline-secondary" onclick={() => ui.gehe("video", c!.video_id, "stuecke")}><i class="fa-solid fa-film"></i> Video</button>
    {:else}
      <h1>Stück</h1>
    {/if}
  </div>
  <div class="m-ansicht-koerper">
    {#if c}
      <div class="row g-3">
        <div class="col-lg-8">
          <textarea class="form-control" style="font-size: 1.05rem; line-height: 1.6; min-height: 520px" bind:value={text} bind:this={feld}></textarea>
          <div class="d-flex align-items-center gap-2 mt-2 flex-wrap">
            <span class="text-secondary">{zahl(text.length)} Zeichen, Ziel {zahl(ziel)}, Überlappung vor {c.ueberlappung_vor} / nach {c.ueberlappung_nach}</span>
            <span class="ms-auto"></span>
            <button class="btn btn-outline-secondary" onclick={teilen} disabled={beschaeftigt || geaendert} title="An der Cursorposition in zwei Stücke teilen"><i class="fa-solid fa-scissors"></i> Teilen bei Cursor</button>
            <button class="btn btn-outline-secondary" onclick={() => (text = c?.text ?? "")} disabled={!geaendert || beschaeftigt}>Verwerfen</button>
            <button class="btn btn-primary" onclick={speichern} disabled={!geaendert || beschaeftigt || !text.trim()}>{#if beschaeftigt}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if} Speichern und neu einbetten</button>
          </div>
        </div>
        <div class="col-lg-4">
          <div class="card mb-3"><div class="card-header fw-semibold">Einbettung</div><div class="card-body">
            {#if c.einbettung_details.length}
              {#each c.einbettung_details as e}<div>{e.modell} &middot; {e.dimension} Dimensionen &middot; {datumZeit(e.erstellt)}</div>{/each}
            {:else}<span class="text-warning">Keine Einbettung - dieses Stück wird bei der Suche nicht gefunden.</span>{/if}
          </div></div>
          <div class="card mb-3"><div class="card-header fw-semibold">Herkunft</div><div class="card-body">
            <div>Video: <button class="btn btn-sm btn-link p-0" onclick={() => ui.gehe("video", c!.video_id)}>{c.video_titel}</button></div>
            <div class="text-secondary small">Angelegt {datumZeit(c.erstellt)}{c.manuell_bearbeitet ? ", von Hand bearbeitet" : ""}{c.korrektur_id ? ", aus der Korrektur" : ", aus dem Rohtranskript"}</div>
          </div></div>
          {#if c.vorheriger}
            <div class="card mb-3"><div class="card-header fw-semibold">Vorheriges Stück ({zeitmarke(c.vorheriger.start_s)})</div><div class="card-body small">{c.vorheriger.text.slice(-400)} <button class="btn btn-sm btn-link p-0" onclick={() => ui.gehe("stelle", c!.vorheriger!.id)}>öffnen</button></div></div>
          {/if}
          {#if c.naechster}
            <div class="card mb-3"><div class="card-header fw-semibold">Nächstes Stück ({zeitmarke(c.naechster.start_s)})</div><div class="card-body small">{c.naechster.text.slice(0, 400)} <button class="btn btn-sm btn-link p-0" onclick={() => ui.gehe("stelle", c!.naechster!.id)}>öffnen</button></div></div>
          {/if}
        </div>
      </div>
    {:else}
      <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Stück wird geladen.</div>
    {/if}
  </div>
</section>
