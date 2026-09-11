<script lang="ts">
  // Ein Video: Originaldaten, Kennzahlen, Reiter Transkript / Korrektur / Themen / Stücke / Aufträge.
  import { onDestroy, onMount } from "svelte";
  import { api, mitParametern } from "../lib/api";
  import type { ChunkEintrag, Korrektur, Seite, Transkript, Vergleich, VideoDetail, VideoPflege, ZuruecksetzErgebnis } from "../lib/typen";
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
  // Welcher Hilfeabschnitt den Schritt hinter einem Reiter erklärt.
  const REITER_HILFE: Record<string, string> = { transkript: "stufe-transkription", korrektur: "stufe-korrektur", themen: "stufe-korrektur", stuecke: "stufe-stueckelung", auftraege: "fliessband" };
  const FELD_TITEL: Record<string, string> = { titel: "Titel", beschreibung: "Beschreibung", veroeffentlicht: "Datum", dauer_s: "Dauer", typ: "Art", original_url: "Originaladresse", kanal_name: "Kanal", serie: "Serie", folge_nr: "Folge", schlagworte: "Schlagworte" };

  interface Pflegeformular {
    titel: string;
    beschreibung: string;
    veroeffentlicht: string;
    dauer_s: string;
    typ: string;
    original_url: string;
    kanal_name: string;
    serie: string;
    folge_nr: string;
    schlagworte: string;
  }

  let v = $state<VideoDetail | null>(null);
  let transkript = $state<Transkript | null>(null);
  let korrektur = $state<Korrektur | null>(null);
  let vergleich = $state<Vergleich | null>(null);
  let vergleichModus = $state<"beide" | "korrigiert" | "roh">("beide");
  let nurVerworfene = $state(false);
  let stuecke = $state<Seite<ChunkEintrag> | null>(null);
  let notizen = $state("");
  let notizTimer: number | null = null;
  let bearbeiten = $state(false);
  let pflege = $state<Pflegeformular>({ titel: "", beschreibung: "", veroeffentlicht: "", dauer_s: "", typ: "video", original_url: "", kanal_name: "", serie: "", folge_nr: "", schlagworte: "" });
  let bildStand = $state(0);
  let bildEingabe = $state<HTMLInputElement | null>(null);
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

  function pflegeStarten(): void {
    if (!v) return;
    pflege = {
      titel: v.titel,
      beschreibung: v.beschreibung,
      veroeffentlicht: v.veroeffentlicht ? v.veroeffentlicht.slice(0, 10) : "",
      dauer_s: v.dauer_s === null ? "" : String(v.dauer_s),
      typ: v.typ || "video",
      original_url: v.original_url,
      kanal_name: v.kanal_name,
      serie: v.serie,
      folge_nr: v.folge_nr === null ? "" : String(v.folge_nr),
      schlagworte: v.schlagworte.join(", "),
    };
    bearbeiten = true;
  }

  function pflegeAlsAenderung(): VideoPflege {
    const a: VideoPflege = {
      titel: pflege.titel.trim() || undefined,
      beschreibung: pflege.beschreibung,
      typ: pflege.typ.trim() || "video",
      original_url: pflege.original_url.trim(),
      kanal_name: pflege.kanal_name.trim(),
      serie: pflege.serie.trim(),
      schlagworte: pflege.schlagworte.split(",").map((w) => w.trim()).filter(Boolean),
    };
    if (pflege.veroeffentlicht) a.veroeffentlicht = `${pflege.veroeffentlicht}T00:00:00`;
    const dauer = Number(pflege.dauer_s);
    if (pflege.dauer_s.trim() !== "" && Number.isFinite(dauer) && dauer >= 0) a.dauer_s = Math.round(dauer);
    const folge = Number(pflege.folge_nr);
    if (pflege.folge_nr.trim() === "") a.folge_nr_loeschen = true;
    else if (Number.isFinite(folge) && folge >= 0) a.folge_nr = Math.round(folge);
    return a;
  }

  async function pflegeSpeichern(): Promise<void> {
    beschaeftigt = true;
    try {
      v = await api.put<VideoDetail>(`/videos/${id}`, pflegeAlsAenderung());
      bearbeiten = false;
      meldungen.gut("Metadaten gespeichert; der Abgleich lässt diese Felder jetzt stehen");
    } catch (e) {
      meldeFehler(e, "Metadaten speichern");
    } finally {
      beschaeftigt = false;
    }
  }

  async function handpflegeAufheben(): Promise<void> {
    try {
      v = await api.put<VideoDetail>(`/videos/${id}`, { handpflege_aufheben: true });
      meldungen.gut("Handpflege aufgehoben; der nächste Abgleich übernimmt wieder die Werte der Quelle");
    } catch (e) {
      meldeFehler(e, "Handpflege aufheben");
    }
  }

  async function bildHochladen(ereignis: Event): Promise<void> {
    const eingabe = ereignis.target as HTMLInputElement;
    const datei = eingabe.files?.[0];
    if (!datei) return;
    const formular = new FormData();
    formular.append("datei", datei);
    beschaeftigt = true;
    try {
      v = await api.hochladen<VideoDetail>(`/videos/${id}/miniatur`, formular);
      bildStand = Date.now();
      meldungen.gut("Vorschaubild gesetzt");
    } catch (e) {
      meldeFehler(e, "Vorschaubild");
    } finally {
      beschaeftigt = false;
      eingabe.value = "";
    }
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
      {#if v.hat_audio}<button class="btn btn-sm btn-primary" onclick={() => spieleVideo(id)} title="Im eigenen Spieler ab Anfang abspielen"><i class="fa-solid fa-play"></i> Abspielen</button>{/if}
      {#if v.original_url}
        <a class="btn btn-sm btn-outline-secondary" href={v.original_url} target="_blank" rel="noreferrer">{#if v.original_url.includes("youtu")}<i class="fa-brands fa-youtube"></i> Bei YouTube öffnen{:else}<i class="fa-solid fa-up-right-from-square"></i> Original öffnen{/if}</a>
      {/if}
      <button class="btn btn-sm btn-outline-secondary" class:active={bearbeiten} title="Titel, Datum, Serie, Adresse und weitere Metadaten von Hand pflegen" onclick={() => (bearbeiten ? (bearbeiten = false) : pflegeStarten())}><i class="fa-solid fa-pen"></i> Bearbeiten</button>
      <div class="dropdown">
        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" data-bs-toggle="dropdown" title="Einzelne Stufen neu anstoßen, auf eine Stufe zurücksetzen oder den Umfang ändern"><i class="fa-solid fa-diagram-next"></i> Fließband</button>
        <ul class="dropdown-menu dropdown-menu-end">
          <li><h6 class="dropdown-header">Auftrag anlegen</h6></li>
          {#each AUFTRAGSARTEN as [art, titel]}
            <li><button class="dropdown-item" onclick={() => auftrag(art)}>{titel}</button></li>
          {/each}
          <li><hr class="dropdown-divider" /></li>
          <li><button class="dropdown-item" onclick={() => (zuruecksetzDialog = true)} title="Ergebnisse oberhalb einer Stufe löschen und neu rechnen lassen (fragt nach)"><i class="fa-solid fa-rotate-left"></i> Auf Stufe zurücksetzen ...</button></li>
          <li><hr class="dropdown-divider" /></li>
          {#if v.ausgewaehlt}
            <li><button class="dropdown-item" onclick={() => auswahl(false)} title="Das Video wird nicht weiter verarbeitet; wartende Aufträge werden abgebrochen">Aus dem Umfang nehmen</button></li>
          {:else}
            <li><button class="dropdown-item" onclick={() => auswahl(true)} title="Das Video wird verarbeitet; bei aktiver Automatik entsteht sofort der nächste Auftrag">In den Umfang aufnehmen</button></li>
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
              <div class="flex-shrink-0">
                {#if v.miniatur_url}<img class="m-mini gross" src={bildStand ? `${v.miniatur_url}?v=${bildStand}` : v.miniatur_url} alt="" />{:else}<div class="m-mini gross"></div>{/if}
                <input class="d-none" type="file" accept="image/jpeg,image/png,image/webp" bind:this={bildEingabe} onchange={bildHochladen} />
                <button class="btn btn-sm btn-outline-secondary mt-2 w-100" title="Eigenes Vorschaubild setzen (JPEG, PNG oder WebP)" disabled={beschaeftigt} onclick={() => bildEingabe?.click()}><i class="fa-solid fa-image"></i> Bild wählen</button>
              </div>
              {#if bearbeiten}
                <div class="flex-grow-1" style="min-width: 260px">
                  <div class="d-flex align-items-center gap-2 mb-2"><h6 class="m-0 small text-uppercase text-secondary">Metadaten von Hand pflegen</h6><InfoKnopf anker="pflege" /></div>
                  <div class="row g-2">
                    <div class="col-12"><label class="form-label mb-1" for="pf-titel">Titel</label><input class="form-control" id="pf-titel" bind:value={pflege.titel} title="Titel, wie er in Belegen und Listen erscheint" /></div>
                    <div class="col-md-3"><label class="form-label mb-1" for="pf-datum">Datum</label><input class="form-control" id="pf-datum" type="date" bind:value={pflege.veroeffentlicht} title="Datum der Veröffentlichung; der Zeitraum-Filter im Chat nutzt es" /></div>
                    <div class="col-md-3"><label class="form-label mb-1" for="pf-dauer">Dauer</label><div class="input-group"><input class="form-control" id="pf-dauer" type="number" min="0" bind:value={pflege.dauer_s} title="Dauer in Sekunden; die Aufnahmeregel vergleicht damit die Mindestdauer" /><span class="input-group-text">s</span></div></div>
                    <div class="col-md-3"><label class="form-label mb-1" for="pf-serie">Serie</label><input class="form-control" id="pf-serie" placeholder="z. B. mmM" bind:value={pflege.serie} title="Kürzel der Serie; steuert Reihenfolge auf dem Fließband und die Anzeige der Belege" /></div>
                    <div class="col-md-3"><label class="form-label mb-1" for="pf-folge">Folge</label><input class="form-control" id="pf-folge" type="number" min="0" placeholder="leer = keine" title="Folgennummer innerhalb der Serie; leer lassen, wenn es keine gibt" bind:value={pflege.folge_nr} /></div>
                    <div class="col-md-8"><label class="form-label mb-1" for="pf-url">Originaladresse (YouTube oder andere)</label><input class="form-control" id="pf-url" placeholder="https://youtu.be/..." bind:value={pflege.original_url} title="Adresse des Originals; Belege springen dorthin an die Sekunde, bei YouTube mit Zeitmarke" /></div>
                    <div class="col-md-4"><label class="form-label mb-1" for="pf-typ">Art</label><select class="form-select" id="pf-typ" bind:value={pflege.typ} title="Art des Werks; die Aufnahmeregel kann Arten ausschließen"><option value="video">Video</option><option value="live">Livestream</option><option value="short">Short</option><option value="audio">Audio</option></select></div>
                    <div class="col-md-4"><label class="form-label mb-1" for="pf-kanal">Kanal</label><input class="form-control" id="pf-kanal" bind:value={pflege.kanal_name} title="Name des Kanals oder der Urheberin" /></div>
                    <div class="col-md-8"><label class="form-label mb-1" for="pf-schlag">Schlagworte (durch Komma getrennt)</label><input class="form-control" id="pf-schlag" bind:value={pflege.schlagworte} title="Schlagworte, durch Komma getrennt; nur zur Anzeige und Suche in der Bibliothek" /></div>
                    <div class="col-12"><label class="form-label mb-1" for="pf-besch">Beschreibung</label><textarea class="form-control" id="pf-besch" rows="3" bind:value={pflege.beschreibung} title="Beschreibung der Quelle oder eigene; wird angezeigt, aber nicht eingebettet"></textarea></div>
                    <div class="col-12 d-flex gap-2 align-items-center flex-wrap">
                      <span class="small text-secondary">Gespeicherte Felder gelten als von Hand gepflegt; der Abgleich mit der Quelle überschreibt sie nicht mehr.</span>
                      <span class="ms-auto"></span>
                      <button class="btn btn-outline-secondary" onclick={() => (bearbeiten = false)}>Abbrechen</button>
                      <button class="btn btn-primary" onclick={pflegeSpeichern} disabled={beschaeftigt || !pflege.titel.trim()}>Speichern</button>
                    </div>
                  </div>
                </div>
              {:else}
              <dl class="row mb-0 flex-grow-1" style="min-width: 260px">
                <dt class="col-sm-4 fw-normal text-secondary">Veröffentlicht</dt><dd class="col-sm-8">{datum(v.veroeffentlicht)}</dd>
                <dt class="col-sm-4 fw-normal text-secondary">Dauer</dt><dd class="col-sm-8">{zeitmarke(v.dauer_s)} ({dauerWorte(v.dauer_s)})</dd>
                {#if v.aufrufe !== null}<dt class="col-sm-4 fw-normal text-secondary">Aufrufe</dt><dd class="col-sm-8">{zahl(v.aufrufe)}</dd>{/if}
                <dt class="col-sm-4 fw-normal text-secondary">Kanal</dt><dd class="col-sm-8">{v.kanal_name || "-"}</dd>
                <dt class="col-sm-4 fw-normal text-secondary">Originaladresse</dt><dd class="col-sm-8">{#if v.original_url}<a href={v.original_url} target="_blank" rel="noreferrer">{v.original_url}</a>{:else}<span class="text-secondary">keine (über Bearbeiten nachtragen)</span>{/if}</dd>
                {#if v.datei_pfad}<dt class="col-sm-4 fw-normal text-secondary">Datei</dt><dd class="col-sm-8"><code>{v.datei_pfad}</code></dd>{/if}
                <dt class="col-sm-4 fw-normal text-secondary">Quelle</dt><dd class="col-sm-8">{#if v.quelle_typ === "lokal"}lokale Datei aus dem Verzeichnis der Quelle{:else if !v.quelle_id}ohne Quelle{:else}{v.quelle_heruntergeladen ? "in der Quelle als Datei vorhanden" : "in der Quelle nicht heruntergeladen"}{/if} &middot; {v.ausgewaehlt ? "im Umfang" : "nicht im Umfang"}{v.auswahl_manuell ? " (von Hand entschieden)" : ""}</dd>
                {#if v.felder_manuell.length}<dt class="col-sm-4 fw-normal text-secondary">Von Hand gepflegt</dt><dd class="col-sm-8">{v.felder_manuell.map((f) => FELD_TITEL[f] ?? f).join(", ")} <button class="btn btn-sm btn-link p-0 align-baseline" title="Der nächste Abgleich übernimmt wieder die Werte der Quelle" onclick={handpflegeAufheben}>aufheben</button> <InfoKnopf anker="pflege" /></dd>{/if}
                {#if v.schlagworte.length}<dt class="col-sm-4 fw-normal text-secondary">Schlagworte</dt><dd class="col-sm-8">{#each v.schlagworte as s}<span class="badge text-bg-light me-1">{s}</span>{/each}</dd>{/if}
              </dl>
              {/if}
            </div>
            {#if v.korrektur?.zusammenfassung}
              <h6 class="mt-3 mb-1 small text-uppercase text-secondary">Kurzzusammenfassung</h6>
              <p class="mb-2" style="font-size: 1.02rem">{v.korrektur.zusammenfassung}</p>
            {/if}
            {#if v.beschreibung}
              <details class="mt-2"><summary class="text-secondary">Beschreibung der Quelle</summary><pre class="mt-2 mb-0" style="white-space: pre-wrap; font-family: inherit">{v.beschreibung}</pre></details>
            {/if}
            <h6 class="mt-3 mb-1 small text-uppercase text-secondary">Notizen <InfoKnopf anker="video" /></h6>
            <textarea class="form-control" rows="2" title="Eigene Notizen; werden gespeichert, aber nicht eingebettet und nicht durchsucht" placeholder="Eigene Notizen zu diesem Video ..." bind:value={notizen} oninput={notizGeaendert}></textarea>
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
          <li class="nav-item"><a class="nav-link d-flex align-items-center gap-1" class:active={aktiverReiter === k} href="#/video/{id}/{k}" onclick={(e) => { e.preventDefault(); reiterWechsel(k); }}>{titel} <InfoKnopf anker={REITER_HILFE[k]} titel="Was in diesem Schritt passiert" /></a></li>
        {/each}
        {#if aktiverReiter === "korrektur" && vergleich}
          <li class="nav-item ms-auto d-flex align-items-center gap-2 pe-1">
            <div class="btn-group btn-group-sm">
              <button class="btn btn-outline-secondary" class:active={vergleichModus === "beide"} onclick={() => (vergleichModus = "beide")} title="Rohtext und korrigierten Text Block für Block nebeneinander zeigen">Nebeneinander</button>
              <button class="btn btn-outline-secondary" class:active={vergleichModus === "korrigiert"} onclick={() => (vergleichModus = "korrigiert")} title="Nur die korrigierte Fassung zeigen">Nur korrigiert</button>
              <button class="btn btn-outline-secondary" class:active={vergleichModus === "roh"} onclick={() => (vergleichModus = "roh")} title="Nur den Rohtext des Transkriptionsdienstes zeigen">Nur roh</button>
            </div>
            <div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" id="nurverw" bind:checked={nurVerworfene} title="Nur Blöcke zeigen, die der Abweichungswächter verworfen hat" /><label class="form-check-label small" for="nurverw">Nur verworfene</label></div>
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
                      <button class="btn btn-sm btn-outline-primary mt-1" onclick={() => blockUebernehmen(b.index)} title="Den vom Wächter verworfenen Vorschlag des Modells doch übernehmen">Trotzdem übernehmen</button>
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
            <div class="d-flex justify-content-end mb-2"><button class="btn btn-sm btn-outline-secondary" onclick={() => ui.gehe("stellen")} title="Alle Stücke im Textstellen-Browser durchblättern und bearbeiten"><i class="fa-solid fa-align-left"></i> Im Textstellen-Browser öffnen</button></div>
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
