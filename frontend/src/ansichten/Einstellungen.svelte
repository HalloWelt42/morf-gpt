<script lang="ts">
  // Einstellungen: Gruppen links, Werte rechts mit Beschreibung, Grenzen, Einheit,
  // Vorgabe. Speichern entprellt im Hintergrund. Unterseiten Anbieter, Quellen, Umzug.
  import { onMount } from "svelte";
  import { api } from "../lib/api";
  import type { Einstellung } from "../lib/typen";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldeFehler } from "../lib/stores/meldungen.svelte";
  import { uhrzeit } from "../lib/format";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Anbieter from "./einstellungen/Anbieter.svelte";
  import Quellen from "./einstellungen/Quellen.svelte";
  import Umzug from "./einstellungen/Umzug.svelte";

  let { gruppe = "" }: { gruppe?: string } = $props();

  const SONDER: { kennung: string; titel: string; icon: string }[] = [
    { kennung: "anbieter-verwaltung", titel: "Anbieter", icon: "fa-microchip" },
    { kennung: "quellen", titel: "Quellen", icon: "fa-satellite-dish" },
    { kennung: "umzug", titel: "Umzug", icon: "fa-truck-ramp-box" },
  ];

  let alle = $state<Einstellung[]>([]);
  let suche = $state("");
  let gespeichert = $state("");
  let laden = $state(true);

  const gruppen = $derived(
    [...new Map(alle.filter((e) => e.gruppe !== "anbieter").map((e) => [e.gruppe, e.gruppe_titel])).entries()].map(([kennung, titel]) => ({ kennung, titel })),
  );
  const aktiv = $derived(gruppe || (gruppen[0]?.kennung ?? "quelle"));
  const sonder = $derived(SONDER.find((s) => s.kennung === aktiv) ?? null);
  const woerter = $derived(suche.toLowerCase().split(/\s+/).filter(Boolean));
  const sichtbar = $derived(
    woerter.length
      ? alle.filter((e) => e.gruppe !== "anbieter" && woerter.every((w) => `${e.titel} ${e.beschreibung} ${e.schluessel}`.toLowerCase().includes(w)))
      : alle.filter((e) => e.gruppe === aktiv),
  );
  const gruppeTitel = $derived(woerter.length ? `Suche: ${suche}` : (gruppen.find((g) => g.kennung === aktiv)?.titel ?? sonder?.titel ?? ""));

  async function laden_(): Promise<void> {
    laden = true;
    try {
      alle = await api.get<Einstellung[]>("/einstellungen");
    } catch (e) {
      meldeFehler(e, "Einstellungen laden");
    } finally {
      laden = false;
    }
  }

  const wartend = new Map<string, number>();

  function setze(e: Einstellung, wert: unknown): void {
    e.wert = wert;
    e.geaendert = wert !== e.vorgabe;
    const alt = wartend.get(e.schluessel);
    if (alt) window.clearTimeout(alt);
    wartend.set(
      e.schluessel,
      window.setTimeout(async () => {
        try {
          const neu = await api.put<Einstellung>(`/einstellungen/${e.schluessel}`, { wert });
          e.wert = neu.wert;
          e.geaendert = neu.geaendert;
          gespeichert = new Date().toISOString();
        } catch (err) {
          meldeFehler(err, e.titel);
          void laden_();
        }
      }, 500),
    );
  }

  async function zuruecksetzen(e: Einstellung): Promise<void> {
    try {
      const neu = await api.del<Einstellung>(`/einstellungen/${e.schluessel}`);
      e.wert = neu.wert;
      e.geaendert = false;
      gespeichert = new Date().toISOString();
    } catch (err) {
      meldeFehler(err, e.titel);
    }
  }

  function zahlEingabe(e: Einstellung, ev: Event): void {
    const roh = (ev.target as HTMLInputElement).value;
    if (roh === "") return;
    setze(e, e.typ === "ganzzahl" ? Math.round(Number(roh)) : Number(roh));
  }

  onMount(() => void laden_());
</script>

