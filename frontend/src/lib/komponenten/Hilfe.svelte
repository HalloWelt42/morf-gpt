<script lang="ts">
  // Das freischwebende Hilfefenster: liegt frei über der Seite, lässt sich ziehen, in der Größe
  // ändern, minimieren und maximieren. Inhalt sind die Markdown-Themen; die Volltextsuche markiert
  // Treffer im Text und blättert bei Bedarf von Thema zu Thema. Der Zustand lebt im Store `hilfe`.
  import { untrack } from "svelte";
  import { hilfe, KOPF_HOEHE } from "../stores/hilfe.svelte";
  import { alleThemen, holeThema } from "../hilfe/themen";

  const themen = alleThemen();
  const kategorien = [...new Set(themen.map((t) => t.kategorie))];
  const thema = $derived(hilfe.thema ? holeThema(hilfe.thema) : null);
  const suchtAlle = $derived(hilfe.bereich === "alle" && hilfe.suche.trim() !== "");

  let artikel = $state<HTMLElement | null>(null);
  let textfeld = $state<HTMLDivElement | null>(null);
  let suchfeld = $state<HTMLInputElement | null>(null);

  /** In der Themenliste bei der Suche über alle Themen nur Themen mit Treffern zeigen. */
  function sichtbar(anker: string): boolean {
    return !suchtAlle || hilfe.trefferJeThema(anker) > 0;
  }

  /**
   * Treffer im gerenderten Artikel markieren und den aktiven Treffer in den Blick holen. Arbeitet
   * auf den Textknoten, damit die HTML-Struktur unangetastet bleibt; alte Markierungen werden zuvor
   * wieder aufgelöst.
   */
  function markiere(behaelter: HTMLElement, begriff: string, aktivIndex: number): void {
    behaelter.querySelectorAll("mark.tref").forEach((m) => m.replaceWith(document.createTextNode(m.textContent ?? "")));
    behaelter.normalize();
    if (!begriff) {
      if (textfeld) textfeld.scrollTop = 0;
      return;
    }
    const nadel = begriff.toLowerCase();
    const laeufer = document.createTreeWalker(behaelter, NodeFilter.SHOW_TEXT);
    const knoten: Text[] = [];
    while (laeufer.nextNode()) knoten.push(laeufer.currentNode as Text);
    let zaehler = 0;
    for (const k of knoten) {
      const text = k.nodeValue ?? "";
      const klein = text.toLowerCase();
      if (!klein.includes(nadel)) continue;
      const stueck = document.createDocumentFragment();
      let pos = 0;
      let i: number;
      while ((i = klein.indexOf(nadel, pos)) !== -1) {
        if (i > pos) stueck.appendChild(document.createTextNode(text.slice(pos, i)));
        const mark = document.createElement("mark");
        mark.className = "tref" + (zaehler === aktivIndex ? " aktiv" : "");
        mark.textContent = text.slice(i, i + begriff.length);
        stueck.appendChild(mark);
        zaehler++;
        pos = i + begriff.length;
      }
      if (pos < text.length) stueck.appendChild(document.createTextNode(text.slice(pos)));
      k.parentNode?.replaceChild(stueck, k);
    }
    behaelter.querySelector("mark.tref.aktiv")?.scrollIntoView({ block: "center" });
  }

  $effect(() => {
    // Abhängigkeiten: Thema, Suchbegriff, aktiver Treffer und die Trefferliste.
    void hilfe.thema;
    void hilfe.trefferIndex;
    void hilfe.treffer;
    const begriff = hilfe.suche.trim();
    if (!artikel) return;
    markiere(artikel, begriff, hilfe.aktivLokal());
  });

  // Sichtschutz: geraten die Bedienelemente aus dem Browserfenster (nach dem Verkleinern oder bei
  // veralteter gemerkter Lage), schaltet das Fenster auf Vollbild; dort ist immer alles erreichbar.
  function sichtSichern(): void {
    if (!hilfe.offen || hilfe.maximiert) return;
    if (!hilfe.imBild()) hilfe.maximieren();
  }

  $effect(() => {
    if (!hilfe.offen) return;
    const beiGroesse = () => sichtSichern();
    window.addEventListener("resize", beiGroesse);
    untrack(() => {
      sichtSichern();
      suchfeld?.focus();
    });
    return () => window.removeEventListener("resize", beiGroesse);
  });

  function tasteImSuchfeld(e: KeyboardEvent): void {
    if (e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey) hilfe.voriger();
      else hilfe.naechster();
    }
  }

  function tasteImFenster(e: KeyboardEvent): void {
    if (e.key !== "Escape") return;
    if (hilfe.suche) hilfe.setzeSuche("");
    else hilfe.schliessen();
  }

  // --- Verschieben (Zeiger, damit es auch mit Stift und Finger geht) ---
  function ziehBeginn(e: PointerEvent): void {
    if (hilfe.maximiert || (e.target as HTMLElement).closest("button")) return;
    e.preventDefault();
    const sx = e.clientX;
    const sy = e.clientY;
    const ox = hilfe.x;
    const oy = hilfe.y;
    const bewegen = (ev: PointerEvent) => {
      // Der Kopf mit allen Knöpfen bleibt immer im Fenster.
      const maxX = Math.max(0, window.innerWidth - hilfe.breite);
      const maxY = Math.max(0, window.innerHeight - KOPF_HOEHE);
      hilfe.setzePosition(Math.min(maxX, Math.max(0, ox + ev.clientX - sx)), Math.min(maxY, Math.max(0, oy + ev.clientY - sy)));
    };
    const ende = () => {
      hilfe.speichern();
      window.removeEventListener("pointermove", bewegen);
      window.removeEventListener("pointerup", ende);
    };
    window.addEventListener("pointermove", bewegen);
    window.addEventListener("pointerup", ende);
  }

  // --- Größe ändern ---
  function groesseBeginn(e: PointerEvent): void {
    if (hilfe.maximiert) return;
    e.preventDefault();
    e.stopPropagation();
    const sx = e.clientX;
    const sy = e.clientY;
    const ob = hilfe.breite;
    const oh = hilfe.hoehe;
    const bewegen = (ev: PointerEvent) => {
      hilfe.setzeGroesse(Math.min(ob + ev.clientX - sx, window.innerWidth - hilfe.x), Math.min(oh + ev.clientY - sy, window.innerHeight - hilfe.y));
    };
    const ende = () => {
      hilfe.speichern();
      window.removeEventListener("pointermove", bewegen);
      window.removeEventListener("pointerup", ende);
    };
    window.addEventListener("pointermove", bewegen);
    window.addEventListener("pointerup", ende);
  }

  const stil = $derived(hilfe.maximiert ? "" : `left: ${hilfe.x}px; top: ${hilfe.y}px; width: ${hilfe.breite}px; height: ${hilfe.minimiert ? "auto" : `${hilfe.hoehe}px`};`);
