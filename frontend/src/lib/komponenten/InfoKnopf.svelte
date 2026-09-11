<script lang="ts">
  // Hilfepunkt (Mini-i): öffnet das Hilfefenster genau beim passenden Thema. Mit `finde` wird dort
  // gleich ein Begriff gesucht und markiert (Auffinden), damit man sofort an der richtigen Stelle steht.
  import { hilfe } from "../stores/hilfe.svelte";

  let { anker, finde = "", titel = "Erklärung in der Hilfe" }: { anker: string; finde?: string; titel?: string } = $props();

  function oeffnen(e: MouseEvent): void {
    e.preventDefault();
    e.stopPropagation();
    if (finde) hilfe.finde(anker, finde);
    else hilfe.zeige(anker);
  }
</script>

<button class="m-info" type="button" title={titel} aria-label={titel} onclick={oeffnen}>i</button>
