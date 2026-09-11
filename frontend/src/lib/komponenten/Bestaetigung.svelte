<script lang="ts">
  // Eigener Bestätigungsdialog (kein Browser-Dialog). Große Schrift über .modal-content.
  import type { Snippet } from "svelte";

  let {
    offen = $bindable(false),
    titel,
    bestaetigen = "Bestätigen",
    abbrechen = "Abbrechen",
    gefaehrlich = false,
    beschaeftigt = false,
    onBestaetigen,
    children,
  }: {
    offen?: boolean;
    titel: string;
    bestaetigen?: string;
    abbrechen?: string;
    gefaehrlich?: boolean;
    beschaeftigt?: boolean;
    onBestaetigen: () => void | Promise<void>;
    children?: Snippet;
  } = $props();

  function schliessen(): void {
    if (!beschaeftigt) offen = false;
  }

  function taste(e: KeyboardEvent): void {
    if (e.key === "Escape") schliessen();
  }
</script>

<svelte:window onkeydown={offen ? taste : undefined} />

{#if offen}
  <div class="modal d-block" tabindex="-1" role="dialog" aria-modal="true" aria-labelledby="dialog-titel">
    <div class="modal-dialog modal-dialog-centered">
      <div class="modal-content">
        <div class="modal-header">
          <h5 class="modal-title" id="dialog-titel">{titel}</h5>
          <button type="button" class="btn-close" aria-label="Schließen" onclick={schliessen}></button>
        </div>
        <div class="modal-body">
          {#if children}{@render children()}{/if}
        </div>
        <div class="modal-footer">
          <button type="button" class="btn btn-outline-secondary" onclick={schliessen} disabled={beschaeftigt}>{abbrechen}</button>
          <button type="button" class="btn {gefaehrlich ? 'btn-danger' : 'btn-primary'}" onclick={onBestaetigen} disabled={beschaeftigt}>
            {#if beschaeftigt}<i class="fa-solid fa-circle-notch fa-spin"></i>{/if}
            {bestaetigen}
          </button>
        </div>
      </div>
    </div>
  </div>
  <div class="modal-backdrop show"></div>
{/if}
