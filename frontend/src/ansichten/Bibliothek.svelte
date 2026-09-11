<script lang="ts">
  // Bibliothek: alle Videos der Quelle mit Filtern, Auswahl im Umfang, Stufe, Stapelaktionen.
  import { onDestroy, onMount } from "svelte";
  import { api, mitParametern } from "../lib/api";
  import type { AuswahlRegelErgebnis, AuswahlStapelErgebnis, Seite, SerieEintrag, VideoEintrag } from "../lib/typen";
  import { ereignisse } from "../lib/stores/ereignisse.svelte";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { datum, zahl, zeitmarke } from "../lib/format";
  import { spieleVideo } from "../lib/spielen";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";
  import Seitenwahl from "../lib/komponenten/Seitenwahl.svelte";
  import Bestaetigung from "../lib/komponenten/Bestaetigung.svelte";

  const STUFEN = ["entdeckt", "audio", "transkribiert", "korrigiert", "gestueckelt", "eingebettet"];
  const STUFEN_TITEL: Record<string, string> = { entdeckt: "Entdeckt", audio: "Audio bereit", transkribiert: "Transkribiert", korrigiert: "Korrigiert", gestueckelt: "Gestückelt", eingebettet: "Eingebettet" };

  let q = $state("");
  let serie = $state("");
  let stufe = $state("");
  let auswahl = $state<"" | "true" | "false">("true");
  let typ = $state("");
  let sortierung = $state("veroeffentlicht");
  let richtung = $state<"auf" | "ab">("ab");
  let seite = $state(1);
  let jeSeite = $state(50);
  let daten = $state<Seite<VideoEintrag> | null>(null);
  let serien = $state<SerieEintrag[]>([]);
  let markiert = $state<Set<string>>(new Set());
  let laden = $state(false);
  let regelDialog = $state(false);
  let zuruecksetzDialog = $state(false);
  let zielStufe = $state("entdeckt");
  let beschaeftigt = $state(false);
  let suchTimer: number | null = null;
  const abos: (() => void)[] = [];

  async function ladeDaten(): Promise<void> {
    laden = true;
    try {
      daten = await api.get<Seite<VideoEintrag>>(
        mitParametern("/videos", { q, serie: serie === "__ohne__" ? "" : serie || undefined, stufe, ausgewaehlt: auswahl, typ, sortierung, richtung, seite, je_seite: jeSeite }),
      );
    } catch (e) {
      meldeFehler(e, "Videos laden");
    } finally {
      laden = false;
    }
  }

  async function ladeSerien(): Promise<void> {
    try {
      serien = await api.get<SerieEintrag[]>("/videos/serien");
    } catch {
      // nicht kritisch
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

  function sortiere(spalte: string): void {
    if (sortierung === spalte) richtung = richtung === "ab" ? "auf" : "ab";
    else {
      sortierung = spalte;
      richtung = spalte === "titel" ? "auf" : "ab";
    }
    filterGeaendert();
  }

  function umschalten(id: string): void {
    const neu = new Set(markiert);
    if (neu.has(id)) neu.delete(id);
    else neu.add(id);
    markiert = neu;
  }

  function alleUmschalten(): void {
    const alle = daten?.eintraege.map((v) => v.id) ?? [];
    markiert = alle.every((id) => markiert.has(id)) ? new Set() : new Set(alle);
  }

  async function stapelAuswahl(an: boolean): Promise<void> {
    try {
      const r = await api.post<AuswahlStapelErgebnis>("/videos/auswahl/stapel", { video_ids: [...markiert], ausgewaehlt: an });
      meldungen.gut(`${zahl(r.geaendert)} Videos ${an ? "aufgenommen" : "aus dem Umfang genommen"}${r.auftraege_angelegt ? `, ${zahl(r.auftraege_angelegt)} Aufträge angelegt` : ""}`);
      markiert = new Set();
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Auswahl");
    }
  }

  async function vorziehen(): Promise<void> {
    try {
      for (const id of markiert) await api.put(`/videos/${id}`, { prioritaet: 100 });
      meldungen.gut(`${zahl(markiert.size)} Videos vorgezogen`);
      markiert = new Set();
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Vorziehen");
    }
  }

  async function zuruecksetzen(): Promise<void> {
    beschaeftigt = true;
    let n = 0;
    try {
      for (const id of markiert) {
        try {
          await api.post(`/videos/${id}/zuruecksetzen/${zielStufe}`);
          n++;
        } catch {
          // Video steht schon auf oder unter der Zielstufe
        }
      }
      meldungen.gut(`${zahl(n)} Videos auf "${STUFEN_TITEL[zielStufe]}" zurückgesetzt`);
      zuruecksetzDialog = false;
      markiert = new Set();
      await ladeDaten();
    } finally {
      beschaeftigt = false;
    }
  }

  async function regelAnwenden(): Promise<void> {
    beschaeftigt = true;
    try {
      const r = await api.post<AuswahlRegelErgebnis>("/videos/auswahl/regel");
      meldungen.gut(`Regel angewendet: ${zahl(r.aufgenommen)} aufgenommen, ${zahl(r.entfernt)} entfernt, ${zahl(r.unveraendert)} unverändert`);
      regelDialog = false;
      await ladeDaten();
      await ladeSerien();
    } catch (e) {
      meldeFehler(e, "Auswahlregel");
    } finally {
      beschaeftigt = false;
    }
  }

  async function einzelAuswahl(v: VideoEintrag, an: boolean): Promise<void> {
    try {
      await api.put(`/videos/${v.id}`, { ausgewaehlt: an });
      v.ausgewaehlt = an;
      v.auswahl_manuell = true;
    } catch (e) {
      meldeFehler(e, "Auswahl");
      await ladeDaten();
    }
  }

  let nachladen: number | null = null;
  onMount(() => {
    void ladeDaten();
    void ladeSerien();
    abos.push(
      ereignisse.abonniere("auftrag_status", () => {
        if (nachladen) return;
        nachladen = window.setTimeout(() => { nachladen = null; void ladeDaten(); }, 2000);
      }),
    );
  });
  onDestroy(() => {
    abos.forEach((ab) => ab());
    if (nachladen) window.clearTimeout(nachladen);
  });
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <h1>Bibliothek</h1>
    <span class="m-unter">{zahl(daten?.gesamt)} Videos{#if auswahl === "true"} im Umfang{/if}</span>
    <InfoKnopf anker="bibliothek" />
    <span class="m-luecke"></span>
    <button class="btn btn-sm btn-outline-secondary" title="Auswahlregel auf alle nicht von Hand entschiedenen Videos anwenden" onclick={() => (regelDialog = true)}><i class="fa-solid fa-wand-magic-sparkles"></i> Auswahlregel anwenden</button>
  </div>

  <div class="m-ansicht-koerper d-flex flex-column gap-2" style="overflow: hidden">
    <div class="d-flex gap-2 flex-wrap align-items-center">
      <input class="form-control form-control-sm" style="width: 280px" title="Sucht in Titel und Beschreibung der Videos" placeholder="Titel oder Beschreibung suchen ..." bind:value={q} oninput={sucheGeaendert} />
      <select class="form-select form-select-sm" style="width: 170px" bind:value={serie} onchange={filterGeaendert} title="Nur Videos dieser Serie zeigen">
        <option value="">Alle Serien</option>
        {#each serien as s (s.serie)}<option value={s.serie || "__ohne__"}>{s.serie || "Ohne Serie"} ({s.anzahl})</option>{/each}
      </select>
      <select class="form-select form-select-sm" style="width: 170px" bind:value={stufe} onchange={filterGeaendert} title="Nur Videos zeigen, die auf dieser Stufe des Fließbands stehen">
        <option value="">Alle Stufen</option>
        {#each STUFEN as s}<option value={s}>{STUFEN_TITEL[s]}</option>{/each}
      </select>
      <select class="form-select form-select-sm" style="width: 170px" bind:value={auswahl} onchange={filterGeaendert} title="Im Umfang heißt: das Video wird auf dem Fließband verarbeitet">
        <option value="true">Im Umfang</option>
        <option value="false">Nicht im Umfang</option>
        <option value="">Alle</option>
      </select>
      <select class="form-select form-select-sm" style="width: 140px" bind:value={typ} onchange={filterGeaendert} title="Nur Videos dieser Art zeigen (Video, Livestream, Short)">
        <option value="">Alle Arten</option>
        <option value="video">Video</option>
        <option value="live">Livestream</option>
        <option value="short">Short</option>
      </select>
      {#if laden}<span class="text-secondary small"><i class="fa-solid fa-circle-notch fa-spin"></i></span>{/if}
    </div>

    <div class="m-tabelle-feld flex-grow-1">
      <table class="table table-hover table-sm align-middle">
        <thead>
          <tr>
            <th style="width: 34px"><input class="form-check-input" type="checkbox" title="Alle Videos dieser Seite markieren, um sie unten gemeinsam zu behandeln (aufnehmen, ausschließen, Aufträge anlegen)" checked={!!daten?.eintraege.length && daten.eintraege.every((v) => markiert.has(v.id))} onchange={alleUmschalten} /></th>
            <th style="width: 52px" title="Im Umfang: der Schalter sagt, ob das Video auf dem Fließband verarbeitet wird"><i class="fa-solid fa-circle-check"></i></th>
            <th style="width: 72px"></th>
            <th class="sortierbar" onclick={() => sortiere("titel")}>Titel {#if sortierung === "titel"}<i class="fa-solid fa-caret-{richtung === 'ab' ? 'down' : 'up'}"></i>{/if}</th>
            <th style="width: 100px" class="sortierbar" onclick={() => sortiere("folge")}>Serie {#if sortierung === "folge"}<i class="fa-solid fa-caret-{richtung === 'ab' ? 'down' : 'up'}"></i>{/if}</th>
            <th style="width: 120px" class="sortierbar" onclick={() => sortiere("veroeffentlicht")}>Datum {#if sortierung === "veroeffentlicht"}<i class="fa-solid fa-caret-{richtung === 'ab' ? 'down' : 'up'}"></i>{/if}</th>
            <th style="width: 80px" class="sortierbar text-end" onclick={() => sortiere("dauer")}>Dauer {#if sortierung === "dauer"}<i class="fa-solid fa-caret-{richtung === 'ab' ? 'down' : 'up'}"></i>{/if}</th>
            <th style="width: 150px" class="sortierbar" onclick={() => sortiere("stufe")}>Stufe {#if sortierung === "stufe"}<i class="fa-solid fa-caret-{richtung === 'ab' ? 'down' : 'up'}"></i>{/if}</th>
            <th style="width: 220px">Offener Auftrag</th>
            <th style="width: 90px"></th>
          </tr>
        </thead>
        <tbody>
          {#each daten?.eintraege ?? [] as v (v.id)}
            <tr class:gewaehlt={markiert.has(v.id)} class:table-danger={!!v.fehler} onclick={() => ui.gehe("video", v.id)}>
              <td onclick={(e) => e.stopPropagation()}><input class="form-check-input" type="checkbox" title="Markieren, um dieses Video mit anderen gemeinsam zu behandeln" checked={markiert.has(v.id)} onchange={() => umschalten(v.id)} /></td>
              <td onclick={(e) => e.stopPropagation()}>
                <div class="form-check form-switch mb-0 m-umfang"><input class="form-check-input" type="checkbox" role="switch" title={v.ausgewaehlt ? "Im Umfang: wird auf dem Fließband verarbeitet; klicken zum Ausschließen" : "Nicht im Umfang: bleibt unverarbeitet; klicken zum Aufnehmen"} checked={v.ausgewaehlt} onchange={(e) => einzelAuswahl(v, (e.target as HTMLInputElement).checked)} /></div>
              </td>
              <td>{#if v.miniatur_url}<img class="m-mini" src={v.miniatur_url} alt="" loading="lazy" />{:else}<div class="m-mini"></div>{/if}</td>
              <td>
                <div class="text-truncate" style="max-width: 520px" title={v.titel}>{v.titel}</div>
                {#if v.fehler}<small class="text-danger">{v.fehler}</small>{/if}
              </td>
              <td>{#if v.serie}<Abzeichen serie={v.serie} folgeNr={v.folge_nr} />{/if}</td>
              <td class="text-secondary text-nowrap">{datum(v.veroeffentlicht)}</td>
              <td class="text-end text-nowrap">{zeitmarke(v.dauer_s)}</td>
              <td><Abzeichen stufe={v.stufe} /></td>
              <td>
                {#if v.offener_auftrag}
                  <div class="m-fortschritt mb-1" class:laeuft={v.offener_auftrag.status === "laeuft"}><span style="width: {Math.round(v.offener_auftrag.fortschritt * 100)}%"></span></div>
                  <small class="text-secondary">{v.offener_auftrag.art_titel}{v.offener_auftrag.status === "wartend" ? " (wartet)" : ""}</small>
                {/if}
              </td>
              <td onclick={(e) => e.stopPropagation()}>
                {#if v.hat_audio}<button class="btn btn-sm btn-outline-primary" title="Abspielen" onclick={() => spieleVideo(v.id)}><i class="fa-solid fa-play"></i></button>{/if}
                <a class="btn btn-sm btn-outline-secondary" title="Bei YouTube öffnen" href={v.original_url} target="_blank" rel="noreferrer"><i class="fa-brands fa-youtube"></i></a>
              </td>
            </tr>
          {/each}
          {#if daten && !daten.eintraege.length}
            <tr><td colspan="10" class="text-center text-secondary py-5">Keine Videos zu diesen Filtern.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>

    <div class="d-flex align-items-center gap-2 flex-wrap">
      {#if markiert.size}
        <span class="fw-semibold">{zahl(markiert.size)} markiert:</span>
        <button class="btn btn-sm btn-outline-primary" onclick={() => stapelAuswahl(true)} title="Die markierten Videos werden verarbeitet; bei aktiver Automatik entstehen sofort die nächsten Aufträge">In den Umfang aufnehmen</button>
        <button class="btn btn-sm btn-outline-secondary" onclick={() => stapelAuswahl(false)} title="Die markierten Videos werden nicht weiter verarbeitet; wartende Aufträge werden abgebrochen, Fertiges bleibt">Aus dem Umfang nehmen</button>
        <button class="btn btn-sm btn-outline-secondary" onclick={vorziehen} title="Die markierten Videos bekommen Vorrang auf dem Fließband"><i class="fa-solid fa-arrow-up"></i> Vorziehen</button>
        <button class="btn btn-sm btn-outline-danger" onclick={() => (zuruecksetzDialog = true)} title="Ergebnisse oberhalb einer Stufe löschen und neu rechnen lassen (fragt nach)"><i class="fa-solid fa-rotate-left"></i> Zurücksetzen auf Stufe ...</button>
      {/if}
      <span class="ms-auto"></span>
      {#if daten}<Seitenwahl bind:seite bind:jeSeite gesamt={daten.gesamt} onWechsel={ladeDaten} />{/if}
    </div>
  </div>
</section>

<Bestaetigung bind:offen={regelDialog} titel="Auswahlregel anwenden" bestaetigen="Anwenden" {beschaeftigt} onBestaetigen={regelAnwenden}>
  <p>Alle Videos, die nicht von Hand entschieden wurden, werden nach der Regel aus den Einstellungen (Mindestdauer, Arten, nur heruntergeladene) neu in den Umfang aufgenommen oder herausgenommen. Bei aktiver Automatik entstehen dabei Folgeaufträge.</p>
</Bestaetigung>

<Bestaetigung bind:offen={zuruecksetzDialog} titel="Auf Stufe zurücksetzen" bestaetigen="Zurücksetzen" gefaehrlich {beschaeftigt} onBestaetigen={zuruecksetzen}>
  <p>Die markierten Videos werden auf die gewählte Stufe zurückgesetzt. Alle Ergebnisse oberhalb (Stücke, Einbettungen, Korrektur, Transkript, Audio) werden gelöscht und bei aktiver Automatik neu gerechnet.</p>
  {#each STUFEN.slice(0, 5) as s}
    <div class="form-check">
      <input class="form-check-input" type="radio" name="ziel" id="ziel-{s}" value={s} bind:group={zielStufe} />
      <label class="form-check-label" for="ziel-{s}">{STUFEN_TITEL[s]}</label>
    </div>
  {/each}
</Bestaetigung>

<style>
  .sortierbar {
    cursor: pointer;
    user-select: none;
  }
</style>
