<script lang="ts">
  import { ui, type Ansicht } from "../stores/ui.svelte";
  import { hilfe } from "../stores/hilfe.svelte";
  import { ereignisse } from "../stores/ereignisse.svelte";
  import { zahl } from "../format";
  import type { Uebersicht } from "../typen";

  let { uebersicht, laeuferAktiv }: { uebersicht: Uebersicht | null; laeuferAktiv: boolean } = $props();

  const eintraege: { ansicht: Ansicht; titel: string; icon: string; zaehler: () => number | null; mit: Ansicht[] }[] = [
    { ansicht: "chat", titel: "Chat", icon: "fa-comments", zaehler: () => null, mit: ["chat"] },
    { ansicht: "bibliothek", titel: "Bibliothek", icon: "fa-film", zaehler: () => uebersicht?.videos_ausgewaehlt ?? null, mit: ["bibliothek", "video"] },
    { ansicht: "stellen", titel: "Textstellen", icon: "fa-align-left", zaehler: () => uebersicht?.chunks ?? null, mit: ["stellen", "stelle"] },
    { ansicht: "fliessband", titel: "Fließband", icon: "fa-diagram-next", zaehler: () => uebersicht?.auftraege_laufend ?? null, mit: ["fliessband", "auftrag"] },
    { ansicht: "einstellungen", titel: "Einstellungen", icon: "fa-sliders", zaehler: () => null, mit: ["einstellungen"] },
  ];

  function klick(e: MouseEvent, ansicht: Ansicht): void {
    e.preventDefault();
    ui.gehe(ansicht);
  }
</script>

<header class="m-kopf">
  <a class="m-marke" href="#/chat" onclick={(e) => klick(e, "chat")}><span class="m-logo">m</span> morf-gpt</a>
  <nav class="m-nav" aria-label="Hauptbereiche">
    {#each eintraege as e (e.ansicht)}
      <a href="#/{e.ansicht}" class:aktiv={e.mit.includes(ui.route.ansicht)} onclick={(ev) => klick(ev, e.ansicht)}>
        <i class="fa-solid {e.icon}"></i> {e.titel}
        {#if e.zaehler() !== null}<span class="zaehler">{zahl(e.zaehler())}</span>{/if}
      </a>
    {/each}
  </nav>
  <div class="m-kopf-rechts">
    <span title={ereignisse.verbunden ? "Ereignisstrom verbunden" : "Ereignisstrom getrennt - Anzeige aktualisiert sich nicht live"}>
      <span class="m-status-punkt" class:aus={!laeuferAktiv || !ereignisse.verbunden}></span>{laeuferAktiv ? "Läufer aktiv" : "Läufer aus"}
    </span>
    <button class="m-kopf-knopf" title="Helles oder dunkles Thema" onclick={() => ui.themaWechseln()}><i class="fa-solid fa-circle-half-stroke"></i></button>
    <button class="m-kopf-knopf" title="Hilfe öffnen oder schließen" onclick={() => hilfe.umschalten("erste-schritte")}><i class="fa-solid fa-circle-question"></i> Hilfe</button>
    <span class="version" title="Version aus version.json">{uebersicht?.version_voll ?? __APP_VERSION_VOLL__}</span>
  </div>
</header>
