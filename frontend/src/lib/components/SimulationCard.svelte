<script>
  import { app } from '$lib/app.svelte.js'
  import { ChevronDown, FlaskConical } from '$lib/icons.js'

  let open = $state(false)
  const on = $derived(app.sim.enabled)
  $effect(() => {
    if (on) open = true
  })
</script>

<section class="card sim-card" class:on data-testid="simulation-card">
  <button class="head" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="eyebrow"><FlaskConical size={13} /> Demo simulation mode</span>
    {#if on}<span class="chip sim">ON · NOT LIVE</span>{/if}
    <ChevronDown size={15} class="chev" />
  </button>
  {#if open}
    <p class="warn-text">
      A manual slider replaces the camera signal so the interface can be shown without a working camera.
      It drives the <strong>same</strong> state engine, and everything it produces is labelled <strong>SIMULATED</strong>.
      It is never live recognition.
    </p>
    <label class="toggle">
      <span class="switch">
        <input type="checkbox" checked={on} onchange={(e) => app.setSimulation(e.currentTarget.checked)} data-testid="sim-toggle" />
        <span class="track"></span><span class="knob"></span>
      </span>
      Use simulated signal
    </label>
    {#if on}
      <div class="slider">
        <input type="range" min="0" max="1" step="0.01" bind:value={app.sim.value} aria-label="Simulated confusion proxy" data-testid="sim-slider" />
        <span class="num val">{Number(app.sim.value).toFixed(2)}</span>
      </div>
      <div class="presets">
        <button class="btn sm" onclick={() => (app.sim.value = 0.1)} data-testid="sim-low">Low 0.10</button>
        <button class="btn sm" onclick={() => (app.sim.value = 0.9)} data-testid="sim-high">High 0.90</button>
      </div>
    {/if}
  {/if}
</section>

<style>
  .sim-card { padding: 4px 12px; }
  .sim-card.on { box-shadow: 0 0 0 1px rgb(232 184 95 / .5), var(--rise-1); background: repeating-linear-gradient(135deg, rgb(232 184 95 / .05) 0 8px, transparent 8px 16px), var(--sheen), var(--plane); }
  .head { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 0; border: 0; background: none; color: var(--muted); text-align: left; }
  .head .eyebrow { flex: 1 1 auto; }
  .head :global(.chev) { transition: transform var(--t2) var(--ease); }
  .head[aria-expanded='false'] :global(.chev) { transform: rotate(-90deg); }
  .warn-text { margin: 0 0 10px; font-size: 12px; line-height: 1.5; color: #f2d7a8; }
  .warn-text strong { color: #ffe7c2; }
  .toggle { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--text-2); cursor: pointer; margin-bottom: 10px; }
  .slider { display: flex; align-items: center; gap: 10px; }
  .val { width: 34px; text-align: right; font-size: 12.5px; color: var(--text); }
  .presets { display: flex; gap: 6px; margin: 8px 0 12px; }
</style>
