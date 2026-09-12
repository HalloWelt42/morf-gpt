<script lang="ts">
  // Eigener Transkriptionsdienst: Engine, Modell, Arbeiter mit Zustand, Wartende, Speicher; Arbeiter anpassen.
  import { onMount } from "svelte";
  import { api } from "../../lib/api";
  import type { TranskriptionsdienstStand } from "../../lib/typen";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import { dezimal } from "../../lib/format";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Speicherplatz from "../../lib/komponenten/Speicherplatz.svelte";

  let stand = $state<TranskriptionsdienstStand | null>(null);
  let beschaeftigt = $state(false);

  const ZUSTAND: Record<string, string> = { laedt: "lädt das Modell", bereit: "bereit", beschaeftigt: "transkribiert", beendet: "beendet" };

  async function laden(): Promise<void> {
    try {
      stand = await api.get<TranskriptionsdienstStand>("/transkription/dienst");
    } catch (e) {
      meldeFehler(e, "Transkriptionsdienst");
    }
  }

  async function anpassen(anzahl: number | null): Promise<void> {
    beschaeftigt = true;
    try {
      stand = await api.post<TranskriptionsdienstStand>("/transkription/dienst/arbeiter", anzahl === null ? {} : { anzahl });
      const bereit = (stand.arbeiter ?? []).filter((a) => a.zustand === "bereit" || a.zustand === "beschaeftigt").length;
      meldungen.gut(`${bereit} Arbeiter beim Transkriptionsdienst`);
    } catch (e) {
      meldeFehler(e, "Arbeiter anpassen");
    } finally {
      beschaeftigt = false;
    }
  }

  onMount(() => void laden());
</script>

{#if stand}
  <div class="card mb-3">
    <div class="card-body">
      <div class="d-flex align-items-center gap-2 flex-wrap">
        <h6 class="m-0 small text-uppercase text-secondary">Transkriptionsdienst: {stand.engine_titel}</h6>
        <InfoKnopf anker="stufe-transkription" finde="Eigener Dienst" />
        <span class="ms-auto"></span>
        <button class="btn btn-sm btn-outline-secondary" onclick={laden} title="Stand des Dienstes und Speicher neu lesen"><i class="fa-solid fa-rotate"></i></button>
        <button class="btn btn-sm btn-primary" onclick={() => anpassen(null)} disabled={beschaeftigt || !stand.eigener || !stand.erreichbar} title="Den Dienst auf die eingestellte Zahl Arbeiter bringen, soweit der Speicher reicht">{#if beschaeftigt}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if} Auf {stand.arbeiter_einstellung} Arbeiter</button>
        <button class="btn btn-sm btn-outline-secondary" onclick={() => anpassen(1)} disabled={beschaeftigt || !stand.eigener || !stand.erreichbar || (stand.arbeiter ?? []).length <= 1} title="Alle Arbeiter bis auf einen beenden; beschäftigte enden nach ihrem Auftrag">Auf einen</button>
      </div>
      {#if !stand.eigener}
        <div class="text-secondary mt-2">{stand.hinweis}</div>
      {:else if !stand.erreichbar}
        <div class="alert alert-warning py-2 mt-2 mb-0"><i class="fa-solid fa-triangle-exclamation"></i> {stand.hinweis} Der Dienst startet mit <code>./start.sh transkription</code>; Adresse: <code>{stand.adresse}</code>.</div>
      {:else}
        <div class="row g-3 mt-1">
          <div class="col-md-5">
            <div class="small text-secondary mb-1">Arbeiter ({(stand.arbeiter ?? []).length} von {stand.gewuenscht} gewünscht, höchstens {stand.maximum})</div>
            {#each stand.arbeiter ?? [] as a (a.nummer)}
              <div title="Arbeiter {a.nummer}: {ZUSTAND[a.zustand] ?? a.zustand}, {a.auftraege} Aufträge bisher">
                <i class="fa-solid fa-microchip text-secondary"></i> Arbeiter {a.nummer}
                <span class="badge" class:text-bg-success={a.zustand === "bereit"} class:text-bg-primary={a.zustand === "beschaeftigt"} class:text-bg-secondary={a.zustand !== "bereit" && a.zustand !== "beschaeftigt"}>{ZUSTAND[a.zustand] ?? a.zustand}</span>
                {#if a.groesse_gb}<span class="text-secondary" title="Modell {dezimal(a.groesse_gb)} GB; belegt nach dem letzten Auftrag {dezimal(a.speicher_gb)} GB (Modell plus behaltene Puffer)">{dezimal(a.speicher_gb || a.groesse_gb)} GB</span>{/if}
                <span class="text-secondary small">{a.auftraege} Aufträge</span>
              </div>
            {:else}
              <div class="text-secondary">Kein Arbeiter geladen.</div>
            {/each}
            <div class="small text-secondary mt-1">Engine <code>{stand.engine}</code>, Modell <code>{stand.modell}</code>{#if stand.wartend} <span class="text-warning">, {stand.wartend} wartende Aufträge</span>{/if}</div>
          </div>
          <div class="col-md-7">
            <div class="small text-secondary mb-1">Speicher des Rechners, auf dem der Dienst läuft</div>
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
        <div class="small text-secondary mt-2">Gemessen mit Whisper large-v3 auf der Grafikeinheit: ein Arbeiter etwa dreifache Echtzeit; zwei Arbeiter schaffen zusammen etwa 40 Prozent mehr, vier etwa zwei Drittel mehr, jeder einzelne Auftrag wird dabei langsamer. Die Zahl der Arbeiter stellst du unten ein; die Stufe Transkribieren bringt den Dienst vor jedem Auftrag darauf. Damit mehrere Arbeiter arbeiten, müssen unter Fließband ebenso viele parallele Transkriptionen erlaubt sein.</div>
      {/if}
    </div>
  </div>
{/if}
