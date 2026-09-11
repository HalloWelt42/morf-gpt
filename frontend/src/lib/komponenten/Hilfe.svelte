<script lang="ts">
  // Freischwebendes Hilfefenster: verschiebbar, größenverstellbar, durchsuchbar, mit
  // Sprungmarken. Merkt sich Lage, Größe und zuletzt gelesenen Abschnitt.
  import { ui } from "../stores/ui.svelte";
  import { HILFE, type Abschnitt } from "../hilfeInhalt";

  interface Lage {
    links: number;
    oben: number;
    breite: number;
    hoehe: number;
  }

  function leseLage(): Lage {
    try {
      const roh = localStorage.getItem("m-hilfe-lage");
      if (roh) return JSON.parse(roh) as Lage;
    } catch {
      // ignorieren
    }
    return { links: Math.max(20, window.innerWidth - 600), oben: 72, breite: 560, hoehe: 640 };
  }

  let lage = $state<Lage>(leseLage());
  let suche = $state("");
  let aktiv = $state<string>(localStorage.getItem("m-hilfe-anker") ?? HILFE[0].anker);
  let fenster = $state<HTMLDivElement | null>(null);
  let textfeld = $state<HTMLDivElement | null>(null);

  const suchtexte = new Map<string, string>(
    HILFE.map((a) => [
      a.anker,
      [a.titel, a.kurz, ...a.stichworte, ...a.bloecke.flatMap((b) => [b.text ?? "", ...(b.punkte ?? [])])].join(" ").toLowerCase(),
    ]),
  );

  const woerter = $derived(suche.toLowerCase().split(/\s+/).filter(Boolean));
  const treffer = $derived(woerter.length ? HILFE.filter((a) => woerter.every((w) => suchtexte.get(a.anker)!.includes(w))) : HILFE);
  const kategorien = $derived([...new Set(treffer.map((a) => a.kategorie))]);
  const abschnitt = $derived<Abschnitt>(HILFE.find((a) => a.anker === aktiv) ?? HILFE[0]);

  // Anker von außen (Mini-i) übernehmen
  $effect(() => {
    if (ui.hilfeOffen && ui.hilfeAnker && HILFE.some((a) => a.anker === ui.hilfeAnker)) {
      aktiv = ui.hilfeAnker;
      suche = "";
    }
  });

  $effect(() => {
    localStorage.setItem("m-hilfe-anker", aktiv);
    if (textfeld) textfeld.scrollTop = 0;
  });

  function speichereLage(): void {
    localStorage.setItem("m-hilfe-lage", JSON.stringify(lage));
  }

  let ziehStart: { x: number; y: number } | null = null;
  function ziehBeginn(e: MouseEvent): void {
    ziehStart = { x: e.clientX - lage.links, y: e.clientY - lage.oben };
    e.preventDefault();
  }
  function zieh(e: MouseEvent): void {
    if (!ziehStart) return;
    lage.links = Math.max(0, Math.min(window.innerWidth - 120, e.clientX - ziehStart.x));
    lage.oben = Math.max(0, Math.min(window.innerHeight - 60, e.clientY - ziehStart.y));
  }
  function ziehEnde(): void {
    if (ziehStart) speichereLage();
    ziehStart = null;
  }

  function groesseGemerkt(): void {
    if (!fenster) return;
    lage.breite = fenster.offsetWidth;
    lage.hoehe = fenster.offsetHeight;
    speichereLage();
  }

  function hervor(text: string): string {
    if (!woerter.length) return text;
    const escaped = woerter.map((w) => w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    return text.replace(new RegExp(`(${escaped.join("|")})`, "gi"), "$1");
  }

  function teile(text: string): { t: string; m: boolean }[] {
    return hervor(text)
      .split(/([^]*)/)
      .filter((s) => s !== "")
      .map((s) => (s.startsWith("") ? { t: s.slice(1, -1), m: true } : { t: s, m: false }));
  }

  function taste(e: KeyboardEvent): void {
    if (e.key === "Escape") ui.hilfeSchliessen();
  }
</script>

<svelte:window onmousemove={zieh} onmouseup={ziehEnde} onkeydown={ui.hilfeOffen ? taste : undefined} />

{#if ui.hilfeOffen}
  <div
    class="m-hilfe"
    bind:this={fenster}
    style="left: {lage.links}px; top: {lage.oben}px; width: {lage.breite}px; height: {lage.hoehe}px"
    role="dialog"
    aria-label="Hilfe"
    onmouseup={groesseGemerkt}
  >
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <div class="m-hilfe-kopf" onmousedown={ziehBeginn}>
      <i class="fa-solid fa-circle-question"></i> <b>Hilfe</b>
      <span class="ms-auto small opacity-75">Ziehen zum Verschieben, Ecke zum Vergrößern</span>
      <button class="btn btn-sm btn-light" title="Schließen" onclick={() => ui.hilfeSchliessen()}><i class="fa-solid fa-xmark"></i></button>
    </div>
    <div class="m-hilfe-suche">
      <input class="form-control" placeholder="Hilfe durchsuchen ..." bind:value={suche} />
    </div>
    <div class="m-hilfe-koerper">
      <nav class="m-hilfe-inhalt" aria-label="Hilfeabschnitte">
        {#each kategorien as k (k)}
          <div class="px-3 pt-2 pb-1 small text-uppercase text-secondary fw-semibold">{k}</div>
          {#each treffer.filter((a) => a.kategorie === k) as a (a.anker)}
            <a href="#hilfe-{a.anker}" class:aktiv={a.anker === aktiv} onclick={(e) => { e.preventDefault(); aktiv = a.anker; }}>{a.titel}</a>
          {/each}
        {/each}
        {#if !treffer.length}<div class="px-3 py-2 text-secondary">Kein Abschnitt passt zu "{suche}".</div>{/if}
      </nav>
      <div class="m-hilfe-text" bind:this={textfeld}>
        <h2 class="mt-0">{abschnitt.titel}</h2>
        <p class="text-secondary">{abschnitt.kurz}</p>
        {#each abschnitt.bloecke as b, i (i)}
          {#if b.typ === "h2"}
            <h2>{b.text}</h2>
          {:else if b.typ === "absatz"}
            <p>{#each teile(b.text ?? "") as s}{#if s.m}<mark>{s.t}</mark>{:else}{s.t}{/if}{/each}</p>
          {:else if b.typ === "punkte"}
            <ul>{#each b.punkte ?? [] as p}<li>{#each teile(p) as s}{#if s.m}<mark>{s.t}</mark>{:else}{s.t}{/if}{/each}</li>{/each}</ul>
          {:else if b.typ === "schritte"}
            <ol>{#each b.punkte ?? [] as p}<li>{#each teile(p) as s}{#if s.m}<mark>{s.t}</mark>{:else}{s.t}{/if}{/each}</li>{/each}</ol>
          {:else if b.typ === "tipp"}
            <div class="alert alert-success py-2"><i class="fa-solid fa-lightbulb"></i> {b.text}</div>
          {:else if b.typ === "warnung"}
            <div class="alert alert-warning py-2"><i class="fa-solid fa-triangle-exclamation"></i> {b.text}</div>
          {/if}
        {/each}
      </div>
    </div>
  </div>
{/if}
