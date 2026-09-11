<script lang="ts">
  // Ein Video: Originaldaten, Kennzahlen, Reiter Transkript / Korrektur / Themen / Stücke / Aufträge.
  import { onDestroy, onMount } from "svelte";
  import { api, mitParametern } from "../lib/api";
  import type { ChunkEintrag, Korrektur, Seite, Transkript, Vergleich, VideoDetail, ZuruecksetzErgebnis } from "../lib/typen";
  import { ereignisse } from "../lib/stores/ereignisse.svelte";
  import { spieler } from "../lib/stores/spieler.svelte";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { bytes, datum, datumZeit, dauerWorte, dezimal, zahl, zeitmarke, youtubeMitZeit } from "../lib/format";
  import { spieleVideo, spielerVergessen } from "../lib/spielen";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";
  import Bestaetigung from "../lib/komponenten/Bestaetigung.svelte";

  let { id, reiter = "" }: { id: string; reiter?: string } = $props();

  const STUFEN = ["entdeckt", "audio", "transkribiert", "korrigiert", "gestueckelt", "eingebettet"];
  const STUFEN_TITEL: Record<string, string> = { entdeckt: "Entdeckt", audio: "Audio bereit", transkribiert: "Transkribiert", korrigiert: "Korrigiert", gestueckelt: "Gestückelt", eingebettet: "Eingebettet" };
  const AUFTRAGSARTEN: [string, string][] = [["audio", "Audio beschaffen"], ["transkription", "Transkribieren"], ["korrektur", "Korrigieren"], ["stueckelung", "Stückeln"], ["einbettung", "Einbetten"]];
  const REITER: [string, string][] = [["transkript", "Transkript"], ["korrektur", "Korrektur"], ["themen", "Themen"], ["stuecke", "Stücke"], ["auftraege", "Aufträge"]];

  let v = $state<VideoDetail | null>(null);
  let transkript = $state<Transkript | null>(null);
  let korrektur = $state<Korrektur | null>(null);
  let vergleich = $state<Vergleich | null>(null);
  let vergleichModus = $state<"beide" | "korrigiert" | "roh">("beide");
  let nurVerworfene = $state(false);
  let stuecke = $state<Seite<ChunkEintrag> | null>(null);
  let notizen = $state("");
  let notizTimer: number | null = null;
  let loeschDialog = $state(false);
  let zuruecksetzDialog = $state(false);
  let zielStufe = $state("entdeckt");
  let beschaeftigt = $state(false);
  let aktiverReiter = $state("transkript");
  const abos: (() => void)[] = [];

  const aktivesSegment = $derived.by(() => {
    if (!transkript || spieler.video?.id !== id) return -1;
    return transkript.segmente.findIndex((s) => spieler.position >= s.start_s && spieler.position < s.end_s);
  });

  async function laden(): Promise<void> {
    try {
      v = await api.get<VideoDetail>(`/videos/${id}`);
      notizen = v.notizen;
    } catch (e) {
      meldeFehler(e, "Video laden");
      ui.gehe("bibliothek");
      return;
    }
    await ladeReiter();
  }

  async function ladeReiter(): Promise<void> {
    if (!v) return;
    try {
      if (aktiverReiter === "transkript" && v.transkript && !transkript) transkript = await api.get<Transkript>(`/transkripte/${id}`);
      if ((aktiverReiter === "korrektur" || aktiverReiter === "themen") && v.korrektur && !korrektur) korrektur = await api.get<Korrektur>(`/korrekturen/${id}`);
      if (aktiverReiter === "korrektur" && v.korrektur && !vergleich) vergleich = await api.get<Vergleich>(`/korrekturen/${id}/vergleich`);
      if (aktiverReiter === "stuecke" && !stuecke) stuecke = await api.get<Seite<ChunkEintrag>>(mitParametern("/chunks", { video_id: id, je_seite: 500 }));
      if (aktiverReiter === "themen" && v.korrektur && !korrektur) korrektur = await api.get<Korrektur>(`/korrekturen/${id}`);
    } catch (e) {
      meldeFehler(e, "Laden");
    }
  }

  function reiterWechsel(r: string): void {
    aktiverReiter = r;
    ui.gehe("video", id, r);
    void ladeReiter();
  }

  function notizGeaendert(): void {
    if (notizTimer) window.clearTimeout(notizTimer);
    notizTimer = window.setTimeout(async () => {
      try {
        await api.put(`/videos/${id}`, { notizen });
      } catch (e) {
        meldeFehler(e, "Notiz speichern");
      }
    }, 800);
  }

  async function auswahl(an: boolean): Promise<void> {
    try {
      v = await api.put<VideoDetail>(`/videos/${id}`, { ausgewaehlt: an });
      meldungen.gut(an ? "Video im Umfang" : "Video aus dem Umfang genommen");
    } catch (e) {
      meldeFehler(e, "Auswahl");
    }
  }

  async function auftrag(art: string): Promise<void> {
    try {
      const r = await api.post<{ art_titel: string }>(`/videos/${id}/auftrag/${art}`);
      meldungen.gut(`Auftrag angelegt: ${r.art_titel}`);
      await laden();
    } catch (e) {
      meldeFehler(e, "Auftrag");
    }
  }

  async function zuruecksetzen(): Promise<void> {
    beschaeftigt = true;
    try {
      const r = await api.post<ZuruecksetzErgebnis>(`/videos/${id}/zuruecksetzen/${zielStufe}`);
      meldungen.gut(`Zurückgesetzt auf "${STUFEN_TITEL[r.stufe_nachher]}"${r.folgeauftrag_id ? ", Folgeauftrag angelegt" : ""}`);
      zuruecksetzDialog = false;
      transkript = korrektur = vergleich = null;
      stuecke = null;
      spielerVergessen(id);
      await laden();
    } catch (e) {
      meldeFehler(e, "Zurücksetzen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function loeschen(): Promise<void> {
    beschaeftigt = true;
    try {
      await api.del(`/videos/${id}`);
      meldungen.gut("Video gelöscht");
      loeschDialog = false;
      ui.gehe("bibliothek");
    } catch (e) {
      meldeFehler(e, "Löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function blockUebernehmen(index: number): Promise<void> {
    if (!korrektur) return;
    try {
      korrektur = await api.post<Korrektur>(`/korrekturen/${korrektur.id}/bloecke/${index}/uebernehmen`);
      vergleich = await api.get<Vergleich>(`/korrekturen/${id}/vergleich`);
      meldungen.gut("Vorschlag übernommen");
    } catch (e) {
      meldeFehler(e, "Übernehmen");
    }
  }

  onMount(() => {
    aktiverReiter = REITER.some(([k]) => k === reiter) ? reiter : "transkript";
    void laden();
    abos.push(
      ereignisse.abonniere("auftrag_status", (e) => {
        if (e.daten.video_id === id) {
          if (e.daten.status === "fertig") {
            transkript = korrektur = vergleich = null;
            stuecke = null;
            spielerVergessen(id);
          }
          void laden();
        }
      }),
    );
  });
  onDestroy(() => {
    abos.forEach((ab) => ab());
    if (notizTimer) window.clearTimeout(notizTimer);
  });
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <button class="btn btn-sm btn-outline-secondary" title="Zurück zur Bibliothek" onclick={() => ui.gehe("bibliothek")}><i class="fa-solid fa-arrow-left"></i></button>
    {#if v}
      <h1 class="text-truncate" style="max-width: 640px" title={v.titel}>{v.titel}</h1>
      {#if v.serie}<Abzeichen serie={v.serie} folgeNr={v.folge_nr} />{/if}
      <Abzeichen stufe={v.stufe} />
      <InfoKnopf anker="video" />
      <span class="m-luecke"></span>
      {#if v.hat_audio}<button class="btn btn-sm btn-primary" onclick={() => spieleVideo(id)}><i class="fa-solid fa-play"></i> Abspielen</button>{/if}
      <a class="btn btn-sm btn-outline-secondary" href={v.original_url} target="_blank" rel="noreferrer"><i class="fa-brands fa-youtube"></i> Bei YouTube öffnen</a>
      <div class="dropdown">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown"><i class="fa-solid fa-diagram-next"></i> Fließband</button>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><h6 class="dropdown-header">Auftrag anlegen</h6></li>
          {#each AUFTRAGSARTEN as [art, titel]}
            <li><button class="dropdown-item" onclick={() => auftrag(art)}>{titel}</button></li>
          {/each}
          <li><hr class="dropdown-divider" /></li>
          <li><button class="dropdown-item" onclick={() => (zuruecksetzDialog = true)}><i class="fa-solid fa-rotate-left"></i> Auf Stufe zurücksetzen ...</button></li>
          <li><hr class="dropdown-divider" /></li>
          {#if v.ausgewaehlt}
            <li><button class="dropdown-item" onclick={() => auswahl(false)}>Aus dem Umfang nehmen</button></li>
          {:else}
            <li><button class="dropdown-item" onclick={() => auswahl(true)}>In den Umfang aufnehmen</button></li>
          {/if}
        </ul>
      </div>
      <button class="btn btn-sm btn-outline-danger" title="Video mit allen Ergebnissen löschen" onclick={() => (loeschDialog = true)}><i class="fa-solid fa-trash"></i></button>
    {:else}
      <h1>Video</h1>
    {/if}
  </div>

  {#if v}
    <div class="m-ansicht-koerper">
      {#if v.fehler}<div class="alert alert-danger"><i class="fa-solid fa-triangle-exclamation"></i> {v.fehler}</div>{/if}
      <div class="row g-3 mb-3">
        <div class="col-xl-8">
          <div class="card h-100"><div class="card-body">
            <div class="d-flex gap-3 flex-wrap">
              {#if v.miniatur_url}<img class="m-mini gross" src={v.miniatur_url} alt="" />{:else}<div class="m-mini gross"></div>{/if}
              <dl class="row mb-0 flex-grow-1" style="min-width: 260px">
                <dt class="col-sm-4 fw-normal text-secondary">Veröffentlicht</dt><dd class="col-sm-8">{datum(v.veroeffentlicht)}</dd>
                <dt class="col-sm-4 fw-normal text-secondary">Dauer</dt><dd class="col-sm-8">{zeitmarke(v.dauer_s)} ({dauerWorte(v.dauer_s)})</dd>
                <dt class="col-sm-4 fw-normal text-secondary">Aufrufe</dt><dd class="col-sm-8">{zahl(v.aufrufe)}</dd>
                <dt class="col-sm-4 fw-normal text-secondary">Kanal</dt><dd class="col-sm-8">{v.kanal_name || "-"}</dd>
                <dt class="col-sm-4 fw-normal text-secondary">Originaladresse</dt><dd class="col-sm-8"><a href={v.original_url} target="_blank" rel="noreferrer">{v.original_url}</a></dd>
                <dt class="col-sm-4 fw-normal text-secondary">Quelle</dt><dd class="col-sm-8">{v.quelle_heruntergeladen ? "in der Quelle als Datei vorhanden" : "in der Quelle nicht heruntergeladen"} &middot; {v.ausgewaehlt ? "im Umfang" : "nicht im Umfang"}{v.auswahl_manuell ? " (von Hand entschieden)" : ""}</dd>
                {#if v.schlagworte.length}<dt class="col-sm-4 fw-normal text-secondary">Schlagworte</dt><dd class="col-sm-8">{#each v.schlagworte as s}<span class="badge text-bg-light me-1">{s}</span>{/each}</dd>{/if}
              </dl>
            </div>
            {#if v.korrektur?.zusammenfassung}
              <h6 class="mt-3 mb-1 small text-uppercase text-secondary">Kurzzusammenfassung</h6>
              <p class="mb-2" style="font-size: 1.02rem">{v.korrektur.zusammenfassung}</p>
            {/if}
            {#if v.beschreibung}
              <details class="mt-2"><summary class="text-secondary">Beschreibung der Quelle</summary><pre class="mt-2 mb-0" style="white-space: pre-wrap; font-family: inherit">{v.beschreibung}</pre></details>
            {/if}
            <h6 class="mt-3 mb-1 small text-uppercase text-secondary">Notizen <InfoKnopf anker="video" /></h6>
            <textarea class="form-control" rows="2" placeholder="Eigene Notizen zu diesem Video ..." bind:value={notizen} oninput={notizGeaendert}></textarea>
          </div></div>
        </div>
        <div class="col-xl-4">
          <div class="m-kennzahlen">
            <div class="m-kennzahl"><div class="wert">{v.audio ? bytes(v.audio.groesse_bytes) : "-"}</div><div class="titel">Audio{#if v.audio} ({v.audio.format}, {v.audio.bezugsweg}){/if}</div></div>
            <div class="m-kennzahl"><div class="wert">{v.transkript ? zahl(v.transkript.segmente_anzahl) : "-"}</div><div class="titel">Segmente{#if v.transkript} / {zahl(v.transkript.zeichen)} Zeichen{/if}</div></div>
            <div class="m-kennzahl"><div class="wert">{v.korrektur?.aehnlichkeit !== null && v.korrektur?.aehnlichkeit !== undefined ? dezimal(v.korrektur.aehnlichkeit) : "-"}</div><div class="titel">Ähnlichkeit{#if v.korrektur} / {v.korrektur.bloecke_verworfen} von {v.korrektur.bloecke_gesamt} verworfen{/if}</div></div>
            <div class="m-kennzahl"><div class="wert">{zahl(v.chunks_anzahl)}</div><div class="titel">Stücke</div></div>
            {#if v.offener_auftrag}
              <div class="m-kennzahl" style="grid-column: 1 / -1">
                <div class="titel mb-1">{v.offener_auftrag.art_titel} {v.offener_auftrag.status === "laeuft" ? "läuft" : "wartet"}</div>
                <div class="m-fortschritt" class:laeuft={v.offener_auftrag.status === "laeuft"}><span style="width: {Math.round(v.offener_auftrag.fortschritt * 100)}%"></span></div>
                <div class="titel">{v.offener_auftrag.meldung}</div>
              </div>
            {/if}
          </div>
        </div>
      </div>

      <ul class="nav nav-tabs">
        {#each REITER as [k, titel]}
          <li class="nav-item"><a class="nav-link" class:active={aktiverReiter === k} href="#/video/{id}/{k}" onclick={(e) => { e.preventDefault(); reiterWechsel(k); }}>{titel}</a></li>
        {/each}
        {#if aktiverReiter === "korrektur" && vergleich}
          <li class="nav-item ms-auto d-flex align-items-center gap-2 pe-1">
            <div class="btn-group btn-group-sm">
              <button class="btn btn-outline-secondary" class:active={vergleichModus === "beide"} onclick={() => (vergleichModus = "beide")}>Nebeneinander</button>
              <button class="btn btn-outline-secondary" class:active={vergleichModus === "korrigiert"} onclick={() => (vergleichModus = "korrigiert")}>Nur korrigiert</button>
              <button class="btn btn-outline-secondary" class:active={vergleichModus === "roh"} onclick={() => (vergleichModus = "roh")}>Nur roh</button>
            </div>
            <div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" id="nurverw" bind:checked={nurVerworfene} /><label class="form-check-label small" for="nurverw">Nur verworfene</label></div>
          </li>
        {/if}
      </ul>
      <div class="border border-top-0 p-3 bg-body">
        {#if aktiverReiter === "transkript"}
          {#if !v.transkript}
            <div class="m-leer"><i class="fa-solid fa-closed-captioning"></i>Noch kein Transkript.{#if v.stufe === "audio"} <button class="btn btn-sm btn-primary ms-2" onclick={() => auftrag("transkription")}>Jetzt transkribieren</button>{/if}</div>
          {:else if transkript}
            <div class="text-secondary small mb-2">{transkript.modell} &middot; {datumZeit(transkript.erstellt)} &middot; Verarbeitung {dauerWorte(transkript.dauer_verarbeitung_s)} <InfoKnopf anker="korrektur" /></div>
            {#each transkript.segmente as s (s.index)}
              <div class="m-absatz" class:aktiv={aktivesSegment === s.index}>
                <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                <span class="zeit" title="Ab hier abspielen" onclick={() => spieleVideo(id, s.start_s)}>{zeitmarke(s.start_s)}</span>
                <span>{s.text}</span>
              </div>
            {/each}
          {:else}
            <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Transkript wird geladen.</div>
          {/if}
        {:else if aktiverReiter === "korrektur"}
          {#if !v.korrektur}
            <div class="m-leer"><i class="fa-solid fa-spell-check"></i>Noch keine Korrektur.{#if v.stufe === "transkribiert"} <button class="btn btn-sm btn-primary ms-2" onclick={() => auftrag("korrektur")}>Jetzt korrigieren</button>{/if}</div>
          {:else if vergleich && korrektur}
            <div class="text-secondary small mb-2">Korrektur vom {datumZeit(korrektur.erstellt)} &middot; {korrektur.anbieter} ({korrektur.modell}) &middot; {korrektur.bloecke_gesamt} Blöcke, {korrektur.bloecke_verworfen} verworfen, Ähnlichkeit {dezimal(korrektur.aehnlichkeit)} <InfoKnopf anker="korrektur" /></div>
            <div class="m-vergleich" style={vergleichModus === "beide" ? "" : "grid-template-columns: 1fr"}>
              {#each vergleich.bloecke.filter((b) => !nurVerworfene || b.verworfen) as b (b.index)}
                {#if vergleichModus !== "korrigiert"}
                  <div class:verworfen={b.verworfen}>
                    <div class="small text-secondary mb-1">Block {b.index + 1} &middot; {zeitmarke(b.start_s)} bis {zeitmarke(b.end_s)} &middot; Ähnlichkeit {b.aehnlichkeit !== null ? dezimal(b.aehnlichkeit) : "-"} &middot; roh</div>
                    <div>{b.roh}</div>
                  </div>
                {/if}
                {#if vergleichModus !== "roh"}
                  <div class:verworfen={b.verworfen}>
                    <div class="small text-secondary mb-1">{vergleichModus === "korrigiert" ? `Block ${b.index + 1} · ${zeitmarke(b.start_s)} bis ${zeitmarke(b.end_s)} · ` : ""}{b.verworfen ? "verworfen: " + b.grund + " - Rohtext übernommen" : "korrigiert"}</div>
                    {#each b.absaetze as a}<p class="mb-2">{a.text}</p>{/each}
                    {#if b.verworfen && b.vorschlag}
                      <details><summary class="text-secondary">Vorschlag des Modells zeigen</summary><p class="mt-2 text-secondary">{b.vorschlag}</p></details>
                      <button class="btn btn-sm btn-outline-primary mt-1" onclick={() => blockUebernehmen(b.index)}>Trotzdem übernehmen</button>
                    {/if}
                  </div>
                {/if}
              {/each}
            </div>
          {:else}
            <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Korrektur wird geladen.</div>
          {/if}
        {:else if aktiverReiter === "themen"}
          {#if !korrektur?.themen.length}
            <div class="m-leer"><i class="fa-solid fa-list"></i>Keine Themenaufschlüsselung vorhanden.</div>
          {:else}
            {#each korrektur.themen as t, i (i)}
              <div class="m-absatz">
                <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                <span class="zeit" title="Ab hier abspielen" onclick={() => spieleVideo(id, t.start_s)}>{zeitmarke(t.start_s)}</span>
                <div><div class="fw-semibold">{t.titel}</div><div class="text-secondary">{t.kurz}</div><div class="small text-secondary">{zeitmarke(t.start_s)} bis {zeitmarke(t.end_s)}</div></div>
              </div>
            {/each}
          {/if}
        {:else if aktiverReiter === "stuecke"}
          {#if !stuecke}
            <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Stücke werden geladen.</div>
          {:else if !stuecke.eintraege.length}
            <div class="m-leer"><i class="fa-solid fa-scissors"></i>Noch keine Stücke.{#if v.stufe === "korrigiert" || v.stufe === "transkribiert"} <button class="btn btn-sm btn-primary ms-2" onclick={() => auftrag("stueckelung")}>Jetzt stückeln</button>{/if}</div>
          {:else}
            <div class="d-flex justify-content-end mb-2"><button class="btn btn-sm btn-outline-secondary" onclick={() => ui.gehe("stellen")}><i class="fa-solid fa-align-left"></i> Im Textstellen-Browser öffnen</button></div>
            {#each stuecke.eintraege as c (c.id)}
              <div class="m-absatz" style="grid-template-columns: 110px 1fr">
                <div>
                  <div class="fw-semibold">Stück {c.reihenfolge}</div>
                  <!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
                  <span class="zeit" onclick={() => spieleVideo(id, c.start_s)}>{zeitmarke(c.start_s)}</span>
                  <div class="small text-secondary">{zahl(c.zeichen)} Zeichen</div>
                  {#if !c.einbettungen.length}<div class="small text-warning">nicht eingebettet</div>{/if}
                </div>
                <div>
                  {#if c.thema}<div class="small text-secondary mb-1">{c.thema}</div>{/if}
                  <div style="display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden">{c.text}</div>
                  <button class="btn btn-sm btn-link p-0" onclick={() => ui.gehe("stelle", c.id)}>Öffnen</button>
                </div>
              </div>
            {/each}
          {/if}
        {:else if aktiverReiter === "auftraege"}
          {#if !v.auftraege.length}
            <div class="m-leer"><i class="fa-solid fa-list-check"></i>Noch keine Aufträge.</div>
          {:else}
            <div class="m-tabelle-feld">
              <table class="table table-sm table-hover align-middle mb-0">
                <thead><tr><th>Stufe</th><th>Status</th><th>Fortschritt</th><th>Meldung</th><th>Versuche</th><th>Angelegt</th></tr></thead>
                <tbody>
                  {#each v.auftraege as a (a.id)}
                    <tr onclick={() => ui.gehe("auftrag", a.id)}>
                      <td>{a.art_titel}</td>
                      <td><span class="badge text-bg-{a.status === 'fertig' ? 'success' : a.status === 'fehler' ? 'danger' : a.status === 'laeuft' ? 'primary' : 'secondary'}">{a.status === "laeuft" ? "läuft" : a.status}</span></td>
                      <td style="width: 160px"><div class="m-fortschritt"><span style="width: {Math.round(a.fortschritt * 100)}%"></span></div></td>
                      <td class="text-secondary">{a.fehler || a.meldung}</td>
                      <td>{a.versuche}</td>
                      <td class="text-secondary text-nowrap">{datumZeit(a.erstellt)}</td>
                    </tr>
                  {/each}
                </tbody>
              </table>
            </div>
          {/if}
        {/if}
      </div>
    </div>
  {:else}
    <div class="m-ansicht-koerper"><div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Video wird geladen.</div></div>
  {/if}
</section>

{#if v?.korrektur?.themen.length}
  <aside class="m-seite">
    <div class="m-seite-kopf"><i class="fa-solid fa-list"></i> Themen</div>
    <div class="m-seite-koerper">
      {#each v.korrektur.themen as t, i (i)}
        <div class="m-stelle" class:hervor={spieler.video?.id === id && spieler.position >= t.start_s && spieler.position < t.end_s}>
          <div class="kopf"><span class="nr">{i + 1}</span><div><div class="titel">{t.titel}</div><div class="zeit">{zeitmarke(t.start_s)} bis {zeitmarke(t.end_s)}</div></div></div>
          <div class="auszug">{t.kurz}</div>
          <div class="aktionen">
            <button class="btn btn-sm btn-outline-primary" title="Ab {zeitmarke(t.start_s)} abspielen" onclick={() => spieleVideo(id, t.start_s)}><i class="fa-solid fa-play"></i></button>
            <a class="btn btn-sm btn-outline-secondary" title="Bei YouTube ab hier öffnen" href={youtubeMitZeit(v.original_url, t.start_s)} target="_blank" rel="noreferrer"><i class="fa-brands fa-youtube"></i></a>
          </div>
        </div>
      {/each}
    </div>
  </aside>
{/if}

<Bestaetigung bind:offen={zuruecksetzDialog} titel="Auf Stufe zurücksetzen" bestaetigen="Zurücksetzen" gefaehrlich {beschaeftigt} onBestaetigen={zuruecksetzen}>
  <p>Das Video steht auf <b>{STUFEN_TITEL[v?.stufe ?? "entdeckt"]}</b>. Alle Ergebnisse oberhalb der gewählten Stufe werden gelöscht und bei aktiver Automatik neu gerechnet.</p>
  {#each STUFEN.slice(0, Math.max(0, STUFEN.indexOf(v?.stufe ?? "entdeckt"))) as s}
    <div class="form-check"><input class="form-check-input" type="radio" name="zielv" id="zielv-{s}" value={s} bind:group={zielStufe} /><label class="form-check-label" for="zielv-{s}">{STUFEN_TITEL[s]}</label></div>
  {/each}
</Bestaetigung>
<Bestaetigung bind:offen={loeschDialog} titel="Video löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Das Video <b>{v?.titel}</b> wird mit Audio, Transkript, Korrektur, Stücken und Einbettungen aus der Bibliothek entfernt. Beim nächsten Abgleich taucht es wieder auf (dann außerhalb des Umfangs, wenn du es vorher ausgeschlossen hast).</p>
</Bestaetigung>

<style>
  .m-stelle.hervor {
    border-color: var(--m-akzent);
  }
</style>
