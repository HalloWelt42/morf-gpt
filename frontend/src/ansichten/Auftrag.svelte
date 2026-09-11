<script lang="ts">
  // Ein Auftrag: Kennzahlen, Parameter, Ergebnis, seitenweises Protokoll (live).
  import { onDestroy, onMount } from "svelte";
  import { api, mitParametern } from "../lib/api";
  import type { AuftragDetail, ProtokollSeite, ProtokollZeile } from "../lib/typen";
  import { ereignisse } from "../lib/stores/ereignisse.svelte";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { dauerWorte, datumZeit, uhrzeit, vorZeit, zahl } from "../lib/format";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";

  let { id }: { id: string } = $props();

  const FARBE: Record<string, string> = { laeuft: "primary", wartend: "secondary", fertig: "success", fehler: "danger", abgebrochen: "dark", pausiert: "warning" };

  let a = $state<AuftragDetail | null>(null);
  let zeilen = $state<ProtokollZeile[]>([]);
  let gesamt = $state(0);
  const anzahl = 50;
  const abos: (() => void)[] = [];

  async function laden(): Promise<void> {
    try {
      a = await api.get<AuftragDetail>(`/auftraege/${id}`);
      const p = await api.get<ProtokollSeite>(mitParametern(`/auftraege/${id}/protokoll`, { ab: 0, anzahl }));
      zeilen = [...p.eintraege].reverse();
      gesamt = p.gesamt;
    } catch (e) {
      meldeFehler(e, "Auftrag laden");
    }
  }

  async function aeltere(): Promise<void> {
    try {
      const p = await api.get<ProtokollSeite>(mitParametern(`/auftraege/${id}/protokoll`, { ab: zeilen.length, anzahl }));
      zeilen = [...[...p.eintraege].reverse(), ...zeilen];
      gesamt = p.gesamt;
    } catch (e) {
      meldeFehler(e, "Protokoll laden");
    }
  }

  async function abbrechen(): Promise<void> {
    try {
      const r = await api.post<{ hinweis: string }>(`/auftraege/${id}/abbrechen`);
      meldungen.zeige(r.hinweis);
      await laden();
    } catch (e) {
      meldeFehler(e, "Abbrechen");
    }
  }

  async function wiederholen(): Promise<void> {
    try {
      await api.post(`/auftraege/${id}/wiederholen`);
      meldungen.gut("Auftrag erneut eingereiht");
      await laden();
    } catch (e) {
      meldeFehler(e, "Wiederholen");
    }
  }

  onMount(() => {
    void laden();
    abos.push(
      ereignisse.abonniere("auftrag_protokoll", (e) => {
        if (e.daten.auftrag_id !== id) return;
        zeilen = [...zeilen, { id: Date.now(), zeit: String(e.daten.zeit), stufe: String(e.daten.stufe ?? "info"), text: String(e.daten.text ?? "") }];
        gesamt += 1;
      }),
      ereignisse.abonniere("auftrag_fortschritt", (e) => {
        if (e.daten.auftrag_id !== id || !a) return;
        a.fortschritt = Number(e.daten.fortschritt ?? a.fortschritt);
        a.meldung = String(e.daten.meldung ?? a.meldung);
        a.herzschlag = new Date().toISOString();
      }),
      ereignisse.abonniere("auftrag_status", (e) => {
        if (e.daten.auftrag_id === id) void laden();
      }),
    );
  });

  onDestroy(() => abos.forEach((ab) => ab()));
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <button class="btn btn-sm btn-outline-secondary" title="Zurück zum Fließband" onclick={() => ui.gehe("fliessband")}><i class="fa-solid fa-arrow-left"></i></button>
    {#if a}
      <h1>{a.art_titel}{#if a.video_titel} - {a.video_titel}{/if}</h1>
      <span class="badge text-bg-{FARBE[a.status] ?? 'secondary'} fs-6">{a.status === "laeuft" ? "läuft" : a.status}</span>
      {#if a.video_serie}<Abzeichen serie={a.video_serie} folgeNr={a.video_folge_nr} />{/if}
      <span class="m-luecke"></span>
      {#if a.status === "laeuft" || a.status === "wartend"}
        <button class="btn btn-sm btn-outline-danger" onclick={abbrechen} title="Den laufenden oder wartenden Auftrag abbrechen; das Video bleibt auf seiner bisherigen Stufe"><i class="fa-solid fa-stop"></i> Abbrechen</button>
      {:else if a.status === "fehler" || a.status === "abgebrochen"}
        <button class="btn btn-sm btn-outline-secondary" onclick={wiederholen} title="Den Auftrag wieder in die Reihe stellen, zum Beispiel nach einem behobenen Fehler"><i class="fa-solid fa-rotate-right"></i> Erneut versuchen</button>
      {/if}
      {#if a.video_id}
        <button class="btn btn-sm btn-outline-secondary" onclick={() => ui.gehe("video", a?.video_id ?? "")}><i class="fa-solid fa-film"></i> Video öffnen</button>
      {/if}
    {:else}
      <h1>Auftrag</h1>
    {/if}
  </div>
  <div class="m-ansicht-koerper">
    {#if a}
      {#if a.fehler}<div class="alert alert-danger"><i class="fa-solid fa-triangle-exclamation"></i> {a.fehler}</div>{/if}
      <div class="m-kennzahlen mb-3">
        <div class="m-kennzahl"><div class="wert">{a.gestartet ? uhrzeit(a.gestartet) : "-"}</div><div class="titel">Gestartet{#if a.gestartet} ({datumZeit(a.gestartet)}){/if}</div></div>
        <div class="m-kennzahl"><div class="wert">{a.laufzeit_s !== null ? dauerWorte(a.laufzeit_s) : "-"}</div><div class="titel">{a.status === "laeuft" ? "Dauer bisher" : "Dauer"}</div></div>
        <div class="m-kennzahl"><div class="wert">{a.versuche}</div><div class="titel">Versuch</div></div>
        <div class="m-kennzahl"><div class="wert">{Math.round(a.fortschritt * 100)} Prozent</div><div class="titel">Fortschritt</div></div>
        <div class="m-kennzahl"><div class="wert">{a.herzschlag ? vorZeit(a.herzschlag) : "-"}</div><div class="titel">Letztes Lebenszeichen</div></div>
      </div>
      {#if a.status === "laeuft"}
        <div class="m-fortschritt laeuft mb-1"><span style="width: {Math.round(a.fortschritt * 100)}%"></span></div>
        <div class="text-secondary mb-3">{a.meldung}</div>
      {/if}
      <div class="row g-3 mb-3">
        <div class="col-lg-6">
          <div class="card h-100"><div class="card-header fw-semibold">Parameter</div><div class="card-body">
            {#if Object.keys(a.parameter).length}
              <dl class="row mb-0">{#each Object.entries(a.parameter) as [k, v]}<dt class="col-5 fw-normal text-secondary">{k}</dt><dd class="col-7 mb-1">{String(v)}</dd>{/each}</dl>
            {:else}<span class="text-secondary">Keine besonderen Parameter; es gelten die Einstellungen.</span>{/if}
          </div></div>
        </div>
        <div class="col-lg-6">
          <div class="card h-100"><div class="card-header fw-semibold">Ergebnis</div><div class="card-body">
            {#if Object.keys(a.ergebnis).length}
              <dl class="row mb-0">{#each Object.entries(a.ergebnis) as [k, v]}<dt class="col-5 fw-normal text-secondary">{k}</dt><dd class="col-7 mb-1">{typeof v === "number" ? zahl(v) : String(v)}</dd>{/each}</dl>
            {:else}<span class="text-secondary">Liegt nach Abschluss hier.</span>{/if}
          </div></div>
        </div>
      </div>
      <div class="d-flex align-items-center mb-1">
        <h6 class="m-0"><i class="fa-solid fa-terminal"></i> Protokoll ({zahl(gesamt)} Zeilen)</h6>
        {#if zeilen.length < gesamt}<button class="btn btn-sm btn-outline-secondary ms-auto" onclick={aeltere} title="Weitere, ältere Protokollzeilen nachladen">Ältere laden (noch {zahl(gesamt - zeilen.length)})</button>{/if}
      </div>
      <div class="m-protokoll" style="max-height: 480px">
        {#each zeilen as z (z.id)}
          <div class={z.stufe === "warn" ? "warn" : z.stufe === "fehler" ? "fehler" : ""}><span class="zeit">{uhrzeit(z.zeit)}</span>{z.text}</div>
        {/each}
      </div>
    {:else}
      <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Auftrag wird geladen.</div>
    {/if}
  </div>
</section>
