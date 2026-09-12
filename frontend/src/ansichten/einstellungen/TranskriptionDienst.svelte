<script lang="ts">
  // Eigener Transkriptionsdienst: Arbeiter mit Prozess, laufender Datei und letztem Auftrag (live),
  // Zahl der Arbeiter per Knopf wählen (setzt die Einstellung und den Dienst), Speicher des Rechners und der Platte.
  import { onMount } from "svelte";
  import { api } from "../../lib/api";
  import type { TranskriptionsdienstStand } from "../../lib/typen";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import { dezimal, uhrzeit, zeitmarke } from "../../lib/format";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Speicherplatz from "../../lib/komponenten/Speicherplatz.svelte";

  const TAKT_MS = 3000;

  let stand = $state<TranskriptionsdienstStand | null>(null);
  let beschaeftigt = $state(false);

  const ZUSTAND: Record<string, string> = { laedt: "lädt das Modell", bereit: "bereit", beschaeftigt: "transkribiert", beendet: "beendet" };

  function stufen(maximum: number): number[] {
    return Array.from({ length: Math.max(1, maximum) }, (_, i) => i + 1);
  }

  function bereite(s: TranskriptionsdienstStand): number {
    return (s.arbeiter ?? []).filter((a) => a.zustand === "bereit" || a.zustand === "beschaeftigt").length;
  }

  async function laden(): Promise<void> {
    try {
      stand = await api.get<TranskriptionsdienstStand>("/transkription/dienst");
    } catch (e) {
      meldeFehler(e, "Transkriptionsdienst");
    }
  }

  async function waehle(anzahl: number): Promise<void> {
    beschaeftigt = true;
    try {
      stand = await api.post<TranskriptionsdienstStand>("/transkription/dienst/arbeiter", { anzahl });
      meldungen.gut(`${bereite(stand)} von ${anzahl} Arbeitern bereit`);
    } catch (e) {
      meldeFehler(e, "Arbeiter wählen");
    } finally {
      beschaeftigt = false;
    }
  }

  onMount(() => {
    void laden();
    const takt = setInterval(() => void laden(), TAKT_MS);
    return () => clearInterval(takt);
  });
</script>

