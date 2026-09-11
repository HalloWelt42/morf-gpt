<script lang="ts">
  // Textstellen: alle Stücke durchblättern, suchen, ein Stück rechts in voller Länge mit
  // markierter Überlappung, Aktionen (bearbeiten, teilen, zusammenlegen, neu einbetten).
  import { onMount } from "svelte";
  import { api, mitParametern } from "../lib/api";
  import type { ChunkDetail, ChunkEintrag, Seite, SerieEintrag } from "../lib/typen";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { zahl, zeitmarke, youtubeMitZeit, datumZeit } from "../lib/format";
  import { spieleVideo } from "../lib/spielen";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";
  import Seitenwahl from "../lib/komponenten/Seitenwahl.svelte";
  import Bestaetigung from "../lib/komponenten/Bestaetigung.svelte";

  let q = $state("");
  let serie = $state("");
  let thema = $state("");
  let ohneEinbettung = $state(false);
  let seite = $state(1);
  let jeSeite = $state(25);
  let daten = $state<Seite<ChunkEintrag> | null>(null);
  let serien = $state<SerieEintrag[]>([]);
  let themen = $state<string[]>([]);
  let gewaehlt = $state<ChunkDetail | null>(null);
  let laden = $state(false);
  let zusammenDialog = $state(false);
  let loeschDialog = $state(false);
  let beschaeftigt = $state(false);
  let suchTimer: number | null = null;

  async function ladeDaten(): Promise<void> {
    laden = true;
    try {
      daten = await api.get<Seite<ChunkEintrag>>(mitParametern("/chunks", { q, serie, thema, ohne_einbettung: ohneEinbettung || undefined, seite, je_seite: jeSeite }));
      if (daten.eintraege.length && (!gewaehlt || !daten.eintraege.some((c) => c.id === gewaehlt?.id))) await waehle(daten.eintraege[0].id);
      if (!daten.eintraege.length) gewaehlt = null;
    } catch (e) {
      meldeFehler(e, "Textstellen laden");
    } finally {
      laden = false;
    }
  }

  async function waehle(id: string): Promise<void> {
    try {
      gewaehlt = await api.get<ChunkDetail>(`/chunks/${id}`);
    } catch (e) {
      meldeFehler(e, "Textstelle laden");
    }
  }

  function filterGeaendert(): void {
    seite = 1;
    void ladeDaten();
  }

  function sucheGeaendert(): void {
    if (suchTimer) window.clearTimeout(suchTimer);
    suchTimer = window.setTimeout(filterGeaendert, 350);
  }

  /** Text in drei Teile: Überlappung zum Vorgänger, Kern, Überlappung zum Nachfolger. */
  function teile(c: ChunkDetail): { vor: string; kern: string; nach: string } {
    const t = c.text;
    const vor = c.ueberlappung_vor > 0 ? t.slice(0, Math.min(c.ueberlappung_vor, t.length)) : "";
    const nachStart = c.ueberlappung_nach > 0 ? Math.max(vor.length, t.length - c.ueberlappung_nach) : t.length;
    return { vor, kern: t.slice(vor.length, nachStart), nach: t.slice(nachStart) };
  }

  async function einbetten(): Promise<void> {
    if (!gewaehlt) return;
    beschaeftigt = true;
    try {
      const r = await api.post<{ modell: string }>(`/chunks/${gewaehlt.id}/einbetten`);
      meldungen.gut(`Eingebettet mit ${r.modell}`);
      await waehle(gewaehlt.id);
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Einbetten");
    } finally {
      beschaeftigt = false;
    }
  }

  async function zusammenlegen(): Promise<void> {
    if (!gewaehlt) return;
    beschaeftigt = true;
    try {
      const r = await api.post<{ chunk: ChunkDetail; hinweis: string }>(`/chunks/${gewaehlt.id}/zusammenlegen`);
      meldungen.gut(r.hinweis);
      gewaehlt = r.chunk;
      zusammenDialog = false;
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Zusammenlegen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function loeschen(): Promise<void> {
    if (!gewaehlt) return;
    beschaeftigt = true;
    try {
      await api.del(`/chunks/${gewaehlt.id}`);
      meldungen.gut("Stück gelöscht");
      loeschDialog = false;
      gewaehlt = null;
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function neuStueckeln(): Promise<void> {
    if (!gewaehlt) return;
    try {
      if (gewaehlt.werkart === "dokument") {
        const r = await api.post<{ art_titel: string }>(`/dokumente/${gewaehlt.dokument_id}/auftrag/stueckelung`);
        meldungen.gut(`Auftrag angelegt: ${r.art_titel}`);
        return;
      }
      const r = await api.post<{ hinweis: string }>(`/chunks/video/${gewaehlt.video_id}/neu`);
      meldungen.gut(r.hinweis);
    } catch (e) {
      meldeFehler(e, "Neu stückeln");
    }
  }

  onMount(() => {
    void ladeDaten();
    void api.get<SerieEintrag[]>("/videos/serien").then((s) => (serien = s)).catch(() => undefined);
    void api.get<string[]>("/chunks/themen").then((t) => (themen = t)).catch(() => undefined);
  });
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <h1>Textstellen</h1>
    <span class="m-unter">{zahl(daten?.gesamt)} Stücke</span>
    <InfoKnopf anker="stellen" />
    <span class="m-luecke"></span>
  </div>
  <div class="m-ansicht-koerper d-flex flex-column gap-2" style="overflow: hidden">
    <div class="d-flex gap-2 flex-wrap align-items-center">
      <input class="form-control form-control-sm" style="width: 300px" title="Sucht im Text der Stücke und in den Titeln der Werke" placeholder="Volltext oder Videotitel suchen ..." bind:value={q} oninput={sucheGeaendert} />
      <select class="form-select form-select-sm" style="width: 160px" bind:value={serie} onchange={filterGeaendert} title="Nur Stücke aus Videos dieser Serie zeigen">
        <option value="">Alle Serien</option>
        {#each serien.filter((s) => s.serie) as s (s.serie)}<option value={s.serie}>{s.serie}</option>{/each}
      </select>
      <input class="form-control form-control-sm" style="width: 220px" title="Nur Stücke, deren Thema (Themenaufschlüsselung oder Kapitel) diesen Text enthält" placeholder="Thema enthält ..." list="themenliste" bind:value={thema} oninput={sucheGeaendert} />
      <datalist id="themenliste">{#each themen.slice(0, 200) as t}<option value={t}></option>{/each}</datalist>
      <div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" id="ohne" bind:checked={ohneEinbettung} title="Nur Stücke zeigen, die noch keinen Vektor haben und darum im Chat nicht gefunden werden" onchange={filterGeaendert} /><label class="form-check-label small" for="ohne">nur ohne Einbettung</label></div>
      {#if laden}<span class="text-secondary small"><i class="fa-solid fa-circle-notch fa-spin"></i></span>{/if}
    </div>
    <div class="flex-grow-1" style="min-height: 0; overflow-y: auto">
      {#each daten?.eintraege ?? [] as c (c.id)}
        <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
        <div class="m-stelle" class:hervor={gewaehlt?.id === c.id} onclick={() => waehle(c.id)} style="cursor: pointer">
          <div class="kopf">
            {#if c.miniatur_url}<img class="m-mini" src={c.miniatur_url} alt="" loading="lazy" />{/if}
            <div class="flex-grow-1" style="min-width: 0">
              <div class="titel">{#if c.werkart === "dokument"}<i class="fa-solid fa-book text-secondary"></i> {/if}{c.video_titel}</div>
              <div class="zeit">{#if c.serie}<Abzeichen serie={c.serie} folgeNr={c.folge_nr} /> &middot;{/if} Stück {c.reihenfolge} von {c.anzahl_im_video} &middot; {#if c.werkart === "dokument"}{c.abschnitt ? `Kapitel: ${c.abschnitt}` : "Dokument"}{:else}{zeitmarke(c.start_s)} bis {zeitmarke(c.end_s)}{/if}{#if c.thema && c.thema !== c.abschnitt} &middot; {c.thema}{/if}</div>
            </div>
          </div>
          <div class="auszug">{c.text}</div>
          <div class="aktionen">
            <span class="small text-secondary">{zahl(c.zeichen)} Zeichen &middot; {c.einbettungen.length ? `eingebettet (${c.einbettungen.join(", ")})` : "Einbettung fehlt"}{c.manuell_bearbeitet ? " · von Hand bearbeitet" : ""}</span>
            <span class="ms-auto"></span>
            {#if c.werkart === "dokument"}
              <button class="btn btn-sm btn-outline-primary" title="Im Dokument lesen" onclick={(e) => { e.stopPropagation(); ui.gehe("dokument", c.dokument_id, c.abschnitt_nr === null ? "" : String(c.abschnitt_nr)); }}><i class="fa-solid fa-book-open"></i></button>
            {:else}
              <button class="btn btn-sm btn-outline-primary" title="Ab {zeitmarke(c.start_s)} abspielen" onclick={(e) => { e.stopPropagation(); void spieleVideo(c.video_id, c.start_s); }}><i class="fa-solid fa-play"></i></button>
              {#if c.original_url}<a class="btn btn-sm btn-outline-secondary" title="Bei YouTube öffnen" href={youtubeMitZeit(c.original_url, c.start_s)} target="_blank" rel="noreferrer" onclick={(e) => e.stopPropagation()}><i class="fa-brands fa-youtube"></i></a>{/if}
            {/if}
            <button class="btn btn-sm btn-outline-secondary" title="Bearbeiten" onclick={(e) => { e.stopPropagation(); ui.gehe("stelle", c.id); }}><i class="fa-solid fa-pen"></i></button>
          </div>
        </div>
      {/each}
      {#if daten && !daten.eintraege.length}<div class="m-leer"><i class="fa-solid fa-align-left"></i>Keine Stücke zu diesen Filtern.</div>{/if}
    </div>
    {#if daten}<Seitenwahl bind:seite bind:jeSeite gesamt={daten.gesamt} auswahl={[10, 25, 50, 100]} onWechsel={ladeDaten} />{/if}
  </div>
</section>

<aside class="m-seite" style="width: 460px">
  <div class="m-seite-kopf"><i class="fa-solid fa-file-lines"></i> {gewaehlt ? `Stück ${gewaehlt.reihenfolge} von ${gewaehlt.anzahl_im_video}` : "Stück"}</div>
  <div class="m-seite-koerper">
    {#if gewaehlt}
      {@const t = teile(gewaehlt)}
      <div class="fw-semibold">{gewaehlt.video_titel}</div>
      <div class="text-secondary small mb-2">{#if gewaehlt.werkart === "dokument"}{gewaehlt.abschnitt ? `Kapitel: ${gewaehlt.abschnitt}` : "Dokument"}{:else}{zeitmarke(gewaehlt.start_s)} bis {zeitmarke(gewaehlt.end_s)}{/if}{#if gewaehlt.thema && gewaehlt.thema !== gewaehlt.abschnitt} &middot; {gewaehlt.thema}{/if} &middot; {zahl(gewaehlt.zeichen)} Zeichen</div>
      <div class="d-flex gap-1 flex-wrap mb-2">
        {#if gewaehlt.werkart === "dokument"}
          <button class="btn btn-sm btn-outline-primary" onclick={() => ui.gehe("dokument", gewaehlt!.dokument_id, gewaehlt!.abschnitt_nr === null ? "" : String(gewaehlt!.abschnitt_nr))} title="Das Kapitel dieses Stücks in der Leseansicht öffnen"><i class="fa-solid fa-book-open"></i> Im Dokument lesen</button>
        {:else}
          <button class="btn btn-sm btn-outline-primary" onclick={() => spieleVideo(gewaehlt!.video_id, gewaehlt!.start_s)} title="Ab dem Anfang dieses Stücks im eigenen Spieler abspielen"><i class="fa-solid fa-play"></i> Abspielen</button>
        {/if}
        <button class="btn btn-sm btn-outline-secondary" onclick={() => ui.gehe("stelle", gewaehlt!.id)} title="Text des Stücks bearbeiten oder teilen"><i class="fa-solid fa-pen"></i> Bearbeiten</button>
        <button class="btn btn-sm btn-outline-secondary" onclick={() => (zusammenDialog = true)} disabled={!gewaehlt.naechster} title="Dieses und das nächste Stück zu einem verbinden; die Überlappung wird nicht doppelt genommen (fragt nach)"><i class="fa-solid fa-object-group"></i> Mit nächstem zusammenlegen</button>
        <button class="btn btn-sm btn-outline-secondary" onclick={einbetten} disabled={beschaeftigt} title="Nur dieses Stück mit dem aktiven Einbettungsmodell neu einbetten"><i class="fa-solid fa-cube"></i> Neu einbetten</button>
        <button class="btn btn-sm btn-outline-secondary" onclick={neuStueckeln} title="Alle Stücke dieses Werks neu bilden"><i class="fa-solid fa-scissors"></i> {gewaehlt.werkart === "dokument" ? "Dokument" : "Video"} neu stückeln</button>
        <button class="btn btn-sm btn-outline-danger" onclick={() => (loeschDialog = true)} title="Dieses Stück löschen (fragt nach)"><i class="fa-solid fa-trash"></i></button>
      </div>
      <div class="small text-secondary mb-2">
        Einbettung: {#if gewaehlt.einbettung_details.length}{#each gewaehlt.einbettung_details as e}{e.modell} ({e.dimension} Dimensionen, {datumZeit(e.erstellt)}) {/each}{:else}<span class="text-warning">fehlt</span>{/if}
      </div>
      <div style="font-size: 1.02rem; line-height: 1.6; white-space: pre-wrap">{#if t.vor}<span class="ueberlappung" title="Überlappung mit dem vorigen Stück ({gewaehlt.ueberlappung_vor} Zeichen)">{t.vor}</span>{/if}{t.kern}{#if t.nach}<span class="ueberlappung" title="Überlappung mit dem nächsten Stück ({gewaehlt.ueberlappung_nach} Zeichen)">{t.nach}</span>{/if}</div>
      <hr />
      {#if gewaehlt.vorheriger}
        <div class="small text-secondary">Vorheriges Stück ({zeitmarke(gewaehlt.vorheriger.start_s)}): <button class="btn btn-sm btn-link p-0" onclick={() => waehle(gewaehlt!.vorheriger!.id)}>öffnen</button></div>
        <div class="small text-truncate text-secondary">{gewaehlt.vorheriger.text.slice(0, 160)} ...</div>
      {/if}
      {#if gewaehlt.naechster}
        <div class="small text-secondary mt-2">Nächstes Stück ({zeitmarke(gewaehlt.naechster.start_s)}): <button class="btn btn-sm btn-link p-0" onclick={() => waehle(gewaehlt!.naechster!.id)}>öffnen</button></div>
        <div class="small text-truncate text-secondary">{gewaehlt.naechster.text.slice(0, 160)} ...</div>
      {/if}
    {:else}
      <div class="text-secondary">Links ein Stück wählen.</div>
    {/if}
  </div>
</aside>

<Bestaetigung bind:offen={zusammenDialog} titel="Stücke zusammenlegen" bestaetigen="Zusammenlegen" {beschaeftigt} onBestaetigen={zusammenlegen}>
  <p>Stück {gewaehlt?.reihenfolge} wird mit dem nächsten Stück zu einem verbunden; die Überlappung wird dabei nicht doppelt genommen. Danach muss das Stück neu eingebettet werden.</p>
</Bestaetigung>
<Bestaetigung bind:offen={loeschDialog} titel="Stück löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Das Stück wird samt Einbettung gelöscht; die übrigen Stücke werden neu durchnummeriert.</p>
</Bestaetigung>

<style>
  .m-stelle.hervor {
    border-color: var(--m-akzent);
    box-shadow: 0 0 0 2px var(--m-akzent-hell);
  }
  .ueberlappung {
    background: var(--m-akzent-hell);
  }
</style>
