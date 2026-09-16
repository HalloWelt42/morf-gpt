<script lang="ts">
  // Übergabe: alles Entstandene als Ordner mit Kennung erstellen (zum Hochladen), vorhandene Übergaben
  // verwalten, eine Übergabe von einer Adresse oder aus einem Ordner holen.
  import { onDestroy, onMount } from "svelte";
  import { api } from "../../lib/api";
  import type { UebergabeInfo, UebergabeLauf } from "../../lib/typen";
  import { ereignisse } from "../../lib/stores/ereignisse.svelte";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import { bytes, datumZeit, zahl } from "../../lib/format";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Bestaetigung from "../../lib/komponenten/Bestaetigung.svelte";

  let erstellen = $state<UebergabeLauf | null>(null);
  let holen = $state<UebergabeLauf | null>(null);
  let uebergaben = $state<UebergabeInfo[]>([]);
  let mitAudio = $state(true);
  let mitModellen = $state(true);
  let adresse = $state("");
  let aufraeumen = $state(true);
  let loeschDialog = $state(false);
  let loeschZiel = $state<UebergabeInfo | null>(null);
  let beschaeftigt = $state(false);
  let takt: number | null = null;
  const abos: (() => void)[] = [];

  const ART_TITEL: Record<string, string> = { bibliothek: "Bibliothek", audio: "Audio", modelle: "Modelle" };

  async function laden(): Promise<void> {
    try {
      erstellen = await api.get<UebergabeLauf>("/uebergabe/erstellen/status");
      holen = await api.get<UebergabeLauf>("/uebergabe/holen/status");
      uebergaben = await api.get<UebergabeInfo[]>("/uebergabe");
    } catch (e) {
      meldeFehler(e, "Übergabe laden");
    }
  }

  async function erstellenStarten(): Promise<void> {
    try {
      erstellen = await api.post<UebergabeLauf>("/uebergabe/erstellen", { mit_audio: mitAudio, mit_modellen: mitModellen });
      meldungen.gut("Übergabe wird erstellt");
    } catch (e) {
      meldeFehler(e, "Übergabe erstellen");
    }
  }

  async function holenStarten(): Promise<void> {
    if (!adresse.trim()) return;
    try {
      holen = await api.post<UebergabeLauf>("/uebergabe/holen", { adresse: adresse.trim(), aufraeumen });
      meldungen.gut("Übergabe wird geholt");
    } catch (e) {
      meldeFehler(e, "Übergabe holen");
    }
  }

  async function loeschen(): Promise<void> {
    if (!loeschZiel) return;
    beschaeftigt = true;
    try {
      await api.del(`/uebergabe/${loeschZiel.kennung}`);
      loeschDialog = false;
      await laden();
    } catch (e) {
      meldeFehler(e, "Löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  function eigeneAdresse(u: UebergabeInfo): string {
    return `${location.origin}/api/uebergabe/${u.kennung}/`;
  }

  async function kopieren(text: string): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      meldungen.gut("In die Zwischenablage kopiert");
    } catch {
      meldungen.fehler("Kopieren nicht möglich; bitte von Hand markieren");
    }
  }

  onMount(() => {
    void laden();
    abos.push(
      ereignisse.abonniere("uebergabe", (e) => {
        const lauf = e.daten.richtung === "holen" ? holen : erstellen;
        if (lauf) {
          lauf.fortschritt = Number(e.daten.fortschritt ?? lauf.fortschritt);
          lauf.meldung = String(e.daten.meldung ?? lauf.meldung);
        }
        if (e.daten.status === "fertig" || e.daten.status === "fehler" || e.daten.status === "geloescht") void laden();
      }),
    );
    takt = window.setInterval(() => {
      if (erstellen?.laeuft || holen?.laeuft) void laden();
    }, 5000);
  });
  onDestroy(() => {
    abos.forEach((ab) => ab());
    if (takt) window.clearInterval(takt);
  });
</script>

