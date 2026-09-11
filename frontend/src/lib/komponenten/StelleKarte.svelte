<script lang="ts">
  // Eine Fundstelle: Nummer, Video, Zeitfenster, Wert, Auszug, Sprünge, Abwahl.
  import type { Stelle } from "../typen";
  import { zeitmarke, folge, youtubeMitZeit } from "../format";
  import { spieleVideo } from "../spielen";
  import { ui } from "../stores/ui.svelte";

  let {
    stelle,
    nummer,
    gewaehlt = true,
    hervorgehoben = false,
    umschaltbar = true,
    onUmschalten,
  }: {
    stelle: Stelle;
    nummer: number;
    gewaehlt?: boolean;
    hervorgehoben?: boolean;
    umschaltbar?: boolean;
    onUmschalten?: () => void;
  } = $props();

  const prozent = $derived(Math.max(0, Math.min(100, Math.round(stelle.wert * 100))));
</script>

{#if stelle.art === "dokument"}
  <div class="m-stelle dokument" class:abgewaehlt={!gewaehlt} class:hervor={hervorgehoben} id="stelle-{nummer}">
    <div class="kopf">
      <span class="nr">{nummer}</span>
      <div class="flex-grow-1" style="min-width: 0">
        <div class="titel"><i class="fa-solid fa-book text-secondary"></i> {stelle.titel}</div>
        <div class="zeit">{#if stelle.abschnitt}Kapitel: {stelle.abschnitt}{:else}Dokument{/if}{#if stelle.seite_von} &middot; Seite {stelle.seite_von}{/if} &middot; Stück {stelle.reihenfolge}</div>
      </div>
    </div>
    <div class="auszug">{stelle.text}</div>
    <div class="aktionen">
      <div class="m-wert" title="Ähnlichkeit zur Frage"><span style="width: {prozent}%"></span></div>
      <span class="m-wert-zahl">{stelle.wert > 0 ? stelle.wert.toFixed(2).replace(".", ",") : "-"}</span>
      <button class="btn btn-sm btn-outline-primary" title="Im Dokument an dieser Stelle lesen" onclick={() => ui.gehe("dokument", stelle.dokument_id, stelle.abschnitt_nr === null ? "" : String(stelle.abschnitt_nr))}><i class="fa-solid fa-book-open"></i></button>
      <button class="btn btn-sm btn-outline-secondary" title="Textstelle öffnen" onclick={() => ui.gehe("stelle", stelle.chunk_id)}><i class="fa-solid fa-up-right-from-square"></i></button>
      {#if umschaltbar && onUmschalten}
        <button class="btn btn-sm btn-outline-secondary" title={gewaehlt ? "Stelle abwählen" : "Stelle wieder aufnehmen"} onclick={onUmschalten}><i class="fa-regular {gewaehlt ? 'fa-square-check' : 'fa-square'}"></i></button>
      {/if}
    </div>
  </div>
{:else if stelle.art === "werkzeug"}
  <div class="m-stelle werkzeug" class:abgewaehlt={!gewaehlt} class:hervor={hervorgehoben} id="stelle-{nummer}">
    <div class="kopf">
      <span class="nr"><i class="fa-solid fa-plug"></i></span>
      <div class="flex-grow-1" style="min-width: 0">
        <div class="titel">{stelle.werkzeug}{#if stelle.titel} - {stelle.titel}{/if}</div>
        <div class="zeit">Fremder Dienst &middot; Stelle {nummer}{#if stelle.quelle_url} &middot; <a href={stelle.quelle_url} target="_blank" rel="noreferrer" title="Quelle des Werkzeugergebnisses öffnen">{stelle.quelle_url.replace(/^https?:\/\//, "").slice(0, 48)}</a>{/if}</div>
      </div>
    </div>
    <div class="auszug" style="-webkit-line-clamp: 6">{stelle.text}</div>
    <div class="aktionen">
      <span class="small text-secondary">{stelle.text.length} Zeichen</span>
      <span class="ms-auto"></span>
      {#if stelle.quelle_url}<a class="btn btn-sm btn-outline-secondary" title="Quelle öffnen" href={stelle.quelle_url} target="_blank" rel="noreferrer"><i class="fa-solid fa-up-right-from-square"></i></a>{/if}
      {#if umschaltbar && onUmschalten}
        <button class="btn btn-sm btn-outline-secondary" title={gewaehlt ? "Stelle abwählen" : "Stelle wieder aufnehmen"} onclick={onUmschalten}><i class="fa-regular {gewaehlt ? 'fa-square-check' : 'fa-square'}"></i></button>
      {/if}
    </div>
  </div>
{:else}
<div class="m-stelle" class:abgewaehlt={!gewaehlt} class:hervor={hervorgehoben} id="stelle-{nummer}">
  <div class="kopf">
    <span class="nr">{nummer}</span>
    <div class="flex-grow-1" style="min-width: 0">
      <div class="titel">{stelle.titel}</div>
      <div class="zeit">
        {#if stelle.serie}<span class="m-serie">{folge(stelle.serie, stelle.folge_nr)}</span> &middot;{/if}
        {zeitmarke(stelle.start_s)} bis {zeitmarke(stelle.end_s)}
        {#if stelle.thema}&middot; {stelle.thema}{/if}
      </div>
    </div>
  </div>
  <div class="auszug">{stelle.text}</div>
  <div class="aktionen">
    <div class="m-wert" title="Ähnlichkeit zur Frage"><span style="width: {prozent}%"></span></div>
    <span class="m-wert-zahl">{stelle.wert > 0 ? stelle.wert.toFixed(2).replace(".", ",") : "-"}</span>
    <button class="btn btn-sm btn-outline-primary" title="Ab {zeitmarke(stelle.start_s)} abspielen" onclick={() => spieleVideo(stelle.video_id, stelle.start_s)}><i class="fa-solid fa-play"></i></button>
    {#if stelle.original_url}
      <a class="btn btn-sm btn-outline-secondary" title="Bei YouTube ab {zeitmarke(stelle.start_s)} öffnen" href={youtubeMitZeit(stelle.original_url, stelle.start_s)} target="_blank" rel="noreferrer"><i class="fa-brands fa-youtube"></i></a>
    {/if}
    <button class="btn btn-sm btn-outline-secondary" title="Textstelle öffnen" onclick={() => ui.gehe("stelle", stelle.chunk_id)}><i class="fa-solid fa-up-right-from-square"></i></button>
    {#if umschaltbar && onUmschalten}
      <button class="btn btn-sm btn-outline-secondary" title={gewaehlt ? "Stelle abwählen" : "Stelle wieder aufnehmen"} onclick={onUmschalten}><i class="fa-regular {gewaehlt ? 'fa-square-check' : 'fa-square'}"></i></button>
    {/if}
  </div>
</div>
{/if}

<style>
  .m-stelle.werkzeug .nr {
    background: var(--m-stufe-korrigiert);
  }
  .m-stelle.dokument .nr {
    background: var(--m-stufe-gestueckelt);
  }
  .m-stelle.hervor {
    border-color: var(--m-akzent);
    box-shadow: 0 0 0 2px var(--m-akzent-hell);
  }
</style>
