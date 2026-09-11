<script lang="ts">
  // Audiospieler-Leiste: <audio> mit HTTP-Range vom Backend, Themen als Zeitleiste,
  // Sprünge, Tempo, YouTube an derselben Stelle.
  import { spieler } from "../stores/spieler.svelte";
  import { zeitmarke, youtubeMitZeit, folge } from "../format";

  let element = $state<HTMLAudioElement | null>(null);
  let zeitleiste = $state<HTMLDivElement | null>(null);

  const dauer = $derived(spieler.video?.dauer_s ?? 0);
  const anteil = $derived(dauer > 0 ? Math.min(100, (spieler.position / dauer) * 100) : 0);

  // Sprungziel übernehmen, sobald das Element bereit ist.
  $effect(() => {
    const ziel = spieler.sprungZiel;
    const el = element;
    if (ziel === null || !el) return;
    const setze = () => {
      el.currentTime = ziel;
      spieler.sprungZiel = null;
      if (spieler.laeuft) void el.play().catch((e: Error) => (spieler.ladefehler = e.message));
    };
    if (el.readyState >= 1) setze();
    else el.addEventListener("loadedmetadata", setze, { once: true });
  });

  $effect(() => {
    const el = element;
    if (!el) return;
    if (spieler.laeuft) void el.play().catch((e: Error) => (spieler.ladefehler = e.message));
    else el.pause();
  });

  $effect(() => {
    if (element) element.playbackRate = spieler.tempo;
  });

  function zeitKlick(e: MouseEvent): void {
    if (!zeitleiste || !dauer) return;
    const r = zeitleiste.getBoundingClientRect();
    const a = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    spieler.springe(a * dauer);
  }

  function breite(start: number, ende: number): string {
    if (!dauer) return "0%";
    return `${Math.max(0, ((ende - start) / dauer) * 100)}%`;
  }

  function links(start: number): string {
    if (!dauer) return "0%";
    return `${Math.max(0, (start / dauer) * 100)}%`;
  }
</script>

{#if spieler.video}
  <footer class="m-spieler" aria-label="Audiospieler">
    <audio
      bind:this={element}
      src={spieler.quelle}
      preload="metadata"
      ontimeupdate={() => (spieler.position = element?.currentTime ?? 0)}
      onended={() => (spieler.laeuft = false)}
      onpause={() => (spieler.laeuft = false)}
      onplay={() => (spieler.laeuft = true)}
      onerror={() => (spieler.ladefehler = "Audio konnte nicht geladen werden")}
    ></audio>
    <div class="zeile1">
      <div style="min-width: 0">
        <div class="titel" title={spieler.video.titel}>{spieler.video.titel}</div>
        <div class="unter">
          {#if spieler.video.serie}<span class="m-serie">{folge(spieler.video.serie, spieler.video.folge_nr)}</span> &middot;{/if}
          {#if spieler.ladefehler}<span class="text-danger">{spieler.ladefehler}</span>
          {:else if spieler.aktuellesThema}Thema: {spieler.aktuellesThema.titel}
          {:else}Abspielen ab Zeitmarke{/if}
        </div>
      </div>
      <div class="knoepfe">
        <button class="btn btn-outline-secondary" title="30 Sekunden zurück" onclick={() => spieler.relativ(-30)}><i class="fa-solid fa-backward"></i></button>
        <button class="btn btn-outline-secondary" title="5 Sekunden zurück" onclick={() => spieler.relativ(-5)}><i class="fa-solid fa-backward-step"></i></button>
        <button class="btn btn-primary" title={spieler.laeuft ? "Pause" : "Abspielen"} onclick={() => spieler.umschalten()}><i class="fa-solid {spieler.laeuft ? 'fa-pause' : 'fa-play'}"></i></button>
        <button class="btn btn-outline-secondary" title="5 Sekunden vor" onclick={() => spieler.relativ(5)}><i class="fa-solid fa-forward-step"></i></button>
        <button class="btn btn-outline-secondary" title="30 Sekunden vor" onclick={() => spieler.relativ(30)}><i class="fa-solid fa-forward"></i></button>
      </div>
      <div class="rechts">
        <span class="zeiten">{zeitmarke(spieler.position)} / {zeitmarke(dauer)}</span>
        <select class="form-select form-select-sm" style="width: 84px" title="Tempo" bind:value={spieler.tempo}>
          <option value={0.8}>0,8x</option>
          <option value={1}>1,0x</option>
          <option value={1.25}>1,25x</option>
          <option value={1.5}>1,5x</option>
          <option value={2}>2,0x</option>
        </select>
        {#if spieler.video.original_url}
          <a class="btn btn-sm btn-outline-secondary" title="Bei YouTube an dieser Stelle öffnen" href={youtubeMitZeit(spieler.video.original_url, spieler.position)} target="_blank" rel="noreferrer"><i class="fa-brands fa-youtube"></i></a>
        {/if}
        <button class="btn btn-sm btn-outline-secondary" title="Spieler schließen" onclick={() => spieler.schliessen()}><i class="fa-solid fa-xmark"></i></button>
      </div>
    </div>
    <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
    <div class="m-zeitleiste" bind:this={zeitleiste} title="Themen des Videos - klicken zum Springen" onclick={zeitKlick}>
      {#each spieler.video.themen as t, i (i)}
        <div class="thema" class:aktiv={spieler.aktuellesThema === t} style="left: {links(t.start_s)}; width: {breite(t.start_s, t.end_s)}" title="{t.titel} ({zeitmarke(t.start_s)} bis {zeitmarke(t.end_s)})">{t.titel}</div>
      {/each}
      <div class="gespielt" style="width: {anteil}%"></div>
      <div class="marke" style="left: {anteil}%"></div>
    </div>
  </footer>
{/if}
