<script lang="ts">
  // Umzug der Bibliothek: Paket exportieren (mit Fortschritt), Pakete verwalten, importieren.
  import { onDestroy, onMount } from "svelte";
  import { api } from "../../lib/api";
  import type { ExportStatus, PaketInfo } from "../../lib/typen";
  import { ereignisse } from "../../lib/stores/ereignisse.svelte";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import { bytes, datumZeit } from "../../lib/format";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Bestaetigung from "../../lib/komponenten/Bestaetigung.svelte";

  let status = $state<ExportStatus | null>(null);
  let pakete = $state<PaketInfo[]>([]);
  let mitTranskripten = $state(false);
  let datei = $state<File | null>(null);
  let importErgebnis = $state<Record<string, unknown> | null>(null);
  let beschaeftigt = $state(false);
  let loeschDialog = $state(false);
  let loeschZiel = $state<PaketInfo | null>(null);
  let takt: number | null = null;
  const abos: (() => void)[] = [];

  async function laden(): Promise<void> {
    try {
      status = await api.get<ExportStatus>("/export/status");
      pakete = await api.get<PaketInfo[]>("/export/pakete");
    } catch (e) {
      meldeFehler(e, "Export laden");
    }
  }

  async function starten(): Promise<void> {
    try {
      status = await api.post<ExportStatus>("/export/bibliothek", { mit_transkripten: mitTranskripten });
      meldungen.gut("Export gestartet");
    } catch (e) {
      meldeFehler(e, "Export");
    }
  }

  async function loeschen(): Promise<void> {
    if (!loeschZiel) return;
    beschaeftigt = true;
    try {
      await api.del(`/export/pakete/${encodeURIComponent(loeschZiel.name)}`);
      loeschDialog = false;
      await laden();
    } catch (e) {
      meldeFehler(e, "Löschen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function importieren(): Promise<void> {
    if (!datei) return;
    beschaeftigt = true;
    importErgebnis = null;
    try {
      const f = new FormData();
      f.append("datei", datei);
      importErgebnis = await api.hochladen<Record<string, unknown>>("/export/import", f);
      meldungen.gut("Import abgeschlossen");
    } catch (e) {
      meldeFehler(e, "Import");
    } finally {
      beschaeftigt = false;
    }
  }

  onMount(() => {
    void laden();
    abos.push(ereignisse.abonniere("export", (e) => {
      if (status) {
        status.fortschritt = Number(e.daten.fortschritt ?? status.fortschritt);
        status.meldung = String(e.daten.meldung ?? status.meldung);
        if (e.daten.laeuft === false) void laden();
      }
    }));
    takt = window.setInterval(() => { if (status?.laeuft) void laden(); }, 5000);
  });
  onDestroy(() => {
    abos.forEach((ab) => ab());
    if (takt) window.clearInterval(takt);
  });
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf"><h1>Umzug der Bibliothek</h1><span class="m-unter">Paket erstellen, anderswo importieren</span><InfoKnopf anker="umzug" /></div>
  <div class="m-ansicht-koerper">
    <div class="row g-3">
      <div class="col-lg-8">
        <div class="card mb-3">
          <div class="card-header fw-semibold">Exportieren</div>
          <div class="card-body">
            <p>Das Paket enthält Videodaten, Korrekturen, Stücke, Vektoren und Vorschaubilder. Audio bleibt hier; der Sprung zu YouTube bleibt überall möglich.</p>
            <div class="form-check form-switch mb-3"><input class="form-check-input" type="checkbox" id="mt" bind:checked={mitTranskripten} title="Auch die Rohtranskripte mit Zeitmarken ins Paket nehmen; macht es deutlich größer" /><label class="form-check-label" for="mt">Rohtranskripte mitnehmen (größer)</label></div>
            {#if status?.laeuft}
              <div class="m-fortschritt laeuft mb-1"><span style="width: {Math.round(status.fortschritt * 100)}%"></span></div>
              <div class="text-secondary">{status.meldung}</div>
            {:else}
              <button class="btn btn-primary" onclick={starten} title="Videos, Korrekturen, Stücke, Vektoren und Vorschaubilder als ein Paket schreiben; Audio bleibt draußen"><i class="fa-solid fa-box"></i> Paket erstellen</button>
              {#if status?.fehler}<div class="text-danger mt-2">{status.fehler}</div>{/if}
              {#if status?.letzte_datei}<div class="text-secondary mt-2">Zuletzt erstellt: {status.letzte_datei}</div>{/if}
            {/if}
          </div>
        </div>
        <div class="card mb-3">
          <div class="card-header fw-semibold">Vorhandene Pakete</div>
          <div class="m-tabelle-feld" style="border: 0">
            <table class="table table-sm mb-0 align-middle">
              <thead><tr><th>Name</th><th>Größe</th><th>Erstellt</th><th></th></tr></thead>
              <tbody>
                {#each pakete as p (p.name)}
                  <tr><td>{p.name}</td><td>{bytes(p.groesse_bytes)}</td><td>{datumZeit(p.erstellt)}</td><td class="text-end"><a class="btn btn-sm btn-outline-secondary" href="/api/export/pakete/{encodeURIComponent(p.name)}" download><i class="fa-solid fa-download"></i></a> <button class="btn btn-sm btn-outline-danger" onclick={() => { loeschZiel = p; loeschDialog = true; }}><i class="fa-solid fa-trash"></i></button></td></tr>
                {/each}
                {#if !pakete.length}<tr><td colspan="4" class="text-secondary text-center py-3">Noch kein Paket.</td></tr>{/if}
              </tbody>
            </table>
          </div>
        </div>
        <div class="card">
          <div class="card-header fw-semibold">Importieren</div>
          <div class="card-body">
            <p>Ein Paket aus einer anderen Installation einlesen. Videos werden über ihre Kennung abgeglichen; das Einbettungsmodell und die Dimension müssen zur Datenbank passen.</p>
            <div class="d-flex gap-2 align-items-center flex-wrap">
              <input class="form-control" type="file" accept=".tar.gz,.tgz" style="max-width: 460px" title="Ein Paket aus einer anderen Installation wählen" onchange={(e) => (datei = (e.target as HTMLInputElement).files?.[0] ?? null)} />
              <button class="btn btn-primary" onclick={importieren} disabled={!datei || beschaeftigt} title="Das Paket in diese Bibliothek einlesen; bekannte Videos werden über ihre Kennung abgeglichen">{#if beschaeftigt}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if} Importieren</button>
            </div>
            {#if importErgebnis}
              <dl class="row mt-3 mb-0">{#each Object.entries(importErgebnis) as [k, v]}<dt class="col-5 fw-normal text-secondary">{k}</dt><dd class="col-7 mb-1">{typeof v === "object" ? JSON.stringify(v) : String(v)}</dd>{/each}</dl>
            {/if}
          </div>
        </div>
      </div>
    </div>
  </div>
</section>

<Bestaetigung bind:offen={loeschDialog} titel="Paket löschen" bestaetigen="Löschen" gefaehrlich {beschaeftigt} onBestaetigen={loeschen}>
  <p>Das Paket <b>{loeschZiel?.name}</b> wird gelöscht.</p>
</Bestaetigung>