{#if stand}
  <div class="card mb-3">
    <div class="card-body">
      <div class="d-flex align-items-center gap-2 flex-wrap">
        <h6 class="m-0 small text-uppercase text-secondary">Transkriptionsdienst: {stand.engine_titel}</h6>
        <InfoKnopf anker="stufe-transkription" finde="Eigener Dienst" />
        <span class="ms-auto"></span>
        {#if stand.eigener && stand.erreichbar}
          <span class="small text-secondary">Arbeiter</span>
          <div class="btn-group m-stufenwahl" role="group" aria-label="Zahl der Arbeiter">
            {#each stufen(stand.maximum ?? 8) as n (n)}
              <button type="button" class="btn btn-sm btn-outline-secondary" class:active={stand.arbeiter_einstellung === n} disabled={beschaeftigt} onclick={() => waehle(n)} title="{n} Arbeiter halten: startet oder beendet Prozesse sofort (soweit der Speicher reicht) und speichert die Zahl als Einstellung">{n}</button>
            {/each}
          </div>
        {/if}
        <button class="btn btn-sm btn-outline-secondary" onclick={laden} title="Stand des Dienstes und Speicher jetzt neu lesen (sonst alle drei Sekunden)"><i class="fa-solid fa-rotate"></i></button>
      </div>
      {#if !stand.eigener}
        <div class="text-secondary mt-2">{stand.hinweis}</div>
      {:else if !stand.erreichbar}
        <div class="alert alert-warning py-2 mt-2 mb-0"><i class="fa-solid fa-triangle-exclamation"></i> {stand.hinweis} Der Dienst startet mit <code>./start.sh transkription</code>; Adresse: <code>{stand.adresse}</code>.</div>
      {:else}
        <div class="small text-secondary mt-2">
          Dienst-Prozess {stand.dienst?.pid}{#if stand.dienst?.gestartet}, läuft seit {uhrzeit(stand.dienst.gestartet)}{/if}; Engine <code>{stand.engine}</code>, Modell <code>{stand.modell}</code>;
          {(stand.arbeiter ?? []).length} von {stand.gewuenscht} Arbeitern, jeder ein eigener Prozess{#if stand.wartend}; <span class="text-warning">{stand.wartend} Aufträge warten auf einen freien Arbeiter</span>{/if}
        </div>
        <div class="table-responsive mt-2">
          <table class="table table-sm align-middle mb-0 m-arbeiter">
            <thead>
              <tr><th>Arbeiter</th><th>Prozess</th><th>Zustand</th><th>Gerade</th><th>Zuletzt</th><th class="text-end">Aufträge</th><th class="text-end" title="Belegter Grafikspeicher nach dem letzten Auftrag (Modell plus behaltene Puffer)">Speicher</th></tr>
            </thead>
            <tbody>
              {#each stand.arbeiter ?? [] as a (a.nummer)}
                <tr>
                  <td><i class="fa-solid fa-microchip text-secondary"></i> Arbeiter {a.nummer}</td>
                  <td title="Kennung des Arbeiterprozesses im Betriebssystem, gestartet {uhrzeit(a.gestartet)}"><code>{a.pid}</code></td>
                  <td><span class="badge" class:text-bg-success={a.zustand === "bereit"} class:text-bg-primary={a.zustand === "beschaeftigt"} class:text-bg-secondary={a.zustand !== "bereit" && a.zustand !== "beschaeftigt"}>{ZUSTAND[a.zustand] ?? a.zustand}</span></td>
                  <td>
                    {#if a.aktuell}
                      <span class="text-truncate d-inline-block" style="max-width: 260px" title={a.aktuell.datei}>{a.aktuell.datei}</span>
                      <span class="text-secondary small">seit {zeitmarke(a.aktuell.laeuft_s)}</span>
                    {:else}
                      <span class="text-secondary">-</span>
                    {/if}
                  </td>
                  <td>
                    {#if a.zuletzt}
                      <span class="text-truncate d-inline-block" style="max-width: 220px" title={a.zuletzt.datei}>{a.zuletzt.datei}</span>
                      {#if a.zuletzt.fehler}
                        <span class="text-danger small" title={a.zuletzt.fehler}>Fehler</span>
                      {:else}
                        <span class="text-secondary small">{a.zuletzt.audio_s !== null ? `${zeitmarke(a.zuletzt.audio_s)} Audio in ` : ""}{zeitmarke(a.zuletzt.dauer_s)}</span>
                      {/if}
                    {:else}
                      <span class="text-secondary">-</span>
                    {/if}
                  </td>
                  <td class="text-end">{a.auftraege}</td>
                  <td class="text-end">{dezimal(a.speicher_gb || a.groesse_gb)} GB</td>
                </tr>
              {:else}
                <tr><td colspan="7" class="text-secondary">Kein Arbeiter geladen.</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="row g-3 mt-1">
          <div class="col-12">
            <div class="small text-secondary mb-1">Arbeitsspeicher des Rechners, auf dem der Dienst läuft</div>
            {#if stand.speicher?.bekannt}
              <div class="m-kennzahlen">
                <div class="m-kennzahl"><div class="wert">{dezimal(stand.speicher.verfuegbar_gb)} GB</div><div class="titel">verfügbar (frei und inaktiv)</div></div>
                <div class="m-kennzahl"><div class="wert">{dezimal(stand.modell_groesse_gb ?? 0)} GB</div><div class="titel">je Arbeiter (Modell)</div></div>
                <div class="m-kennzahl"><div class="wert">{dezimal(stand.speicher.gesamt_gb)} GB</div><div class="titel">gesamt</div></div>
              </div>
            {:else}
              <div class="text-secondary">Der Speicherstand dieses Systems ist unbekannt; Arbeiter werden ohne Prüfung geladen.</div>
            {/if}
          </div>
          <div class="col-12"><Speicherplatz /></div>
        </div>
        {#each stand.hinweise ?? [] as h}
          <div class="alert alert-warning py-2 mt-2 mb-0"><i class="fa-solid fa-triangle-exclamation"></i> {h}</div>
        {/each}
        <div class="small text-secondary mt-2">Jeder Arbeiter ist ein eigener Prozess mit eigenem Modell; die Tabelle zeigt live, welche Datei er gerade transkribiert. Gemessen mit Whisper large-v3 auf der Grafikeinheit: ein Arbeiter etwa dreifache Echtzeit; zwei schaffen zusammen etwa 40 Prozent mehr, vier etwa zwei Drittel mehr, jeder einzelne Auftrag wird dabei langsamer. Damit mehrere Arbeiter arbeiten, müssen unter Fließband ebenso viele parallele Transkriptionen erlaubt sein.</div>
      {/if}
    </div>
  </div>
{/if}
