<script lang="ts">
  // Eine Fundstelle: Nummer, Video, Zeitfenster, Wert, Auszug, Sprünge, Abwahl.
  import type { Stelle } from "../typen";
  import { zeitmarke, datum, folge, youtubeMitZeit } from "../format";
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
  <span class="visually-hidden">{datum(null)}</span>
</div>

<style>
  .m-stelle.hervor {
    border-color: var(--m-akzent);
    box-shadow: 0 0 0 2px var(--m-akzent-hell);
  }
</style>
