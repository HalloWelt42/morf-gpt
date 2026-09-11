<script lang="ts">
  // Ein Dokument: Metadaten (von Hand pflegbar), Kapitelnavigation, Leseansicht, Stücke je Kapitel, Aufträge.
  import { onDestroy, onMount, tick } from "svelte";
  import { api } from "../lib/api";
  import type { DokumentAenderung, DokumentDetail, DokumentInhalt } from "../lib/typen";
  import { ereignisse } from "../lib/stores/ereignisse.svelte";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { bytes, datum, datumZeit, zahl } from "../lib/format";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";
  import Bestaetigung from "../lib/komponenten/Bestaetigung.svelte";

  let { id, abschnitt = "" }: { id: string; abschnitt?: string } = $props();

  const AUFTRAGSARTEN: [string, string][] = [["stueckelung", "Stückeln"], ["einbettung", "Einbetten"]];
  const FELD_TITEL: Record<string, string> = { titel: "Titel", autor: "Autor", sprache: "Sprache", beschreibung: "Beschreibung", veroeffentlicht: "Datum" };

  interface Pflegeformular {
    titel: string;
    autor: string;
    sprache: string;
    veroeffentlicht: string;
    beschreibung: string;
  }

  let d = $state<DokumentDetail | null>(null);
  let inhalt = $state<DokumentInhalt | null>(null);
  let notizen = $state("");
  let notizTimer: number | null = null;
  let bearbeiten = $state(false);
  let pflege = $state<Pflegeformular>({ titel: "", autor: "", sprache: "de", veroeffentlicht: "", beschreibung: "" });
  let loeschDialog = $state(false);
  let beschaeftigt = $state(false);
  let aktiverAbschnitt = $state<number | null>(null);
  const abos: (() => void)[] = [];

  async function laden(): Promise<void> {
    try {
      d = await api.get<DokumentDetail>(`/dokumente/${id}`);
      notizen = d.notizen;
      inhalt = await api.get<DokumentInhalt>(`/dokumente/${id}/inhalt`);
    } catch (e) {
      meldeFehler(e, "Dokument laden");
      ui.gehe("dokumente");
      return;
    }
    await tick();
    const nr = Number(abschnitt);
    // Erst nach dem Aufbau der Leseansicht springen; sonst greift der Sprung ins Leere.
    if (abschnitt && Number.isFinite(nr)) window.setTimeout(() => springe(nr), 80);
  }

  function springe(nr: number): void {
    aktiverAbschnitt = nr;
    document.getElementById(`abschnitt-${nr}`)?.scrollIntoView({ block: "start", behavior: "smooth" });
  }

  function notizGeaendert(): void {
    if (notizTimer) window.clearTimeout(notizTimer);
    notizTimer = window.setTimeout(async () => {
      try {
        await api.put(`/dokumente/${id}`, { notizen });
      } catch (e) {
        meldeFehler(e, "Notiz speichern");
      }
    }, 800);
  }

  function pflegeStarten(): void {
    if (!d) return;
    pflege = { titel: d.titel, autor: d.autor, sprache: d.sprache, veroeffentlicht: d.veroeffentlicht ? d.veroeffentlicht.slice(0, 10) : "", beschreibung: d.beschreibung };
    bearbeiten = true;
  }

  async function pflegeSpeichern(): Promise<void> {
    beschaeftigt = true;
    try {
      const a: DokumentAenderung = { titel: pflege.titel.trim() || undefined, autor: pflege.autor.trim(), sprache: pflege.sprache.trim() || "de", beschreibung: pflege.beschreibung };
      if (pflege.veroeffentlicht) a.veroeffentlicht = `${pflege.veroeffentlicht}T00:00:00`;
      d = await api.put<DokumentDetail>(`/dokumente/${id}`, a);
      bearbeiten = false;
      meldungen.gut("Metadaten gespeichert");
    } catch (e) {
      meldeFehler(e, "Metadaten speichern");
    } finally {
      beschaeftigt = false;
    }
  }

  async function handpflegeAufheben(): Promise<void> {
    try {
      d = await api.put<DokumentDetail>(`/dokumente/${id}`, { handpflege_aufheben: true });
      meldungen.gut("Handpflege aufgehoben");
    } catch (e) {
      meldeFehler(e, "Handpflege aufheben");
    }
  }

  async function auftrag(art: string): Promise<void> {
    try {
      const r = await api.post<{ art_titel: string }>(`/dokumente/${id}/auftrag/${art}`);
      meldungen.gut(`Auftrag angelegt: ${r.art_titel}`);
      await laden();
    } catch (e) {
      meldeFehler(e, "Auftrag");
    }
  }

  async function loeschen(): Promise<void> {
    beschaeftigt = true;
    try {
      await api.del(`/dokumente/${id}`);
      meldungen.gut("Dokument gelöscht");
      loeschDialog = false;
      ui.gehe("dokumente");
    } catch (e) {
      meldeFehler(e, "Löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  function absaetze(text: string): string[] {
    return text.split(/\n\s*\n/).map((a) => a.trim()).filter(Boolean);
  }

  onMount(() => {
    void laden();
    abos.push(ereignisse.abonniere("auftrag_status", (e) => { if (e.daten.dokument_id === id) void laden(); }));
    abos.push(ereignisse.abonniere("dokument", (e) => { if (e.daten.dokument_id === id && e.daten.aktion !== "geloescht") void laden(); }));
  });
  onDestroy(() => {
    abos.forEach((ab) => ab());
    if (notizTimer) window.clearTimeout(notizTimer);
  });
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <button class="btn btn-sm btn-outline-secondary" title="Zurück zu den Dokumenten" onclick={() => ui.gehe("dokumente")}><i class="fa-solid fa-arrow-left"></i></button>
    {#if d}
      <h1 class="text-truncate" style="max-width: 640px" title={d.titel}><i class="fa-solid fa-book text-secondary"></i> {d.titel}</h1>
      <Abzeichen stufe={d.stufe} />
      <InfoKnopf anker="dokumente" />
      <span class="m-luecke"></span>
      <a class="btn btn-sm btn-outline-secondary" href="/api/dokumente/{d.id}/datei" target="_blank" rel="noreferrer" title="Originaldatei herunterladen"><i class="fa-solid fa-download"></i> {d.art_titel}</a>
      <button class="btn btn-sm btn-outline-secondary" class:active={bearbeiten} title="Titel, Autor, Datum und Beschreibung von Hand pflegen" onclick={() => (bearbeiten ? (bearbeiten = false) : pflegeStarten())}><i class="fa-solid fa-pen"></i> Bearbeiten</button>
      <div class="dropdown">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown" title="Stückeln oder Einbetten für dieses Dokument neu anstoßen"><i class="fa-solid fa-diagram-next"></i> Fließband</button>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><h6 class="dropdown-header">Auftrag anlegen</h6></li>
          {#each AUFTRAGSARTEN as [art, titel] (art)}
            <li><button class="dropdown-item" onclick={() => auftrag(art)} title={art === "stueckelung" ? "Alle Stücke des Dokuments neu bilden (Einbettungen fallen mit)" : "Alle Stücke mit dem aktiven Einbettungsmodell neu einbetten"}>{titel}</button></li>
          {/each}
        </ul>
      </div>
      <button class="btn btn-sm btn-outline-danger" title="Dokument mit allen Ergebnissen löschen" onclick={() => (loeschDialog = true)}><i class="fa-solid fa-trash"></i></button>
    {:else}
      <h1>Dokument</h1>
    {/if}
  </div>

  {#if d}
    <div class="m-ansicht-koerper d-flex flex-column gap-3" style="overflow: hidden">
      {#if d.fehler}<div class="alert alert-danger mb-0"><i class="fa-solid fa-triangle-exclamation"></i> {d.fehler}</div>{/if}
      <div class="row g-3">
        <div class="col-xl-8">
          <div class="card h-100"><div class="card-body">
            {#if bearbeiten}
              <div class="d-flex align-items-center gap-2 mb-2"><h6 class="m-0 small text-uppercase text-secondary">Metadaten von Hand pflegen</h6><InfoKnopf anker="pflege" /></div>
              <div class="row g-2">
                <div class="col-12"><label class="form-label mb-1" for="pf-titel">Titel</label><input class="form-control" id="pf-titel" bind:value={pflege.titel} title="Titel, wie er in Belegen und Listen erscheint" /></div>
                <div class="col-md-5"><label class="form-label mb-1" for="pf-autor">Autor</label><input class="form-control" id="pf-autor" bind:value={pflege.autor} title="Autorin oder Autor des Dokuments" /></div>
                <div class="col-md-3"><label class="form-label mb-1" for="pf-datum">Datum</label><input class="form-control" id="pf-datum" type="date" bind:value={pflege.veroeffentlicht} title="Datum der Veröffentlichung; der Zeitraum-Filter im Chat nutzt es" /></div>
                <div class="col-md-4"><label class="form-label mb-1" for="pf-sprache">Sprache</label><input class="form-control" id="pf-sprache" bind:value={pflege.sprache} title="Sprachkürzel des Textes, zum Beispiel de oder en" /></div>
                <div class="col-12"><label class="form-label mb-1" for="pf-besch">Beschreibung</label><textarea class="form-control" id="pf-besch" rows="3" bind:value={pflege.beschreibung} title="Kurzbeschreibung; wird angezeigt, aber nicht eingebettet"></textarea></div>
                <div class="col-12 d-flex gap-2 align-items-center">
                  <span class="ms-auto"></span>
                  <button class="btn btn-outline-secondary" onclick={() => (bearbeiten = false)}>Abbrechen</button>
                  <button class="btn btn-primary" onclick={pflegeSpeichern} disabled={beschaeftigt || !pflege.titel.trim()}>Speichern</button>
                </div>
              </div>
            {:else}
              <dl class="row mb-0">
                <dt class="col-sm-3 fw-normal text-secondary">Autor</dt><dd class="col-sm-9">{d.autor || "-"}</dd>
                <dt class="col-sm-3 fw-normal text-secondary">Art</dt><dd class="col-sm-9">{d.art_titel} &middot; Sprache {d.sprache}</dd>
                <dt class="col-sm-3 fw-normal text-secondary">Datum</dt><dd class="col-sm-9">{datum(d.veroeffentlicht)}</dd>
                <dt class="col-sm-3 fw-normal text-secondary">Datei</dt><dd class="col-sm-9"><code>{d.dateiname || "-"}</code>{#if d.groesse_bytes} &middot; {bytes(d.groesse_bytes)}{/if} &middot; importiert {datumZeit(d.erstellt)}</dd>
                <dt class="col-sm-3 fw-normal text-secondary">Umfang</dt><dd class="col-sm-9">{zahl(d.abschnitte_anzahl)} Abschnitte, {zahl(d.zeichen)} Zeichen, {zahl(d.chunks_anzahl)} Stücke</dd>
                {#if d.felder_manuell.length}<dt class="col-sm-3 fw-normal text-secondary">Von Hand gepflegt</dt><dd class="col-sm-9">{d.felder_manuell.map((f) => FELD_TITEL[f] ?? f).join(", ")} <button class="btn btn-sm btn-link p-0 align-baseline" onclick={handpflegeAufheben} title="Die von Hand gepflegten Felder wieder freigeben; ein erneuter Import darf sie dann überschreiben">aufheben</button></dd>{/if}
              </dl>
              {#if d.beschreibung}
                <details class="mt-2"><summary class="text-secondary">Beschreibung</summary><pre class="mt-2 mb-0" style="white-space: pre-wrap; font-family: inherit">{d.beschreibung}</pre></details>
              {/if}
            {/if}
            <h6 class="mt-3 mb-1 small text-uppercase text-secondary">Notizen</h6>
            <textarea class="form-control" rows="2" title="Eigene Notizen; werden gespeichert, aber nicht eingebettet und nicht durchsucht" placeholder="Eigene Notizen zu diesem Dokument ..." bind:value={notizen} oninput={notizGeaendert}></textarea>
          </div></div>
        </div>
        <div class="col-xl-4">
          <div class="m-kennzahlen">
            <div class="m-kennzahl"><div class="wert">{zahl(d.abschnitte_anzahl)}</div><div class="titel">Abschnitte</div></div>
            <div class="m-kennzahl"><div class="wert">{zahl(d.zeichen)}</div><div class="titel">Zeichen</div></div>
            <div class="m-kennzahl"><div class="wert">{zahl(d.chunks_anzahl)}</div><div class="titel">Stücke</div></div>
            <div class="m-kennzahl"><div class="wert">{d.stufe_titel}</div><div class="titel">Stufe</div></div>
            {#if d.offener_auftrag}
              <div class="m-kennzahl" style="grid-column: 1 / -1">
                <div class="titel mb-1">{d.offener_auftrag.art_titel} {d.offener_auftrag.status === "laeuft" ? "läuft" : "wartet"}</div>
                <div class="m-fortschritt" class:laeuft={d.offener_auftrag.status === "laeuft"}><span style="width: {Math.round(d.offener_auftrag.fortschritt * 100)}%"></span></div>
                <div class="titel">{d.offener_auftrag.meldung}</div>
              </div>
            {/if}
          </div>
        </div>
      </div>

      <div class="d-flex gap-3 flex-grow-1" style="min-height: 0">
        <nav class="m-kapitel" aria-label="Kapitel">
          <div class="m-seite-kopf"><i class="fa-solid fa-list"></i> Kapitel <InfoKnopf anker="dokumente" finde="Kapitel" /></div>
          <div class="m-seite-koerper p-0">
            {#each d.abschnitte as a (a.id)}
              <button class="m-kapitel-eintrag ebene-{a.ebene}" class:aktiv={aktiverAbschnitt === a.reihenfolge} onclick={() => springe(a.reihenfolge)} title="Zum Abschnitt in der Leseansicht springen; die Zahl ist die Anzahl seiner Stücke">
                <span class="text-truncate">{a.titel || `Abschnitt ${a.reihenfolge}`}</span>
                <span class="badge text-bg-light ms-auto" title="Stücke in diesem Abschnitt">{a.chunks_anzahl}</span>
              </button>
            {/each}
          </div>
        </nav>
        <div class="m-lesen flex-grow-1">
          {#if inhalt}
            {#each inhalt.abschnitte as a (a.id)}
              <article id="abschnitt-{a.reihenfolge}" class="m-lesen-abschnitt" class:aktiv={aktiverAbschnitt === a.reihenfolge}>
                {#if a.ebene <= 1}<h2>{a.titel}</h2>{:else if a.ebene === 2}<h3>{a.titel}</h3>{:else}<h4>{a.titel}</h4>{/if}
                <div class="small text-secondary mb-2">{zahl(a.zeichen)} Zeichen &middot; {a.chunks_anzahl} Stücke{#if a.seite_von} &middot; Seite {a.seite_von}{#if a.seite_bis && a.seite_bis !== a.seite_von} bis {a.seite_bis}{/if}{/if}</div>
                {#each absaetze(a.text) as p}<p>{p}</p>{/each}
              </article>
            {/each}
          {:else}
            <p class="text-secondary">Inhalt wird geladen ...</p>
          {/if}
        </div>
      </div>
    </div>
  {/if}
</section>

<Bestaetigung bind:offen={loeschDialog} titel="Dokument löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Das Dokument <b>{d?.titel}</b> wird samt Abschnitten, Stücken, Einbettungen und Originaldatei entfernt.</p>
</Bestaetigung>

<style>
  .m-kapitel {
    width: 280px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    min-height: 0;
    border: 1px solid var(--m-rand);
    background: var(--m-flaeche);
  }
  .m-kapitel .m-seite-koerper {
    overflow-y: auto;
    min-height: 0;
  }
  .m-kapitel-eintrag {
    display: flex;
    align-items: center;
    gap: 6px;
    width: 100%;
    border: 0;
    background: transparent;
    color: var(--m-text-2);
    text-align: left;
    padding: 6px 12px;
    font-size: 0.9rem;
  }
  .m-kapitel-eintrag.ebene-2 {
    padding-left: 24px;
  }
  .m-kapitel-eintrag.ebene-3 {
    padding-left: 36px;
    font-size: 0.85rem;
  }
  .m-kapitel-eintrag.aktiv,
  .m-kapitel-eintrag:hover {
    background: var(--m-akzent-hell);
    color: var(--m-akzent);
  }
  .m-lesen {
    min-height: 0;
    overflow-y: auto;
    border: 1px solid var(--m-rand);
    background: var(--m-flaeche);
    padding: 18px 28px;
    font-size: 1.08rem;
    line-height: 1.65;
  }
  .m-lesen-abschnitt {
    max-width: 78ch;
    padding-bottom: 16px;
    margin-bottom: 16px;
    border-bottom: 1px solid var(--m-rand);
  }
  .m-lesen-abschnitt.aktiv h2,
  .m-lesen-abschnitt.aktiv h3,
  .m-lesen-abschnitt.aktiv h4 {
    color: var(--m-akzent);
  }
  .m-lesen h2 {
    font-size: 1.4rem;
    margin: 8px 0 4px;
  }
  .m-lesen h3 {
    font-size: 1.15rem;
    margin: 8px 0 4px;
  }
  .m-lesen h4 {
    font-size: 1.02rem;
    margin: 8px 0 4px;
  }
</style>
