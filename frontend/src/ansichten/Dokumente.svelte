<script lang="ts">
  // Dokumente: EPUB, Markdown und Text hochladen, eigene Texte anlegen, Liste mit Stufe und Aufträgen.
  import { onDestroy, onMount } from "svelte";
  import { api, mitParametern } from "../lib/api";
  import type { DokumentArt, DokumentDetail, DokumentEintrag, EigenerText, Seite } from "../lib/typen";
  import { ereignisse } from "../lib/stores/ereignisse.svelte";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { datum, zahl } from "../lib/format";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";
  import Seitenwahl from "../lib/komponenten/Seitenwahl.svelte";
  import Bestaetigung from "../lib/komponenten/Bestaetigung.svelte";

  const STUFEN: [string, string][] = [["importiert", "Importiert"], ["gestueckelt", "Gestückelt"], ["eingebettet", "Eingebettet"]];

  let q = $state("");
  let art = $state("");
  let stufe = $state("");
  let seite = $state(1);
  let jeSeite = $state(50);
  let daten = $state<Seite<DokumentEintrag> | null>(null);
  let arten = $state<DokumentArt[]>([]);
  let laden = $state(false);
  let beschaeftigt = $state(false);
  let dateiEingabe = $state<HTMLInputElement | null>(null);
  let textOffen = $state(false);
  let eigener = $state<EigenerText>({ titel: "", text: "", autor: "", art: "markdown" });
  let loeschDialog = $state(false);
  let ziel = $state<DokumentEintrag | null>(null);
  let suchTimer: number | null = null;
  const abos: (() => void)[] = [];

  const endungen = $derived(arten.flatMap((a) => a.endungen).join(","));

  async function ladeDaten(): Promise<void> {
    laden = true;
    try {
      daten = await api.get<Seite<DokumentEintrag>>(mitParametern("/dokumente", { q, art, stufe, seite, je_seite: jeSeite }));
    } catch (e) {
      meldeFehler(e, "Dokumente laden");
    } finally {
      laden = false;
    }
  }

  function filterGeaendert(): void {
    seite = 1;
    void ladeDaten();
  }

  function sucheGeaendert(): void {
    if (suchTimer) window.clearTimeout(suchTimer);
    suchTimer = window.setTimeout(filterGeaendert, 300);
  }

  async function hochladen(ereignis: Event): Promise<void> {
    const eingabe = ereignis.target as HTMLInputElement;
    const dateien = Array.from(eingabe.files ?? []);
    if (!dateien.length) return;
    beschaeftigt = true;
    try {
      for (const datei of dateien) {
        const formular = new FormData();
        formular.append("datei", datei);
        const d = await api.hochladen<DokumentDetail>("/dokumente/hochladen", formular);
        meldungen.gut(`"${d.titel}" gelesen: ${zahl(d.abschnitte_anzahl)} Abschnitte, ${zahl(d.zeichen)} Zeichen`);
      }
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Hochladen");
    } finally {
      beschaeftigt = false;
      eingabe.value = "";
    }
  }

  async function textAnlegen(): Promise<void> {
    beschaeftigt = true;
    try {
      const d = await api.post<DokumentDetail>("/dokumente/text", eigener);
      meldungen.gut(`"${d.titel}" angelegt: ${zahl(d.abschnitte_anzahl)} Abschnitte`);
      eigener = { titel: "", text: "", autor: "", art: "markdown" };
      textOffen = false;
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Eigener Text");
    } finally {
      beschaeftigt = false;
    }
  }

  async function loeschen(): Promise<void> {
    if (!ziel) return;
    beschaeftigt = true;
    try {
      await api.del(`/dokumente/${ziel.id}`);
      meldungen.gut("Dokument gelöscht");
      loeschDialog = false;
      await ladeDaten();
    } catch (e) {
      meldeFehler(e, "Löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  onMount(() => {
    void ladeDaten();
    void api.get<DokumentArt[]>("/dokumente/arten").then((a) => (arten = a)).catch(() => undefined);
    abos.push(ereignisse.abonniere("dokument", () => void ladeDaten()));
    abos.push(ereignisse.abonniere("auftrag_status", (e) => { if (e.daten.dokument_id) void ladeDaten(); }));
  });
  onDestroy(() => {
    abos.forEach((ab) => ab());
    if (suchTimer) window.clearTimeout(suchTimer);
  });
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <h1>Dokumente</h1>
    <span class="m-unter">{zahl(daten?.gesamt)} Dokumente: Bücher, Texte und eigene Notizen neben den Videos</span>
    <InfoKnopf anker="dokumente" />
    <span class="m-luecke"></span>
    <input class="d-none" type="file" multiple accept={endungen || ".epub,.md,.markdown,.txt"} bind:this={dateiEingabe} onchange={hochladen} />
    <button class="btn btn-sm btn-primary" disabled={beschaeftigt} onclick={() => dateiEingabe?.click()} title="E-Book (EPUB), Markdown oder Text hochladen, auch mehrere Dateien; sie werden sofort in Kapitel gelesen"><i class="fa-solid fa-upload"></i> Hochladen</button>
    <button class="btn btn-sm btn-outline-secondary" class:active={textOffen} onclick={() => (textOffen = !textOffen)} title="Einen eigenen Text direkt hier schreiben; er wird wie ein hochgeladenes Dokument verarbeitet"><i class="fa-solid fa-pen-to-square"></i> Eigener Text</button>
  </div>

  <div class="m-ansicht-koerper d-flex flex-column gap-2" style="overflow: hidden">
    {#if textOffen}
      <div class="card">
        <div class="card-body">
          <div class="d-flex align-items-center gap-2 mb-2"><h6 class="m-0 small text-uppercase text-secondary">Eigenen Text anlegen</h6><InfoKnopf anker="dokumente" finde="Eigener Text" /></div>
          <div class="row g-2">
            <div class="col-md-6"><label class="form-label mb-1" for="et-titel">Titel</label><input class="form-control" id="et-titel" bind:value={eigener.titel} title="Titel des Dokuments, wie er in Belegen erscheint" placeholder="z. B. Notizen zur Kasualisierung" /></div>
            <div class="col-md-4"><label class="form-label mb-1" for="et-autor">Autor</label><input class="form-control" id="et-autor" bind:value={eigener.autor} title="Autorin oder Autor, optional" /></div>
            <div class="col-md-2"><label class="form-label mb-1" for="et-art">Art</label><select class="form-select" id="et-art" bind:value={eigener.art} title="Markdown: Überschriften mit # werden Kapitel, Auszeichnung wird zu Text. Text: ein Abschnitt, Absätze an Leerzeilen."><option value="markdown">Markdown</option><option value="text">Text</option></select></div>
            <div class="col-12"><label class="form-label mb-1" for="et-text">Text (Überschriften mit # eröffnen Kapitel)</label><textarea class="form-control" id="et-text" rows="10" bind:value={eigener.text} title="Der Text; eine Zeile mit # am Anfang eröffnet ein Kapitel, ## ein Unterkapitel" placeholder="# Erstes Kapitel&#10;&#10;Der Text ..."></textarea></div>
            <div class="col-12 d-flex gap-2 align-items-center">
              <span class="small text-secondary">Der Text wird wie ein hochgeladenes Dokument gestückelt und eingebettet.</span>
              <span class="ms-auto"></span>
              <button class="btn btn-outline-secondary" onclick={() => (textOffen = false)}>Abbrechen</button>
              <button class="btn btn-primary" onclick={textAnlegen} disabled={beschaeftigt || !eigener.titel.trim() || !eigener.text.trim()}>Anlegen</button>
            </div>
          </div>
        </div>
      </div>
    {/if}

    <div class="d-flex gap-2 flex-wrap align-items-center">
      <input class="form-control form-control-sm" style="width: 280px" title="Sucht in Titel, Autor und Beschreibung" placeholder="Titel, Autor oder Beschreibung suchen ..." bind:value={q} oninput={sucheGeaendert} />
      <select class="form-select form-select-sm" style="width: 190px" bind:value={art} onchange={filterGeaendert} title="Nur Dokumente dieser Dateiart zeigen">
        <option value="">Alle Arten</option>
        {#each arten as a (a.kennung)}<option value={a.kennung}>{a.titel}</option>{/each}
      </select>
      <select class="form-select form-select-sm" style="width: 170px" bind:value={stufe} onchange={filterGeaendert} title="Nur Dokumente zeigen, die auf dieser Stufe stehen: importiert, gestückelt oder eingebettet">
        <option value="">Alle Stufen</option>
        {#each STUFEN as [k, t] (k)}<option value={k}>{t}</option>{/each}
      </select>
      {#if laden || beschaeftigt}<span class="text-secondary small"><i class="fa-solid fa-circle-notch fa-spin"></i></span>{/if}
    </div>

    <div class="m-tabelle-feld flex-grow-1">
      <table class="table table-hover table-sm align-middle">
        <thead>
          <tr>
            <th>Titel</th>
            <th style="width: 160px">Autor</th>
            <th style="width: 130px">Art</th>
            <th style="width: 110px">Datum</th>
            <th style="width: 150px" class="text-end">Umfang</th>
            <th style="width: 80px" class="text-end">Stücke</th>
            <th style="width: 140px">Stufe</th>
            <th style="width: 220px">Offener Auftrag</th>
            <th style="width: 60px"></th>
          </tr>
        </thead>
        <tbody>
          {#each daten?.eintraege ?? [] as d (d.id)}
            <tr class:table-danger={!!d.fehler} onclick={() => ui.gehe("dokument", d.id)}>
              <td>
                <div class="text-truncate" style="max-width: 520px" title={d.titel}><i class="fa-solid fa-book text-secondary me-1"></i>{d.titel}</div>
                {#if d.fehler}<small class="text-danger">{d.fehler}</small>{/if}
              </td>
              <td class="text-truncate" style="max-width: 160px">{d.autor || "-"}</td>
              <td>{d.art_titel}</td>
              <td class="text-secondary text-nowrap">{datum(d.veroeffentlicht)}</td>
              <td class="text-end text-nowrap">{zahl(d.abschnitte_anzahl)} Abschnitte<br /><small class="text-secondary">{zahl(d.zeichen)} Zeichen</small></td>
              <td class="text-end">{zahl(d.chunks_anzahl)}</td>
              <td><Abzeichen stufe={d.stufe} /></td>
              <td>
                {#if d.offener_auftrag}
                  <div class="m-fortschritt mb-1" class:laeuft={d.offener_auftrag.status === "laeuft"}><span style="width: {Math.round(d.offener_auftrag.fortschritt * 100)}%"></span></div>
                  <small class="text-secondary">{d.offener_auftrag.art_titel}{d.offener_auftrag.status === "wartend" ? " (wartet)" : ""}</small>
                {/if}
              </td>
              <td onclick={(e) => e.stopPropagation()}>
                <button class="btn btn-sm btn-outline-danger" title="Dokument löschen" onclick={() => { ziel = d; loeschDialog = true; }}><i class="fa-solid fa-trash"></i></button>
              </td>
            </tr>
          {/each}
          {#if daten && !daten.eintraege.length}
            <tr><td colspan="9" class="text-center text-secondary py-5">Noch keine Dokumente. Lade ein E-Book (EPUB), eine Markdown- oder Textdatei hoch oder lege einen eigenen Text an.</td></tr>
          {/if}
        </tbody>
      </table>
    </div>

    <div class="d-flex align-items-center gap-2 flex-wrap">
      <span class="ms-auto"></span>
      {#if daten}<Seitenwahl bind:seite bind:jeSeite gesamt={daten.gesamt} onWechsel={ladeDaten} />{/if}
    </div>
  </div>
</section>

<Bestaetigung bind:offen={loeschDialog} titel="Dokument löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Das Dokument <b>{ziel?.titel}</b> wird samt Abschnitten, Stücken, Einbettungen und Originaldatei entfernt. Belege in bestehenden Antworten verlieren ihren Sprung.</p>
</Bestaetigung>
