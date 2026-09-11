<script lang="ts">
  // Speicherplatz des Projekts auf der Platte: Datenverzeichnis nach Bereichen, daneben die Platte.
  import { onMount } from "svelte";
  import { api } from "../api";
  import type { SpeicherplatzStand } from "../typen";
  import { meldeFehler } from "../stores/meldungen.svelte";
  import { bytes, zahl } from "../format";

  let stand = $state<SpeicherplatzStand | null>(null);
  let laedt = $state(false);

  async function laden(frisch = false): Promise<void> {
    laedt = true;
    try {
      stand = await api.get<SpeicherplatzStand>(`/system/speicherplatz${frisch ? "?frisch=true" : ""}`);
    } catch (e) {
      meldeFehler(e, "Speicherplatz");
    } finally {
      laedt = false;
    }
  }

  onMount(() => void laden());
</script>

{#if stand}
  <div class="small text-secondary mb-1 d-flex align-items-center gap-2">
    <span>Speicherplatz des Projekts auf der Platte ({stand.verzeichnis})</span>
    <button class="btn btn-link btn-sm p-0" onclick={() => laden(true)} disabled={laedt} title="Datenverzeichnis neu vermessen (sonst höchstens eine Minute alt)"><i class="fa-solid fa-rotate" class:fa-spin={laedt}></i></button>
  </div>
  <div class="m-kennzahlen">
    <div class="m-kennzahl" title="Alle Bereiche des Datenverzeichnisses zusammen"><div class="wert">{bytes(stand.gesamt_bytes)}</div><div class="titel">Projekt gesamt</div></div>
    {#each stand.bereiche as b (b.kennung)}
      {#if b.bytes > 0}
        <div class="m-kennzahl" title="{b.titel}: {zahl(b.dateien)} Dateien{b.pfad ? ` unter ${b.pfad}` : ''}"><div class="wert">{bytes(b.bytes)}</div><div class="titel">{b.titel}</div></div>
      {/if}
    {/each}
    {#if stand.platte_gesamt_bytes}
      <div class="m-kennzahl" title="Freier Platz auf der Platte, auf der das Datenverzeichnis liegt"><div class="wert">{bytes(stand.platte_frei_bytes)}</div><div class="titel">Platte frei von {bytes(stand.platte_gesamt_bytes)}</div></div>
    {/if}
  </div>
{/if}
