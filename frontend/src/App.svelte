<script lang="ts">
  // Rahmen der Oberfläche: Kopfleiste, Ansicht nach Route, Spieler, Hilfe, Meldungen.
  import { onMount } from "svelte";
  import { ui } from "./lib/stores/ui.svelte";
  import { ereignisse } from "./lib/stores/ereignisse.svelte";
  import { api } from "./lib/api";
  import type { Uebersicht } from "./lib/typen";
  import Kopfleiste from "./lib/komponenten/Kopfleiste.svelte";
  import Spieler from "./lib/komponenten/Spieler.svelte";
  import Hilfe from "./lib/komponenten/Hilfe.svelte";
  import Meldungen from "./lib/komponenten/Meldungen.svelte";
  import Chat from "./ansichten/Chat.svelte";
  import Bibliothek from "./ansichten/Bibliothek.svelte";
  import Video from "./ansichten/Video.svelte";
  import Stellen from "./ansichten/Stellen.svelte";
  import Stelle from "./ansichten/Stelle.svelte";
  import Fliessband from "./ansichten/Fliessband.svelte";
  import Auftrag from "./ansichten/Auftrag.svelte";
  import Einstellungen from "./ansichten/Einstellungen.svelte";

  let uebersicht = $state<Uebersicht | null>(null);

  async function ladeUebersicht(): Promise<void> {
    try {
      uebersicht = await api.get<Uebersicht>("/system/uebersicht");
    } catch {
      // Backend nicht erreichbar - Kopfleiste zeigt dann keine Zähler
    }
  }

  onMount(() => {
    ereignisse.start();
    void ladeUebersicht();
    const takt = window.setInterval(() => void ladeUebersicht(), 30000);
    const ab = ereignisse.abonniere("auftrag_status", () => void ladeUebersicht());
    return () => {
      window.clearInterval(takt);
      ab();
    };
  });
</script>

<div class="m-app">
  <Kopfleiste {uebersicht} laeuferAktiv={uebersicht?.laeufer_aktiv ?? false} />
  <main class="m-inhalt">
    {#if ui.route.ansicht === "chat"}
      <Chat id={ui.route.id} />
    {:else if ui.route.ansicht === "bibliothek"}
      <Bibliothek />
    {:else if ui.route.ansicht === "video"}
      {#key ui.route.id}<Video id={ui.route.id} reiter={ui.route.unter} />{/key}
    {:else if ui.route.ansicht === "stellen"}
      <Stellen />
    {:else if ui.route.ansicht === "stelle"}
      {#key ui.route.id}<Stelle id={ui.route.id} />{/key}
    {:else if ui.route.ansicht === "fliessband"}
      <Fliessband />
    {:else if ui.route.ansicht === "auftrag"}
      {#key ui.route.id}<Auftrag id={ui.route.id} />{/key}
    {:else if ui.route.ansicht === "einstellungen"}
      <Einstellungen gruppe={ui.route.id} />
    {/if}
  </main>
  <Spieler />
</div>
<Hilfe />
<Meldungen />