<aside class="m-seite links">
  <div class="m-seite-kopf"><i class="fa-solid fa-sliders"></i> Einstellungen <InfoKnopf anker="einstellungen" /></div>
  <div class="m-seite-koerper p-0">
    <div class="list-group list-group-flush">
      {#each gruppen as g (g.kennung)}
        <a href="#/einstellungen/{g.kennung}" class="list-group-item list-group-item-action" class:active={aktiv === g.kennung && !woerter.length} onclick={(e) => { e.preventDefault(); suche = ""; ui.gehe("einstellungen", g.kennung); }}>{g.titel}</a>
      {/each}
      <div class="list-group-item bg-body-tertiary small text-uppercase text-secondary fw-semibold py-1">Verwaltung</div>
      {#each SONDER as s (s.kennung)}
        <a href="#/einstellungen/{s.kennung}" class="list-group-item list-group-item-action" class:active={aktiv === s.kennung} onclick={(e) => { e.preventDefault(); suche = ""; ui.gehe("einstellungen", s.kennung); }}><i class="fa-solid {s.icon} me-2"></i>{s.titel}</a>
      {/each}
    </div>
  </div>
</aside>

{#if sonder?.kennung === "anbieter-verwaltung"}
  <Anbieter />
{:else if sonder?.kennung === "quellen"}
  <Quellen />
{:else if sonder?.kennung === "umzug"}
  <Umzug />
{:else}
  <section class="m-ansicht">
    <div class="m-ansicht-kopf">
      <h1>Einstellungen - {gruppeTitel}</h1>
      {#if gespeichert}<span class="m-unter"><i class="fa-solid fa-check text-success"></i> Gespeichert {uhrzeit(gespeichert)}</span>{/if}
      <span class="m-luecke"></span>
      <input class="form-control form-control-sm" style="width: 280px" placeholder="Einstellung suchen ..." bind:value={suche} />
    </div>
    <div class="m-ansicht-koerper">
      {#if laden}
        <div class="m-leer"><i class="fa-solid fa-circle-notch fa-spin"></i>Einstellungen werden geladen.</div>
      {:else if !sichtbar.length}
        <div class="m-leer"><i class="fa-solid fa-magnifying-glass"></i>Keine Einstellung passt.</div>
      {:else}
        <div class="list-group">
          {#each sichtbar as e (e.schluessel)}
            <div class="list-group-item py-3" class:bg-primary-subtle={e.geaendert}>
              <div class="row g-3 align-items-center">
                <div class="col-lg-7">
                  <div class="fw-semibold">{e.titel} {#if woerter.length}<span class="badge text-bg-secondary ms-1">{e.gruppe_titel}</span>{/if}</div>
                  <div class="text-secondary">{e.beschreibung}</div>
                  {#if e.minimum !== null || e.maximum !== null}
                    <div class="small text-secondary mt-1">Bereich {e.minimum ?? "-"} bis {e.maximum ?? "-"}{e.einheit ? ` ${e.einheit}` : ""}</div>
                  {/if}
                </div>
                <div class="col-lg-5">
                  <div class="d-flex align-items-center gap-2 justify-content-lg-end">
                    {#if e.typ === "schalter"}
                      <div class="form-check form-switch fs-5 mb-0">
                        <input class="form-check-input" type="checkbox" role="switch" id="e-{e.schluessel}" checked={Boolean(e.wert)} onchange={(ev) => setze(e, (ev.target as HTMLInputElement).checked)} />
                        <label class="form-check-label fs-6" for="e-{e.schluessel}">{e.wert ? "an" : "aus"}</label>
                      </div>
                    {:else if e.typ === "auswahl"}
                      <select class="form-select" style="max-width: 320px" value={String(e.wert)} onchange={(ev) => setze(e, (ev.target as HTMLSelectElement).value)}>
                        {#each e.auswahl as o (o.wert)}<option value={o.wert}>{o.titel}</option>{/each}
                      </select>
                    {:else if e.typ === "zahl" || e.typ === "ganzzahl"}
                      <div class="input-group" style="max-width: 240px">
                        <input class="form-control text-end" type="number" value={e.wert as number} min={e.minimum ?? undefined} max={e.maximum ?? undefined} step={e.schritt ?? (e.typ === "ganzzahl" ? 1 : 0.01)} onchange={(ev) => zahlEingabe(e, ev)} />
                        {#if e.einheit}<span class="input-group-text">{e.einheit}</span>{/if}
                      </div>
                    {:else}
                      <input class="form-control" style="max-width: 360px" value={String(e.wert ?? "")} onchange={(ev) => setze(e, (ev.target as HTMLInputElement).value)} />
                    {/if}
                    <span class="small text-secondary text-nowrap" title="Vorgabe">Vorgabe: {e.typ === "schalter" ? (e.vorgabe ? "an" : "aus") : e.typ === "auswahl" ? (e.auswahl.find((o) => o.wert === e.vorgabe)?.titel ?? String(e.vorgabe)) : String(e.vorgabe)}</span>
                    {#if e.geaendert}
                      <button class="btn btn-sm btn-outline-secondary text-nowrap" title="Auf die Vorgabe zurücksetzen" onclick={() => zuruecksetzen(e)}><i class="fa-solid fa-rotate-left"></i></button>
                    {/if}
                  </div>
                </div>
              </div>
            </div>
          {/each}
        </div>
      {/if}
    </div>
  </section>
{/if}
