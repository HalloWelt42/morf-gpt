<script lang="ts">
  // Seitenweise Navigation für lange Listen. Der Dienst gibt gesamt und je_seite vor.
  import { zahl } from "../format";

  let {
    seite = $bindable(1),
    jeSeite = $bindable(50),
    gesamt,
    auswahl = [25, 50, 100, 200],
    onWechsel,
  }: {
    seite?: number;
    jeSeite?: number;
    gesamt: number;
    auswahl?: number[];
    onWechsel: () => void;
  } = $props();

  const seiten = $derived(Math.max(1, Math.ceil(gesamt / Math.max(1, jeSeite))));
  const von = $derived(gesamt === 0 ? 0 : (seite - 1) * jeSeite + 1);
  const bis = $derived(Math.min(gesamt, seite * jeSeite));

  function gehe(z: number): void {
    const neu = Math.max(1, Math.min(seiten, z));
    if (neu === seite) return;
    seite = neu;
    onWechsel();
  }

  function groesse(e: Event): void {
    jeSeite = Number((e.target as HTMLSelectElement).value);
    seite = 1;
    onWechsel();
  }
</script>

<div class="d-flex align-items-center gap-3 flex-wrap">
  <span class="text-secondary small">{zahl(von)} bis {zahl(bis)} von {zahl(gesamt)}</span>
  <nav aria-label="Seiten">
    <ul class="pagination pagination-sm mb-0">
      <li class="page-item" class:disabled={seite <= 1}><button class="page-link" onclick={() => gehe(1)} title="Erste Seite"><i class="fa-solid fa-angles-left"></i></button></li>
      <li class="page-item" class:disabled={seite <= 1}><button class="page-link" onclick={() => gehe(seite - 1)} title="Vorige Seite"><i class="fa-solid fa-angle-left"></i></button></li>
      <li class="page-item disabled"><span class="page-link">Seite {zahl(seite)} von {zahl(seiten)}</span></li>
      <li class="page-item" class:disabled={seite >= seiten}><button class="page-link" onclick={() => gehe(seite + 1)} title="Nächste Seite"><i class="fa-solid fa-angle-right"></i></button></li>
      <li class="page-item" class:disabled={seite >= seiten}><button class="page-link" onclick={() => gehe(seiten)} title="Letzte Seite"><i class="fa-solid fa-angles-right"></i></button></li>
    </ul>
  </nav>
  <select class="form-select form-select-sm" style="width: 130px" value={jeSeite} onchange={groesse} title="Einträge je Seite">
    {#each auswahl as a}<option value={a}>{a} je Seite</option>{/each}
  </select>
</div>
