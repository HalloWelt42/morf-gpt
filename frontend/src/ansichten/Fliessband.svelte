<script lang="ts">
  // Fließband: Stufen mit Zählern, Durchsatz und Restzeit; Aufträge nach Status; Protokoll live.
  import { onDestroy, onMount } from "svelte";
  import { api, mitParametern } from "../lib/api";
  import type { ArtUebersicht, AuftragEintrag, BandUebersicht, Quelle, Seite, Uebersicht } from "../lib/typen";
  import { ereignisse } from "../lib/stores/ereignisse.svelte";
  import { ui } from "../lib/stores/ui.svelte";
  import { meldungen, meldeFehler } from "../lib/stores/meldungen.svelte";
  import { dauerWorte, vorZeit, zahl, uhrzeit, folge } from "../lib/format";
  import InfoKnopf from "../lib/komponenten/InfoKnopf.svelte";
  import Abzeichen from "../lib/komponenten/Abzeichen.svelte";
  import Seitenwahl from "../lib/komponenten/Seitenwahl.svelte";
  import Bestaetigung from "../lib/komponenten/Bestaetigung.svelte";

  const STUFE_JE_ART: Record<string, string> = {
    audio: "audio",
    transkription: "transkribiert",
    korrektur: "korrigiert",
    stueckelung: "gestueckelt",
    einbettung: "eingebettet",
  };
  const ICON_JE_ART: Record<string, string> = {
    quelle_abgleich: "fa-satellite-dish",
    audio: "fa-headphones",
    transkription: "fa-closed-captioning",
    korrektur: "fa-spell-check",
    stueckelung: "fa-scissors",
    einbettung: "fa-cube",
  };

  let band = $state<BandUebersicht | null>(null);
  let uebersicht = $state<Uebersicht | null>(null);
  let quellen = $state<Quelle[]>([]);
  let status = $state<"laeuft" | "wartend" | "fehler" | "abgebrochen" | "fertig">("laeuft");
  let auftraege = $state<Seite<AuftragEintrag> | null>(null);
  let seite = $state(1);
  let jeSeite = $state(50);
  let protokoll = $state<{ zeit: string; stufe: string; text: string; art: string; video: string }[]>([]);
  let mitrollen = $state(true);
  let protokollFeld = $state<HTMLDivElement | null>(null);
  let allesAnhaltenDialog = $state(false);
  let aufraeumDialog = $state(false);
  let beschaeftigt = $state(false);
  let takt: number | null = null;
  const abos: (() => void)[] = [];

  const stufenZaehler = $derived.by(() => {
    const m = new Map<string, number>();
    for (const s of uebersicht?.stufen ?? []) m.set(s.stufe, s.anzahl);
    return m;
  });

  /** Fertig je Stufe = alle Videos, die diese Stufe erreicht oder überschritten haben. */
  function fertigAb(stufe: string): number {
    const reihe = ["entdeckt", "audio", "transkribiert", "korrigiert", "gestueckelt", "eingebettet"];
    const i = reihe.indexOf(stufe);
    let n = 0;
    for (let k = i; k < reihe.length; k++) n += stufenZaehler.get(reihe[k]) ?? 0;
    return n;
  }

  async function laden(): Promise<void> {
    try {
      const [b, u, q] = await Promise.all([api.get<BandUebersicht>("/auftraege/uebersicht"), api.get<Uebersicht>("/system/uebersicht"), api.get<Quelle[]>("/quellen")]);
      band = b;
      uebersicht = u;
      quellen = q;
    } catch (e) {
      meldeFehler(e, "Fließband laden");
    }
    await ladeAuftraege();
  }

  async function ladeAuftraege(): Promise<void> {
    try {
      auftraege = await api.get<Seite<AuftragEintrag>>(mitParametern("/auftraege", { status, seite, je_seite: jeSeite }));
    } catch (e) {
      meldeFehler(e, "Aufträge laden");
    }
  }

  function wechsle(s: typeof status): void {
    status = s;
    seite = 1;
    void ladeAuftraege();
  }

  async function pause(a: ArtUebersicht, pausiert: boolean): Promise<void> {
    try {
      await api.post("/auftraege/band/pause", { art: a.art, pausiert });
      await laden();
    } catch (e) {
      meldeFehler(e, "Stufe anhalten");
    }
  }

  async function allesAnhalten(): Promise<void> {
    beschaeftigt = true;
    try {
      for (const a of band?.arten.filter((x) => x.pausierbar) ?? []) await api.post("/auftraege/band/pause", { art: a.art, pausiert: true });
      allesAnhaltenDialog = false;
      meldungen.gut("Alle Stufen angehalten; laufende Aufträge enden noch");
      await laden();
    } catch (e) {
      meldeFehler(e, "Anhalten");
    } finally {
      beschaeftigt = false;
    }
  }

  async function allesFortsetzen(): Promise<void> {
    try {
      for (const a of band?.arten.filter((x) => x.pausierbar) ?? []) await api.post("/auftraege/band/pause", { art: a.art, pausiert: false });
      meldungen.gut("Alle Stufen laufen wieder");
      await laden();
    } catch (e) {
      meldeFehler(e, "Fortsetzen");
    }
  }

  async function auffuellen(): Promise<void> {
    try {
      const r = await api.post<{ angelegt: number }>("/auftraege/band/auffuellen");
      meldungen.gut(`${zahl(r.angelegt)} Aufträge angelegt`);
      await laden();
    } catch (e) {
      meldeFehler(e, "Band auffüllen");
    }
  }

  async function abgleichen(): Promise<void> {
    if (!quellen.length) {
      meldungen.fehler("Keine Quelle angelegt (Einstellungen, Quellen)");
      return;
    }
    try {
      const r = await api.post<{ auftrag_id: string | null; hinweis: string }>(`/quellen/${quellen[0].id}/abgleich`);
      meldungen.gut(r.hinweis);
      await laden();
    } catch (e) {
      meldeFehler(e, "Abgleich");
    }
  }

  async function automatik(an: boolean): Promise<void> {
    try {
      await api.put("/einstellungen/band.automatik", { wert: an });
      await laden();
    } catch (e) {
      meldeFehler(e, "Automatik");
    }
  }

  async function fehlerWiederholen(): Promise<void> {
    try {
      const r = await api.post<{ anzahl: number }>("/auftraege/fehler/wiederholen");
      meldungen.gut(`${zahl(r.anzahl)} Aufträge erneut eingereiht`);
      await laden();
    } catch (e) {
      meldeFehler(e, "Wiederholen");
    }
  }

  async function abgebrocheneEinreihen(): Promise<void> {
    try {
      const r = await api.post<{ anzahl: number }>("/auftraege/abgebrochene/wiederholen");
      meldungen.gut(`${zahl(r.anzahl)} abgebrochene Aufträge wieder eingereiht`);
      await laden();
    } catch (e) {
      meldeFehler(e, "Wieder einreihen");
    }
  }

  async function aufraeumen(): Promise<void> {
    beschaeftigt = true;
    try {
      const r = await api.del<{ geloescht: number; tage: number }>("/auftraege/erledigte?tage=7");
      meldungen.gut(`${zahl(r.geloescht)} erledigte Aufträge älter als ${r.tage} Tage entfernt`);
      aufraeumDialog = false;
      await laden();
    } catch (e) {
      meldeFehler(e, "Aufräumen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function abbrechen(a: AuftragEintrag): Promise<void> {
    try {
      const r = await api.post<{ hinweis: string }>(`/auftraege/${a.id}/abbrechen`);
      meldungen.zeige(r.hinweis);
      await laden();
    } catch (e) {
      meldeFehler(e, "Abbrechen");
    }
  }

  async function wiederholen(a: AuftragEintrag): Promise<void> {
    try {
      await api.post(`/auftraege/${a.id}/wiederholen`);
      meldungen.gut("Auftrag erneut eingereiht");
      await laden();
    } catch (e) {
      meldeFehler(e, "Wiederholen");
    }
  }

  function protokollZeile(z: { zeit: string; stufe: string; text: string; art: string; video: string }): void {
    protokoll = [...protokoll.slice(-399), z];
    if (mitrollen && protokollFeld) queueMicrotask(() => { if (protokollFeld) protokollFeld.scrollTop = protokollFeld.scrollHeight; });
  }

  let nachladen: number | null = null;
  function verzoegertLaden(): void {
    if (nachladen) return;
    nachladen = window.setTimeout(() => { nachladen = null; void laden(); }, 1500);
  }

  onMount(() => {
    void laden();
    takt = window.setInterval(() => void laden(), 15000);
    abos.push(
      ereignisse.abonniere("auftrag_protokoll", (e) => {
        protokollZeile({ zeit: String(e.daten.zeit ?? ""), stufe: String(e.daten.stufe ?? "info"), text: String(e.daten.text ?? ""), art: "", video: String(e.daten.video_id ?? "").slice(0, 8) });
      }),
      ereignisse.abonniere("auftrag_status", () => verzoegertLaden()),
      ereignisse.abonniere("auftrag_fortschritt", (e) => {
        if (!auftraege) return;
        const a = auftraege.eintraege.find((x) => x.id === e.daten.auftrag_id);
        if (a) {
          a.fortschritt = Number(e.daten.fortschritt ?? a.fortschritt);
          a.meldung = String(e.daten.meldung ?? a.meldung);
        }
      }),
    );
  });

  onDestroy(() => {
    if (takt) window.clearInterval(takt);
    if (nachladen) window.clearTimeout(nachladen);
    for (const ab of abos) ab();
  });
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <h1>Fließband</h1>
    <span class="m-unter">
      {zahl(uebersicht?.videos_ausgewaehlt)} Videos im Umfang &middot; {zahl(band?.laufend_gesamt)} laufen &middot; {zahl(band?.wartend_gesamt)} warten &middot; {zahl(band?.fehler_gesamt)} Fehler{#if band?.abgebrochen_gesamt} &middot; <span class="text-warning" title="Von Hand gestoppte Aufträge, deren Video noch auf diesen Schritt wartet; unter dem Reiter Abgebrochen wieder einreihen">{zahl(band.abgebrochen_gesamt)} abgebrochen</span>{/if}
    </span>
    <InfoKnopf anker="fliessband" />
    <span class="m-luecke"></span>
    {#if band}
      <div class="form-check form-switch mb-0 me-2" title="Nach einer fertigen Stufe automatisch den nächsten Auftrag anlegen">
        <input class="form-check-input" type="checkbox" role="switch" id="automatik" checked={band.automatik} title="Automatik an: nach jedem fertigen Auftrag wird der nächste Schritt von selbst angelegt. Aus: jeder Schritt wird von Hand angestoßen." onchange={(e) => automatik((e.target as HTMLInputElement).checked)} />
        <label class="form-check-label small" for="automatik">Automatisch weiterreichen</label>
      </div>
    {/if}
    <button class="btn btn-sm btn-outline-secondary" title="Kanal mit der Quelle abgleichen und neue Videos aufnehmen" onclick={abgleichen}><i class="fa-solid fa-rotate"></i> Quelle abgleichen</button>
    <button class="btn btn-sm btn-outline-secondary" title="Für alle Videos im Umfang den nächsten Schritt anlegen" onclick={auffuellen}><i class="fa-solid fa-fill-drip"></i> Band auffüllen</button>
    {#if band?.arten.some((a) => a.pausierbar && !a.pausiert)}
      <button class="btn btn-sm btn-outline-warning" title="Alle Stufen anhalten, laufende Aufträge enden noch" onclick={() => (allesAnhaltenDialog = true)}><i class="fa-solid fa-pause"></i> Alles anhalten</button>
    {:else if band}
      <button class="btn btn-sm btn-outline-success" title="Alle Stufen wieder laufen lassen" onclick={allesFortsetzen}><i class="fa-solid fa-play"></i> Alles fortsetzen</button>
    {/if}
  </div>

  <div class="m-ansicht-koerper d-flex flex-column gap-3" style="overflow: hidden">
    <div class="m-band">
      <div class="m-band-stufe">
        <div class="titel d-flex align-items-center gap-1"><i class="fa-solid fa-satellite-dish"></i> Entdeckt <InfoKnopf anker="stufe-abgleich" titel="Was beim Abgleich mit der Quelle passiert" /></div>
        <div class="zahl">{zahl(uebersicht?.videos_ausgewaehlt)}</div>
        <div class="klein">im Umfang, {zahl(uebersicht?.videos_gesamt)} gesamt</div>
        <div class="zeile"><span>Quelle</span><span>{quellen[0]?.typ_titel ?? "-"}</span></div>
        <div class="zeile"><span>Zuletzt abgeglichen</span><span>{quellen[0]?.zuletzt_abgeglichen ? vorZeit(quellen[0].zuletzt_abgeglichen) : "-"}</span></div>
      </div>
      {#each band?.arten.filter((a) => a.art !== "quelle_abgleich") ?? [] as a (a.art)}
        {@const stufe = STUFE_JE_ART[a.art]}
        {@const fertig = fertigAb(stufe)}
        {@const gesamt = uebersicht?.videos_ausgewaehlt ?? 0}
        <div class="m-band-stufe {stufe}">
          <div class="titel d-flex align-items-center gap-1"><i class="fa-solid {ICON_JE_ART[a.art]}"></i> {a.titel} <InfoKnopf anker="stufe-{a.art}" titel="Was in diesem Schritt passiert und warum er wichtig ist" /></div>
          <div class="zahl">{zahl(fertig)}</div>
          <div class="klein">fertig &middot; {a.laufend} {a.laufend === 1 ? "läuft" : "laufen"} &middot; {zahl(a.wartend)} warten{#if a.fehler} &middot; <span class="text-danger">{a.fehler} Fehler</span>{/if}{#if a.abgebrochen} &middot; <span class="text-warning" title="Von Hand gestoppt; das Video wartet noch auf diesen Schritt">{a.abgebrochen} abgebrochen</span>{/if}</div>
          <div class="m-fortschritt" class:laeuft={a.laufend > 0}><span style="width: {gesamt ? Math.round((fertig / gesamt) * 100) : 0}%"></span></div>
          <div class="zeile"><span>Durchsatz</span><span>{a.durchsatz_fenster} je Stunde</span></div>
          <div class="zeile"><span>Rest</span><span>{a.restzeit_s !== null ? `etwa ${dauerWorte(a.restzeit_s)}` : "-"}</span></div>
          <div class="form-check form-switch mt-1">
            <input class="form-check-input" type="checkbox" role="switch" id="p-{a.art}" checked={!a.pausiert} title="Stufe anhalten oder weiterlaufen lassen; laufende Aufträge enden noch, neue starten nicht" onchange={(e) => pause(a, !(e.target as HTMLInputElement).checked)} />
            <label class="form-check-label small" for="p-{a.art}">{a.pausiert ? "angehalten" : `läuft (${a.parallel} parallel)`}</label>
          </div>
        </div>
      {/each}
    </div>

    <div class="d-flex gap-3 flex-grow-1" style="min-height: 0">
      <div class="d-flex flex-column flex-grow-1" style="min-width: 0; min-height: 0">
        <ul class="nav nav-tabs">
          {#each [["laeuft", "Laufend", band?.laufend_gesamt ?? 0, "primary"], ["wartend", "Wartend", band?.wartend_gesamt ?? 0, "secondary"], ["fehler", "Fehler", band?.fehler_gesamt ?? 0, "danger"], ["abgebrochen", "Abgebrochen", band?.abgebrochen_gesamt ?? 0, "warning"], ["fertig", "Fertig", null, "success"]] as [s, titel, n, farbe]}
            <li class="nav-item"><a class="nav-link" class:active={status === s} href="#/fliessband" title={s === "abgebrochen" ? "Von Hand gestoppte Aufträge, deren Video noch auf diesen Schritt wartet" : undefined} onclick={(e) => { e.preventDefault(); wechsle(s as typeof status); }}>{titel} {#if n !== null}<span class="badge text-bg-{farbe}">{zahl(n as number)}</span>{/if}</a></li>
          {/each}
          <li class="nav-item ms-auto d-flex align-items-center gap-2 pe-1">
            {#if band?.abgebrochen_gesamt}
              <button class="btn btn-sm btn-outline-warning" title="Alle von Hand gestoppten Aufträge, deren Video noch wartet, wieder in die Reihe stellen (beginnen von vorn)" onclick={abgebrocheneEinreihen}><i class="fa-solid fa-rotate-left"></i> Abgebrochene einreihen</button>
            {/if}
            <button class="btn btn-sm btn-outline-secondary" title="Alle fehlgeschlagenen Aufträge erneut versuchen" onclick={fehlerWiederholen}><i class="fa-solid fa-rotate-right"></i> Fehler wiederholen</button>
            <button class="btn btn-sm btn-outline-secondary" title="Fertige Aufträge älter als 7 Tage aufräumen" onclick={() => (aufraeumDialog = true)}><i class="fa-solid fa-broom"></i> Aufräumen</button>
          </li>
        </ul>
        <div class="m-tabelle-feld flex-grow-1" style="border-top: 0">
          <table class="table table-hover table-sm align-middle">
            <thead>
              <tr><th style="width: 150px">Stufe</th><th>Video</th><th style="width: 100px">Serie</th><th style="width: 240px">Fortschritt</th><th style="width: 130px">{status === "fertig" ? "Dauer" : "Seit"}</th><th style="width: 80px"></th></tr>
            </thead>
            <tbody>
              {#each auftraege?.eintraege ?? [] as a (a.id)}
                <tr class:table-danger={a.status === "fehler"} class:table-warning={a.status === "abgebrochen"} onclick={() => ui.gehe("auftrag", a.id)}>
                  <td><Abzeichen stufe={STUFE_JE_ART[a.art] ?? "entdeckt"} titel={a.art_titel} /></td>
                  <td class="text-truncate" style="max-width: 420px">{a.video_titel || a.art_titel}{#if a.fehler}<small class="text-danger ms-2">{a.fehler}</small>{/if}</td>
                  <td>{#if a.video_serie}<Abzeichen serie={a.video_serie} folgeNr={a.video_folge_nr} />{/if}</td>
                  <td>
                    <div class="m-fortschritt mb-1" class:laeuft={a.status === "laeuft"}><span style="width: {Math.round(a.fortschritt * 100)}%{a.status === 'fehler' ? '; background: #b3352c' : ''}"></span></div>
                    <small class="text-secondary">{a.meldung}</small>
                  </td>
                  <td class="text-secondary">{a.status === "fertig" ? dauerWorte(a.laufzeit_s) : a.gestartet ? vorZeit(a.gestartet) : vorZeit(a.erstellt)}</td>
                  <td>
                    {#if a.status === "laeuft" || a.status === "wartend"}
                      <button class="btn btn-sm btn-outline-danger" title="Auftrag abbrechen" onclick={(e) => { e.stopPropagation(); void abbrechen(a); }}><i class="fa-solid fa-stop"></i></button>
                    {:else if a.status === "fehler" || a.status === "abgebrochen"}
                      <button class="btn btn-sm btn-outline-secondary" title={a.status === "abgebrochen" ? "Wieder einreihen; der Auftrag beginnt von vorn" : "Erneut versuchen"} onclick={(e) => { e.stopPropagation(); void wiederholen(a); }}><i class="fa-solid fa-rotate-right"></i></button>
                    {/if}
                  </td>
                </tr>
              {/each}
              {#if auftraege && !auftraege.eintraege.length}
                <tr><td colspan="6" class="text-center text-secondary py-4">Keine Aufträge in diesem Zustand.</td></tr>
              {/if}
            </tbody>
          </table>
        </div>
        {#if auftraege && auftraege.gesamt > jeSeite}
          <div class="py-2"><Seitenwahl bind:seite bind:jeSeite gesamt={auftraege.gesamt} onWechsel={ladeAuftraege} /></div>
        {/if}
      </div>

      <div class="d-flex flex-column" style="width: 440px; min-height: 0">
        <div class="d-flex align-items-center mb-1">
          <h6 class="m-0"><i class="fa-solid fa-terminal"></i> Protokoll (live)</h6>
          <div class="form-check form-switch ms-auto mb-0"><input class="form-check-input" type="checkbox" id="mitrollen" bind:checked={mitrollen} title="Das Protokoll springt bei neuen Zeilen automatisch ans Ende" /><label class="form-check-label small" for="mitrollen">mitrollen</label></div>
        </div>
        <div class="m-protokoll flex-grow-1" bind:this={protokollFeld}>
          {#if !protokoll.length}<div class="text-secondary">Sobald Aufträge laufen, erscheinen hier ihre Meldungen.</div>{/if}
          {#each protokoll as z}
            <div class={z.stufe === "warn" ? "warn" : z.stufe === "fehler" ? "fehler" : ""}><span class="zeit">{uhrzeit(z.zeit)}</span>{#if z.video}[{z.video}] {/if}{z.text}</div>
          {/each}
        </div>
      </div>
    </div>
  </div>
</section>

<Bestaetigung bind:offen={allesAnhaltenDialog} titel="Alle Stufen anhalten" bestaetigen="Anhalten" {beschaeftigt} onBestaetigen={allesAnhalten}>
  <p>Es werden keine neuen Aufträge mehr gestartet. Laufende Aufträge enden noch regulär. Mit "Alles fortsetzen" geht es weiter.</p>
</Bestaetigung>
<Bestaetigung bind:offen={aufraeumDialog} titel="Erledigte Aufträge aufräumen" bestaetigen="Aufräumen" {beschaeftigt} onBestaetigen={aufraeumen}>
  <p>Fertige und abgebrochene Aufträge, die älter als 7 Tage sind, werden samt Protokoll entfernt. Die Ergebnisse (Audio, Transkripte, Stücke) bleiben.</p>
</Bestaetigung>

<span class="visually-hidden">{folge("", null)}</span>
