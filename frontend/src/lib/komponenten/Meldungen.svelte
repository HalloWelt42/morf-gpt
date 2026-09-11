<script lang="ts">
  import { meldungen } from "../stores/meldungen.svelte";
</script>

{#if meldungen.liste.length}
  <div class="m-meldungen" aria-live="polite">
    {#each meldungen.liste as m (m.id)}
      <div class="m-meldung {m.art}" role="status">
        <div class="d-flex align-items-start gap-2">
          <i class="fa-solid {m.art === 'fehler' ? 'fa-triangle-exclamation text-danger' : m.art === 'gut' ? 'fa-circle-check text-success' : 'fa-circle-info text-primary'} mt-1"></i>
          <div class="flex-grow-1">{m.text}</div>
          <button class="btn btn-sm btn-link text-secondary p-0" title="Schließen" onclick={() => meldungen.entferne(m.id)}><i class="fa-solid fa-xmark"></i></button>
        </div>
      </div>
    {/each}
  </div>
{/if}
