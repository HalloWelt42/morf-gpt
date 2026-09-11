<script lang="ts">
  // Instanzen des Einbettungsmodells in LM Studio: Stand, freier Speicher, laden und abbauen.
  import { onMount } from "svelte";
  import { api } from "../../lib/api";
  import type { InstanzenStand } from "../../lib/typen";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import { dezimal } from "../../lib/format";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Speicherplatz from "../../lib/komponenten/Speicherplatz.svelte";

  let stand = $state<InstanzenStand | null>(null);
  let beschaeftigt = $state(false);

  async function laden(): Promise<void> {
    try {
      stand = await api.get<InstanzenStand>("/einbettung/instanzen");
    } catch (e) {
      meldeFehler(e, "Instanzen");
    }
  }

  async function aktion(pfad: "sicherstellen" | "abbauen"): Promise<void> {
    beschaeftigt = true;
    try {
      stand = await api.post<InstanzenStand>(`/einbettung/instanzen/${pfad}`);
      meldungen.gut(pfad === "sicherstellen" ? `${stand.geladen.length} Instanz(en) geladen` : "Zusätzliche Instanzen entladen");
    } catch (e) {
      meldeFehler(e, pfad === "sicherstellen" ? "Instanzen laden" : "Instanzen abbauen");
    } finally {
      beschaeftigt = false;
    }
  }

  onMount(() => void laden());
</script>

{#if stand}
  <div class="card mb-3">
    <div class="card-body">
      <div class="d-flex align-items-center gap-2 flex-wrap">
        <h6 class="m-0 small text-uppercase text-secondary">Instanzen von {stand.modell}</h6>
        <InfoKnopf anker="stufe-einbettung" finde="Instanzen" />
        <span class="ms-auto"></span>
        <button class="btn btn-sm btn-outline-secondary" onclick={laden} title="Stand von LM Studio und Speicher neu lesen"><i class="fa-solid fa-rotate"></i></button>
        <button class="btn btn-sm btn-primary" onclick={() => aktion("sicherstellen")} disabled={beschaeftigt || stand.anbieter_typ !== "lmstudio"} title="Fehlende Instanzen bis zur eingestellten Zahl laden, soweit der Speicher reicht">{#if beschaeftigt}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if} Instanzen laden</button>
        <button class="btn btn-sm btn-outline-secondary" onclick={() => aktion("abbauen")} disabled={beschaeftigt || stand.geladen.length <= 1} title="Alle zusätzlichen Instanzen entladen; das Modell selbst bleibt">Abbauen</button>
      </div>
      <div class="row g-3 mt-1">
        <div class="col-md-5">
          <div class="small text-secondary mb-1">Geladen ({stand.geladen.length} von {stand.gewuenscht} gewünscht)</div>
          {#each stand.geladen as i (i.kennung)}
            <div><i class="fa-solid fa-cube text-secondary"></i> <code>{i.kennung}</code>{#if i.groesse_gb} <span class="text-secondary">{dezimal(i.groesse_gb)} GB</span>{/if}</div>
          {:else}
            <div class="text-secondary">Keine Instanz geladen; die erste lädt LM Studio beim ersten Aufruf selbst.</div>
          {/each}
        </div>
        <div class="col-md-7">
          <div class="small text-secondary mb-1">Speicher dieses Rechners</div>
          <div class="m-kennzahlen">
            <div class="m-kennzahl"><div class="wert">{dezimal(stand.speicher.verfuegbar_gb)} GB</div><div class="titel">verfügbar (frei und inaktiv)</div></div>
            <div class="m-kennzahl"><div class="wert">{dezimal(stand.speicher.frei_gb)} GB</div><div class="titel">frei</div></div>
            <div class="m-kennzahl"><div class="wert">{dezimal(stand.speicher.gesamt_gb)} GB</div><div class="titel">gesamt</div></div>
          </div>
        </div>
        <div class="col-12"><Speicherplatz /></div>
      </div>
      {#each stand.hinweise as h}
        <div class="alert alert-warning py-2 mt-2 mb-0"><i class="fa-solid fa-triangle-exclamation"></i> {h}</div>
      {/each}
      <div class="small text-secondary mt-2">Gemessen: eine Instanz 3,9 Texte je Sekunde, zwei Instanzen mit je vier Anfragen 6,2. Die Zahl der Instanzen und die Anfragen je Instanz stellst du unten ein; die Stufe Einbetten lädt fehlende Instanzen vor jedem Auftrag selbst nach.</div>
    </div>
  </div>
{/if}
