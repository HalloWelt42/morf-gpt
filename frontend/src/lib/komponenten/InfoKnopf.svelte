<script lang="ts">
  // Mini-i-Knopf: springt in der Hilfe genau zu einem Anker (Tiefenlink).
  import { ui } from "../stores/ui.svelte";

  let { anker, titel = "Erklärung in der Hilfe" }: { anker: string; titel?: string } = $props();
</script>

<button class="m-info" type="button" title={titel} aria-label={titel} onclick={() => ui.hilfe(anker)}>i</button>
