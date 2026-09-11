<script lang="ts">
  // Abzeichen für Stufe und Serie - eine Stelle für Farbe und Beschriftung.
  import { folge } from "../format";

  const STUFEN_TITEL: Record<string, string> = {
    entdeckt: "Entdeckt",
    importiert: "Importiert",
    audio: "Audio bereit",
    transkribiert: "Transkribiert",
    korrigiert: "Korrigiert",
    gestueckelt: "Gestückelt",
    eingebettet: "Eingebettet",
  };
  const STUFEN_ICON: Record<string, string> = {
    entdeckt: "fa-satellite-dish",
    importiert: "fa-file-import",
    audio: "fa-headphones",
    transkribiert: "fa-closed-captioning",
    korrigiert: "fa-spell-check",
    gestueckelt: "fa-scissors",
    eingebettet: "fa-cube",
  };

  let {
    stufe = "",
    serie = "",
    folgeNr = null,
    titel = "",
  }: { stufe?: string; serie?: string; folgeNr?: number | null; titel?: string } = $props();
</script>

{#if stufe}
  <span class="m-stufe {stufe}" title={titel || STUFEN_TITEL[stufe] || stufe}><i class="fa-solid {STUFEN_ICON[stufe] ?? 'fa-circle'}"></i> {titel || STUFEN_TITEL[stufe] || stufe}</span>
{:else if serie}
  <span class="m-serie" title="Serie {serie}">{folge(serie, folgeNr)}</span>
{/if}
