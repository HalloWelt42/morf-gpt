<script lang="ts">
  // Quellen: bestehende Quelle mit Regeln, neue Quelle mit Kanalprüfung, Vorschau der Kanalvideos.
  import { onDestroy, onMount } from "svelte";
  import { ereignisse } from "../../lib/stores/ereignisse.svelte";
  import { api, mitParametern } from "../../lib/api";
  import type { KanalAusgabe, Quelle, Seite, VorschauEintrag } from "../../lib/typen";
  import { meldungen, meldeFehler } from "../../lib/stores/meldungen.svelte";
  import { datum, vorZeit, zahl, zeitmarke } from "../../lib/format";
  import InfoKnopf from "../../lib/komponenten/InfoKnopf.svelte";
  import Bestaetigung from "../../lib/komponenten/Bestaetigung.svelte";
  import Seitenwahl from "../../lib/komponenten/Seitenwahl.svelte";

  let quellen = $state<Quelle[]>([]);
  let typen = $state<Record<string, string>>({});
  const ADRESSE_VORGABE: Record<string, string> = { tubevault: "http://192.168.178.49:8031", lokal: "" };
  let neu = $state({ typ: "tubevault", name: "", basis_url: ADRESSE_VORGABE.tubevault, kanal_id: "" });
  const istLokal = $derived(neu.typ === "lokal");

  function typGewechselt(): void {
    neu.basis_url = ADRESSE_VORGABE[neu.typ] ?? "";
    neu.kanal_id = "";
    kanal = null;
  }
  let kanal = $state<KanalAusgabe | null>(null);
  let pruefen = $state(false);
  let beschaeftigt = $state(false);
  let entfernenDialog = $state(false);
  let ziel = $state<Quelle | null>(null);
  let vorschau = $state<Seite<VorschauEintrag> | null>(null);
  let vorschauQuelle = $state<Quelle | null>(null);
  let vorschauSeite = $state(1);
  let vorschauJeSeite = $state(50);
  let bearbeiten = $state<Quelle | null>(null);
  let regeln = $state<{ mindest_dauer_s: string; typen: string; nur_heruntergeladene: string }>({ mindest_dauer_s: "", typen: "", nur_heruntergeladene: "" });

  async function laden(): Promise<void> {
    try {
      quellen = await api.get<Quelle[]>("/quellen");
      typen = await api.get<Record<string, string>>("/quellen/typen");
    } catch (e) {
      meldeFehler(e, "Quellen laden");
    }
  }

  async function kanalPruefen(): Promise<void> {
    pruefen = true;
    kanal = null;
    try {
      kanal = await api.post<KanalAusgabe>("/quellen/pruefen", { typ: neu.typ, basis_url: neu.basis_url, kanal_id: istLokal ? "" : neu.kanal_id });
      if (!neu.name) neu.name = kanal.name;
    } catch (e) {
      meldeFehler(e, "Kanal prüfen");
    } finally {
      pruefen = false;
    }
  }

  async function anlegen(): Promise<void> {
    beschaeftigt = true;
    try {
      await api.post<Quelle>("/quellen", { ...neu, kanal_id: istLokal ? "" : neu.kanal_id });
      meldungen.gut("Quelle angelegt");
      neu = { typ: neu.typ, name: "", basis_url: istLokal ? "" : neu.basis_url, kanal_id: "" };
      kanal = null;
      await laden();
    } catch (e) {
      meldeFehler(e, "Quelle anlegen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function abgleichen(q: Quelle): Promise<void> {
    try {
      const r = await api.post<{ hinweis: string }>(`/quellen/${q.id}/abgleich`);
      meldungen.gut(r.hinweis);
    } catch (e) {
      meldeFehler(e, "Abgleich");
    }
  }

  async function entfernen(): Promise<void> {
    if (!ziel) return;
    beschaeftigt = true;
    try {
      await api.del(`/quellen/${ziel.id}`);
      meldungen.gut("Quelle entfernt; die Videos bleiben in der Bibliothek");
      entfernenDialog = false;
      await laden();
    } catch (e) {
      meldeFehler(e, "Entfernen");
    } finally {
      beschaeftigt = false;
    }
  }

  async function ladeVorschau(q: Quelle | null = vorschauQuelle): Promise<void> {
    if (!q) return;
    vorschauQuelle = q;
    try {
      vorschau = await api.get<Seite<VorschauEintrag>>(mitParametern(`/quellen/${q.id}/vorschau`, { seite: vorschauSeite, je_seite: vorschauJeSeite }));
    } catch (e) {
      meldeFehler(e, "Vorschau");
    }
  }

  function bearbeite(q: Quelle): void {
    bearbeiten = q;
    regeln = {
      mindest_dauer_s: q.regeln.mindest_dauer_s === undefined || q.regeln.mindest_dauer_s === null ? "" : String(q.regeln.mindest_dauer_s),
      typen: (q.regeln.typen as string | undefined) ?? "",
      nur_heruntergeladene: q.regeln.nur_heruntergeladene === undefined || q.regeln.nur_heruntergeladene === null ? "" : String(q.regeln.nur_heruntergeladene),
    };
  }

  async function speichern(): Promise<void> {
    if (!bearbeiten) return;
    beschaeftigt = true;
    try {
      const r: Record<string, unknown> = {};
      if (regeln.mindest_dauer_s !== "") r.mindest_dauer_s = Number(regeln.mindest_dauer_s);
      if (regeln.typen !== "") r.typen = regeln.typen;
      if (regeln.nur_heruntergeladene !== "") r.nur_heruntergeladene = regeln.nur_heruntergeladene === "true";
      await api.put(`/quellen/${bearbeiten.id}`, { name: bearbeiten.name, basis_url: bearbeiten.basis_url, kanal_id: bearbeiten.kanal_id, regeln: r, aktiv: bearbeiten.aktiv });
      meldungen.gut("Quelle gespeichert");
      bearbeiten = null;
      await laden();
    } catch (e) {
      meldeFehler(e, "Speichern");
    } finally {
      beschaeftigt = false;
    }
  }

  // Nach einem Abgleich (läuft als Auftrag) die Zähler der Quellen auffrischen.
  const abo = ereignisse.abonniere("quelle", () => void laden());
  onMount(() => void laden());
  onDestroy(() => abo());
</script>

<section class="m-ansicht">
  <div class="m-ansicht-kopf">
    <h1>Quellen</h1>
    <span class="m-unter">Woher die Videos kommen: ein Dienst oder ein Verzeichnis auf diesem Rechner</span>
    <InfoKnopf anker="quellen" />
  </div>
  <div class="m-ansicht-koerper">
    {#each quellen as q (q.id)}
      <div class="card mb-3">
        <div class="card-body">
          <div class="d-flex align-items-start gap-3 flex-wrap">
            <div class="flex-grow-1">
              <div class="fs-5 fw-semibold">{q.name} <span class="badge text-bg-secondary">{q.typ_titel}</span>{#if !q.aktiv}<span class="badge text-bg-dark ms-1">deaktiviert</span>{/if}</div>
              <div class="text-secondary">{#if q.typ === "lokal"}Verzeichnis {q.basis_url}{#if q.kanal_beschreibung} &middot; {q.kanal_beschreibung}{/if}{:else}{q.basis_url} &middot; Kanal {q.kanal_id}{#if q.kanal_name} ({q.kanal_name}){/if}{/if}</div>
              <div class="mt-1">{zahl(q.videos)} Videos, {zahl(q.videos_ausgewaehlt)} im Umfang &middot; zuletzt abgeglichen {q.zuletzt_abgeglichen ? vorZeit(q.zuletzt_abgeglichen) : "nie"}</div>
              <div class="small text-secondary mt-1">
                Regeln: {q.regeln.mindest_dauer_s !== undefined && q.regeln.mindest_dauer_s !== null ? `Mindestdauer ${q.regeln.mindest_dauer_s} Sekunden` : "Mindestdauer aus den Einstellungen"},
                {q.regeln.typen ? `Arten ${q.regeln.typen}` : "Arten aus den Einstellungen"},
                {#if q.typ !== "lokal"}{q.regeln.nur_heruntergeladene !== undefined && q.regeln.nur_heruntergeladene !== null ? (q.regeln.nur_heruntergeladene ? "nur heruntergeladene" : "auch nicht heruntergeladene") : "Downloadstand aus den Einstellungen"}{:else}jede Datei gilt als vorhanden{/if}
                <InfoKnopf anker="quellen" />
              </div>
            </div>
            <div class="d-flex gap-2 flex-wrap">
              <button class="btn btn-sm btn-primary" onclick={() => abgleichen(q)} title="Die Quelle jetzt lesen: neue Videos anlegen, bekannte auffrischen, Aufnahmeregel anwenden (läuft als Auftrag)"><i class="fa-solid fa-rotate"></i> Jetzt abgleichen</button>
              <button class="btn btn-sm btn-outline-secondary" onclick={() => { vorschauSeite = 1; void ladeVorschau(q); }} title="Zeigt, was die Quelle liefert und welche Videos nach den Regeln aufgenommen würden, ohne etwas zu ändern"><i class="fa-solid fa-eye"></i> Vorschau</button>
              <button class="btn btn-sm btn-outline-secondary" onclick={() => bearbeite(q)} title="Name, Adresse oder Verzeichnis und die Aufnahmeregeln dieser Quelle ändern"><i class="fa-solid fa-pen"></i> Bearbeiten</button>
              <button class="btn btn-sm btn-outline-danger" onclick={() => { ziel = q; entfernenDialog = true; }} title="Quelle entfernen; ihre Videos bleiben in der Bibliothek, nur der Abgleich endet (fragt nach)"><i class="fa-solid fa-trash"></i> Entfernen</button>
            </div>
          </div>
          {#if bearbeiten?.id === q.id}
            <hr />
            <div class="row g-3">
              <div class="col-md-4"><label class="form-label" for="q-name">Name</label><input class="form-control" id="q-name" bind:value={bearbeiten.name} title="Anzeigename der Quelle" /></div>
              {#if bearbeiten.typ === "lokal"}
                <div class="col-md-8"><label class="form-label" for="q-url">Verzeichnis</label><input class="form-control" id="q-url" bind:value={bearbeiten.basis_url} /></div>
              {:else}
                <div class="col-md-5"><label class="form-label" for="q-url">Basisadresse</label><input class="form-control" id="q-url" bind:value={bearbeiten.basis_url} /></div>
                <div class="col-md-3"><label class="form-label" for="q-kanal">Kanalkennung</label><input class="form-control" id="q-kanal" bind:value={bearbeiten.kanal_id} title="Kennung des Kanals, wie die Quelle sie führt (bei YouTube beginnt sie mit UC)" /></div>
              {/if}
              <div class="col-md-4"><label class="form-label" for="r-dauer">Mindestdauer (leer = Einstellungen)</label><div class="input-group"><input class="form-control" id="r-dauer" type="number" bind:value={regeln.mindest_dauer_s} title="Nur Videos, die länger sind als dieser Wert, kommen automatisch in den Umfang; leer heißt Wert aus den Einstellungen" /><span class="input-group-text">Sekunden</span></div></div>
              <div class="col-md-4"><label class="form-label" for="r-typen">Arten (leer = Einstellungen)</label><input class="form-control" id="r-typen" placeholder="video,live" bind:value={regeln.typen} title="Welche Arten aufgenommen werden, durch Komma getrennt: video, live, short; leer heißt Wert aus den Einstellungen" /></div>
              {#if bearbeiten.typ !== "lokal"}<div class="col-md-4"><label class="form-label" for="r-dl">Nur heruntergeladene</label><select class="form-select" id="r-dl" bind:value={regeln.nur_heruntergeladene} title="Nur Videos aufnehmen, die in der Quelle schon als Datei vorliegen"><option value="">aus den Einstellungen</option><option value="true">ja</option><option value="false">nein</option></select></div>{/if}
              <div class="col-md-12 d-flex gap-2 align-items-center">
                <div class="form-check form-switch"><input class="form-check-input" type="checkbox" id="q-aktiv" bind:checked={bearbeiten.aktiv} title="Eine deaktivierte Quelle wird nicht mehr abgeglichen" /><label class="form-check-label" for="q-aktiv">aktiv</label></div>
                <span class="ms-auto"></span>
                <button class="btn btn-outline-secondary" onclick={() => (bearbeiten = null)}>Abbrechen</button>
                <button class="btn btn-primary" onclick={speichern} disabled={beschaeftigt}>Speichern</button>
              </div>
            </div>
          {/if}
        </div>
      </div>
    {/each}

    <div class="card mb-3">
      <div class="card-header fw-semibold">Neue Quelle</div>
      <div class="card-body">
        <div class="row g-3">
          <div class="col-md-3"><label class="form-label" for="n-typ">Typ <InfoKnopf anker="quellen" /></label><select class="form-select" id="n-typ" bind:value={neu.typ} onchange={typGewechselt} title="TubeVault: ein Kanal in einem Videodienst. Lokale Dateien: ein Verzeichnis mit eigenen Video- und Audiodateien auf diesem Rechner.">{#each Object.entries(typen) as [k, t] (k)}<option value={k}>{t}</option>{/each}</select></div>
          <div class="col-md-3"><label class="form-label" for="n-name">Name</label><input class="form-control" id="n-name" bind:value={neu.name} placeholder={istLokal ? "z. B. Meine Aufnahmen" : "z. B. morf"} /></div>
          {#if istLokal}
            <div class="col-md-6"><label class="form-label" for="n-url">Verzeichnis auf diesem Rechner</label><input class="form-control" id="n-url" bind:value={neu.basis_url} placeholder="/Users/name/Videos/morf" title="Vollständiger Pfad des Verzeichnisses; Unterordner werden mitgelesen" /><div class="form-text">Alle Video- und Audiodateien darunter, auch in Unterordnern. Ein Beiblatt name.json und ein Bild name.jpg neben der Datei werden übernommen.</div></div>
          {:else}
            <div class="col-md-3"><label class="form-label" for="n-url">Basisadresse der Quelle</label><input class="form-control" id="n-url" bind:value={neu.basis_url} title="Adresse des Dienstes samt Port, ohne Pfad" /></div>
            <div class="col-md-3"><label class="form-label" for="n-kanal">Kanalkennung</label><input class="form-control" id="n-kanal" bind:value={neu.kanal_id} placeholder="UC..." title="Kennung des Kanals, wie die Quelle sie führt (bei YouTube beginnt sie mit UC)" /></div>
          {/if}
          <div class="col-12 d-flex gap-2 align-items-center flex-wrap">
            <button class="btn btn-outline-secondary" onclick={kanalPruefen} title="Fragt die Quelle nach dem Kanal oder liest das Verzeichnis, ohne etwas zu speichern" disabled={pruefen || !neu.basis_url || (!istLokal && !neu.kanal_id)}>{#if pruefen}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if} {istLokal ? "Verzeichnis prüfen" : "Kanal prüfen"}</button>
            {#if kanal}
              {#if istLokal}
                <span class="text-success"><i class="fa-solid fa-circle-check"></i> Ordner gefunden: <b>{kanal.name}</b>, {zahl(kanal.videos_gesamt)} Dateien</span>
              {:else}
                <span class="text-success"><i class="fa-solid fa-circle-check"></i> Kanal gefunden: <b>{kanal.name}</b>, {zahl(kanal.videos_gesamt)} Videos, {zahl(kanal.videos_heruntergeladen)} heruntergeladen</span>
              {/if}
            {/if}
            <span class="ms-auto"></span>
            <button class="btn btn-primary" onclick={anlegen} disabled={beschaeftigt || !kanal || !neu.name} title="Quelle speichern; danach mit Jetzt abgleichen die Videos übernehmen">Quelle anlegen</button>
          </div>
        </div>
      </div>
    </div>

    {#if vorschau && vorschauQuelle}
      <div class="card">
        <div class="card-header fw-semibold d-flex align-items-center">Vorschau der Kanalvideos ({vorschauQuelle.name}) <button class="btn btn-sm btn-link ms-auto" onclick={() => (vorschau = null)}>schließen</button></div>
        <div class="m-tabelle-feld" style="max-height: 480px; border: 0">
          <table class="table table-sm table-hover mb-0 align-middle">
            <thead><tr><th>Titel</th><th>Datum</th><th class="text-end">Dauer</th><th>Art</th><th>{vorschauQuelle.typ === "lokal" ? "Datei" : "Heruntergeladen"}</th><th>Würde aufgenommen</th><th>Bekannt</th></tr></thead>
            <tbody>
              {#each vorschau.eintraege as e (e.extern_id)}
                <tr><td class="text-truncate" style="max-width: 520px">{e.titel}</td><td class="text-nowrap">{datum(e.veroeffentlicht)}</td><td class="text-end">{zeitmarke(e.dauer_s)}</td><td>{e.typ}</td><td>{e.heruntergeladen ? "ja" : "nein"}</td><td>{e.wuerde_aufgenommen ? "ja" : "nein"}</td><td>{e.bekannt ? "ja" : "neu"}</td></tr>
              {/each}
            </tbody>
          </table>
        </div>
        <div class="card-body py-2"><Seitenwahl bind:seite={vorschauSeite} bind:jeSeite={vorschauJeSeite} gesamt={vorschau.gesamt} auswahl={[50, 100, 200]} onWechsel={() => ladeVorschau()} /></div>
      </div>
    {/if}
  </div>
</section>

<Bestaetigung bind:offen={entfernenDialog} titel="Quelle entfernen" bestaetigen="Entfernen" gefaehrlich {beschaeftigt} onBestaetigen={entfernen}>
  <p>Die Quelle <b>{ziel?.name}</b> wird entfernt. Ihre Videos bleiben in der Bibliothek, verlieren aber den Quellbezug (kein Abgleich, keine neue Audiobeschaffung).</p>
</Bestaetigung>