<div class="card mb-3">
  <div class="card-header fw-semibold">Übergabe erstellen <InfoKnopf anker="umzug" finde="Übergabe" /></div>
  <div class="card-body">
    <p>
      Für einen Empfänger, der die Bibliothek ohne diese Werkstatt weiterbetreibt: ein Ordner mit zufälliger Kennung, darin das Bibliothekspaket mit Transkripten und Dokumenten,
      wahlweise alle Audiodateien in Teilen zu 2 GB und die lokalen Modelle, dazu Prüfsummen und eine Anleitung. Zugangsschlüssel, Anbieter und Einstellungen bleiben draußen.
      Den Ordner lädst du auf einen Webspace; wer die Adresse mit der Kennung kennt, kann ihn holen.
    </p>
    <div class="d-flex gap-4 flex-wrap mb-3">
      <div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" id="ue-audio" bind:checked={mitAudio} title="Alle Audiodateien der Videos im Umfang mitgeben (viele Gigabyte); nötig nur für den eingebauten Abspieler und erneutes Transkribieren" /><label class="form-check-label" for="ue-audio">Audio mitgeben</label></div>
      <div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" id="ue-modelle" bind:checked={mitModellen} title="Die lokalen Modelle (Spracherkennung, Einbettung) mitgeben, damit der Empfänger nichts aus dem Netz laden muss" /><label class="form-check-label" for="ue-modelle">Modelle mitgeben</label></div>
    </div>
    {#if erstellen?.laeuft}
      <div class="m-fortschritt laeuft mb-1"><span style="width: {Math.round(erstellen.fortschritt * 100)}%"></span></div>
      <div class="text-secondary">{erstellen.meldung}</div>
    {:else}
      <button class="btn btn-primary" onclick={erstellenStarten} title="Übergabeordner mit Kennung schreiben; dauert bei vielen Gigabyte Audio einige Minuten"><i class="fa-solid fa-box-open"></i> Übergabe erstellen</button>
      {#if erstellen?.fehler}<div class="text-danger mt-2">{erstellen.fehler}</div>{/if}
      {#if erstellen?.ergebnis && !erstellen.fehler}<div class="text-secondary mt-2">{erstellen.meldung}</div>{/if}
    {/if}
  </div>
</div>

<div class="card mb-3">
  <div class="card-header fw-semibold">Vorhandene Übergaben</div>
  <div class="card-body">
    {#each uebergaben as u (u.kennung)}
      <div class="border-bottom pb-3 mb-3">
        <div class="d-flex align-items-center gap-2 flex-wrap">
          <code title="Kennung der Übergabe; sie ist der Zugang">{u.kennung}</code>
          <span class="text-secondary">{datumZeit(u.erstellt)} &middot; morf-gpt {u.version} &middot; {bytes(u.gesamt_bytes)}</span>
          <span class="ms-auto"></span>
          <button class="btn btn-sm btn-outline-secondary" onclick={() => kopieren(eigeneAdresse(u))} title="Adresse kopieren, unter der diese Übergabe direkt von diesem Rechner geholt werden kann (Backend erreichbar vorausgesetzt)"><i class="fa-solid fa-link"></i> Adresse hier</button>
          <a class="btn btn-sm btn-outline-secondary" href="/api/uebergabe/{u.kennung}/ANLEITUNG.md" target="_blank" rel="noopener" title="Die Anleitung für den Empfänger lesen"><i class="fa-solid fa-book-open"></i> Anleitung</a>
          <button class="btn btn-sm btn-outline-danger" onclick={() => { loeschZiel = u; loeschDialog = true; }} title="Den Übergabeordner mit allen Teilen löschen"><i class="fa-solid fa-trash"></i></button>
        </div>
        <div class="small text-secondary mt-1" title="Ordner auf diesem Rechner; von hier wird auf den Webspace hochgeladen">Ordner: <code>{u.ordner}</code></div>
        <div class="small mt-1">
          {zahl(u.zaehler.videos)} Videos, {zahl(u.zaehler.chunks + (u.zaehler.dokument_chunks ?? 0))} Stücke, {zahl(u.zaehler.einbettungen)} Einbettungen, {zahl(u.zaehler.dokumente)} Dokumente
          {#if u.audio_dateien}&middot; {zahl(u.audio_dateien)} Audiodateien ({bytes(u.audio_bytes)}){/if}
          {#if u.modelle.length}&middot; Modelle: {u.modelle.join(", ")}{/if}
        </div>
        <div class="table-responsive mt-2">
          <table class="table table-sm mb-0">
            <thead><tr><th>Teil</th><th>Art</th><th class="text-end">Größe</th><th>Prüfsumme (SHA-256)</th></tr></thead>
            <tbody>
              {#each u.teile as t (t.name)}
                <tr><td><a href="/api/uebergabe/{u.kennung}/{encodeURIComponent(t.name)}" title="Diesen Teil herunterladen">{t.name}</a></td><td>{ART_TITEL[t.art] ?? t.art}</td><td class="text-end">{bytes(t.bytes)}</td><td><code class="small" title={t.sha256}>{t.sha256.slice(0, 16)}...</code></td></tr>
              {/each}
            </tbody>
          </table>
        </div>
      </div>
    {:else}
      <div class="text-secondary">Noch keine Übergabe erstellt.</div>
    {/each}
  </div>
</div>

<div class="card mb-3">
  <div class="card-header fw-semibold">Übergabe holen <InfoKnopf anker="umzug" finde="Übergabe holen" /></div>
  <div class="card-body">
    <p>
      Als Empfänger: die Adresse des Übergabeordners eintragen (Webadresse mit Kennung, endet auf die Kennung, oder ein Ordner auf diesem Rechner). morf-gpt lädt die Teile, prüft
      die Prüfsummen, liest die Bibliothek ein und legt Audio und Modelle ab. Ein abgebrochener Download setzt beim nächsten Versuch fort.
    </p>
    <div class="d-flex gap-2 align-items-center flex-wrap">
      <input class="form-control" style="max-width: 560px" bind:value={adresse} placeholder="https://beispiel.de/morf/2f1c…-…/ oder /Pfad/zum/Ordner" title="Webadresse des Übergabeordners (mit Kennung) oder Pfad eines Ordners auf diesem Rechner" onkeydown={(e) => { if (e.key === "Enter") void holenStarten(); }} />
      <button class="btn btn-primary" onclick={holenStarten} disabled={!adresse.trim() || holen?.laeuft} title="Übergabe laden, prüfen und übernehmen"><i class="fa-solid fa-cloud-arrow-down"></i> Holen</button>
      <div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" id="ue-aufraeumen" bind:checked={aufraeumen} title="Heruntergeladene Teile nach dem Übernehmen wieder löschen (spart Platz); aus, wenn du sie behalten willst" /><label class="form-check-label" for="ue-aufraeumen">Download danach löschen</label></div>
    </div>
    {#if holen?.laeuft}
      <div class="m-fortschritt laeuft mt-3 mb-1"><span style="width: {Math.round(holen.fortschritt * 100)}%"></span></div>
      <div class="text-secondary">{holen.meldung}</div>
    {:else if holen?.fehler}
      <div class="text-danger mt-3">{holen.fehler}</div>
    {:else if holen?.ergebnis}
      <div class="mt-3">
        <div class="fw-semibold">{holen.meldung}</div>
        <dl class="row mt-2 mb-0">
          <dt class="col-5 fw-normal text-secondary">Kennung</dt><dd class="col-7 mb-1"><code>{String(holen.ergebnis.kennung)}</code> (morf-gpt {String(holen.ergebnis.version)})</dd>
          <dt class="col-5 fw-normal text-secondary">Geladen</dt><dd class="col-7 mb-1">{bytes(Number(holen.ergebnis.geladen_bytes))}</dd>
          <dt class="col-5 fw-normal text-secondary">Bibliothek</dt><dd class="col-7 mb-1">{Object.entries((holen.ergebnis.bibliothek as Record<string, unknown>) ?? {}).filter(([, v]) => typeof v === "number" && v).map(([k, v]) => `${k} ${v}`).join(", ")}</dd>
          <dt class="col-5 fw-normal text-secondary">Audio</dt><dd class="col-7 mb-1">{zahl(Number(holen.ergebnis.audio_dateien))} Dateien, davon {zahl(Number(holen.ergebnis.audio_neu))} neu eingetragen</dd>
          <dt class="col-5 fw-normal text-secondary">Modelle</dt><dd class="col-7 mb-1">{zahl(Number(holen.ergebnis.modelle_dateien))} Dateien{#if (holen.ergebnis.modelle as string[])?.length} ({(holen.ergebnis.modelle as string[]).join(", ")}){/if}</dd>
        </dl>
      </div>
    {/if}
  </div>
</div>

<Bestaetigung bind:offen={loeschDialog} titel="Übergabe löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Der Ordner <code>{loeschZiel?.kennung}</code> mit allen Teilen wird von diesem Rechner gelöscht. Ein bereits hochgeladener Ordner bleibt davon unberührt.</p>
</Bestaetigung>