</script>

{#if hilfe.offen}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <section class="m-hilfe" class:minimiert={hilfe.minimiert} class:maximiert={hilfe.maximiert} style={stil} role="dialog" aria-label="Hilfe" onkeydown={tasteImFenster}>
    <!-- svelte-ignore a11y_no_static_element_interactions -->
    <header class="m-hilfe-kopf" onpointerdown={ziehBeginn}>
      <i class="fa-solid {thema?.symbol ?? 'fa-circle-question'}"></i>
      <div class="m-hilfe-titel">
        <b>{thema?.titel ?? "Hilfe"}</b>
        {#if thema?.unterzeile}<span>{thema.unterzeile}</span>{/if}
      </div>
      <div class="m-hilfe-aktionen">
        <button class="btn btn-sm btn-light" type="button" title={hilfe.minimiert ? "Wiederherstellen" : "Minimieren"} onclick={() => hilfe.minimierenUmschalten()}><i class="fa-solid {hilfe.minimiert ? 'fa-window-restore' : 'fa-window-minimize'}"></i></button>
        <button class="btn btn-sm btn-light" type="button" title={hilfe.maximiert ? "Vollbild verlassen" : "Maximieren"} onclick={() => hilfe.maximierenUmschalten()}><i class="fa-solid {hilfe.maximiert ? 'fa-compress' : 'fa-expand'}"></i></button>
        <button class="btn btn-sm btn-light" type="button" title="Schließen" onclick={() => hilfe.schliessen()}><i class="fa-solid fa-xmark"></i></button>
      </div>
    </header>

    {#if !hilfe.minimiert}
      <div class="m-hilfe-leiste">
        <div class="btn-group btn-group-sm" role="group" aria-label="Suchbereich">
          <button class="btn btn-outline-secondary" type="button" class:active={hilfe.bereich === "alle"} title="In allen Themen suchen" onclick={() => hilfe.setzeBereich("alle")}>Alle Themen</button>
          <button class="btn btn-outline-secondary" type="button" class:active={hilfe.bereich === "thema"} title="Nur in diesem Thema suchen" onclick={() => hilfe.setzeBereich("thema")}>Dieses Thema</button>
        </div>
        <div class="m-hilfe-suchfeld">
          <i class="fa-solid fa-magnifying-glass text-secondary"></i>
          <input bind:this={suchfeld} placeholder={hilfe.bereich === "alle" ? "In allen Themen suchen ..." : "In diesem Thema suchen ..."} value={hilfe.suche} oninput={(e) => hilfe.setzeSuche(e.currentTarget.value)} onkeydown={tasteImSuchfeld} aria-label="Hilfe durchsuchen" title="Volltextsuche; Eingabe springt zum nächsten Treffer, Umschalt + Eingabe zurück, Escape leert" />
          {#if hilfe.suche.trim()}
            <span class="zaehler">{hilfe.trefferGesamt ? hilfe.trefferIndex + 1 : 0}/{hilfe.trefferGesamt}</span>
            <button class="btn btn-sm btn-link p-0" type="button" title="Vorheriger Treffer (Umschalt + Eingabe)" onclick={() => hilfe.voriger()}><i class="fa-solid fa-chevron-up"></i></button>
            <button class="btn btn-sm btn-link p-0" type="button" title="Nächster Treffer (Eingabe)" onclick={() => hilfe.naechster()}><i class="fa-solid fa-chevron-down"></i></button>
            <button class="btn btn-sm btn-link p-0" type="button" title="Suche leeren (Escape)" onclick={() => hilfe.setzeSuche("")}><i class="fa-solid fa-xmark"></i></button>
          {/if}
        </div>
      </div>
      {#if suchtAlle && thema}
        <div class="m-hilfe-hinweis">{hilfe.trefferGesamt ? `Treffer in ${thema.titel}; mit den Pfeilen geht es durch alle Themen.` : "Kein Thema enthält diesen Begriff."}</div>
      {/if}

      <div class="m-hilfe-koerper">
        <nav class="m-hilfe-inhalt" aria-label="Themen">
          {#each kategorien as k (k)}
            {#if themen.some((t) => t.kategorie === k && sichtbar(t.anker))}
              <div class="px-3 pt-2 pb-1 small text-uppercase text-secondary fw-semibold">{k}</div>
              {#each themen.filter((t) => t.kategorie === k && sichtbar(t.anker)) as t (t.anker)}
                <a href="#hilfe-{t.anker}" class:aktiv={t.anker === hilfe.thema} onclick={(e) => { e.preventDefault(); hilfe.waehle(t.anker); }}>
                  <span class="text-truncate">{t.titel}</span>
                  {#if suchtAlle}<span class="badge text-bg-secondary">{hilfe.trefferJeThema(t.anker)}</span>{/if}
                </a>
              {/each}
            {/if}
          {/each}
        </nav>
        <div class="m-hilfe-text" bind:this={textfeld}>
          {#if thema}
            {#key hilfe.thema}
              <!-- Eigene, fest mitgelieferte Markdown-Themen (kein Nutzertext), durch DOMPurify geführt. -->
              <article class="m-hilfe-artikel" bind:this={artikel}>{@html thema.html}</article>
            {/key}
          {:else}
            <p class="text-secondary">Kein Thema gewählt.</p>
          {/if}
        </div>
      </div>
      {#if !hilfe.maximiert}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div class="m-hilfe-griff" title="Größe ändern" onpointerdown={groesseBeginn}></div>
      {/if}
    {/if}
  </section>
{/if}
