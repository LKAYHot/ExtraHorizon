<script>
  import { app } from '$lib/app.svelte.js'
  import { ago } from '$lib/format.js'
  import { Repeat, TriangleAlert, X } from '$lib/icons.js'

  let { message } = $props()

  let now = $state(Date.now())
  let countdown = $state(null) // seconds left for auto-adapt
  let cancelledFor = $state(null)

  const offer = $derived(app.offer && app.offer.answerId === message.id ? app.offer : null)
  const cfg = $derived(app.vision.config)
  const visible = $derived(message.status === 'done' && !app.busy)

  $effect(() => {
    if (!offer) return
    const t = setInterval(() => (now = Date.now()), 1000)
    return () => clearInterval(t)
  })

  // optional auto-adapt (off by default): visible, cancellable 3 s countdown
  $effect(() => {
    const id = offer?.event.id
    if (!id || !app.autoAdapt || cancelledFor === id) {
      countdown = null
      return
    }
    countdown = 3
    const t = setInterval(() => {
      countdown -= 1
      if (countdown <= 0) {
        clearInterval(t)
        countdown = null
        app.explainDifferently(id)
      }
    }, 1000)
    return () => clearInterval(t)
  })
</script>

{#if visible}
  <div class="offer" class:active={!!offer} data-testid="offer">
    {#if offer}
      <div class="signal">
        <TriangleAlert size={14} />
        <span><strong>Possible confusion detected</strong> · {ago(offer.event.t, now)}
          {#if offer.event.source === 'simulation'}<span class="chip sim">SIMULATED</span>{/if}</span>
      </div>
      <div class="actions">
        {#if countdown != null}
          <span class="count num">Auto-adapting in {countdown}s</span>
          <button class="btn sm ghost" onclick={() => (cancelledFor = offer.event.id)}><X size={13} /> Cancel</button>
        {/if}
        <button class="btn primary go" onclick={() => app.explainDifferently(offer.event.id)} data-testid="explain-differently">
          <Repeat size={15} /> Explain differently
        </button>
      </div>
    {:else}
      <button class="btn" disabled title="Becomes active after a detected event" data-testid="explain-differently-disabled">
        <Repeat size={15} /> Explain differently
      </button>
      <span class="hint">Activates when the confusion proxy stays above {cfg.threshold} for {cfg.hold_s} s (or in labelled simulation mode).</span>
    {/if}
  </div>
{/if}

<style>
  .offer {
    display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; margin: -4px 0 4px 37px;
    animation: eh-fade .3s var(--ease) both;
  }
  .hint { font-size: 12px; color: var(--faint); }
  .offer.active {
    justify-content: space-between; padding: 10px 12px; border-radius: var(--radius-sm);
    background: linear-gradient(180deg, rgb(217 89 38 / .12), rgb(165 139 255 / .08));
    box-shadow: 0 0 0 1px rgb(217 89 38 / .45), 0 16px 34px -20px rgb(217 89 38 / .6);
    animation: eh-rise .45s var(--spring) both;
  }
  .signal { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); }
  .signal :global(svg) { color: #f08a5d; }
  .actions { display: flex; align-items: center; gap: 8px; }
  .count { font-size: 12px; color: var(--warn); }
  .go { height: 36px; }
  @media (max-width: 859px) { .offer { margin-left: 0; } }
</style>
