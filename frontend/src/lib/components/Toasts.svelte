<script>
  import { app } from '$lib/app.svelte.js'
  import { CircleCheck, CircleAlert, TriangleAlert } from '$lib/icons.js'
  const ICON = { ok: CircleCheck, warn: TriangleAlert, error: CircleAlert }
</script>

<div class="toasts" aria-live="polite">
  {#each app.toasts as t (t.id)}
    {@const Icon = ICON[t.kind] ?? CircleCheck}
    <div class="toast tone-{t.kind === 'error' ? 'error' : t.kind === 'warn' ? 'warn' : 'ok'}" role="status"><Icon size={15} /> {t.text}</div>
  {/each}
</div>

<style>
  .toasts { position: fixed; left: 50%; bottom: 20px; transform: translateX(-50%); z-index: 50; display: flex; flex-direction: column; gap: 8px; align-items: center; pointer-events: none; }
  .toast {
    display: flex; align-items: center; gap: 8px; padding: 9px 14px; border-radius: 12px; font-size: 13px; color: var(--text);
    background: rgb(14 22 44 / .92); -webkit-backdrop-filter: var(--blur); backdrop-filter: var(--blur);
    box-shadow: var(--ring-2), var(--rise-3); animation: eh-rise .35s var(--spring) both;
  }
  .toast :global(svg) { color: var(--tone); }
</style>
