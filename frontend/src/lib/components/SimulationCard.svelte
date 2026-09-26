<script>
  import { app } from '$lib/app.svelte.js'
  import { COLOR, LABEL, SIM_PRESETS } from '$lib/emotions.js'
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
      Pick an expression by hand instead of the camera — for showing the interface without a working camera.
      It drives the <strong>same</strong> emotion engine and prompt note, and everything it produces is labelled
      <strong>SIMULATED</strong>. It is never live recognition.
    </p>
    <label class="toggle">
      <span class="switch">
        <input type="checkbox" checked={on} onchange={(e) => app.setSimulation(e.currentTarget.checked)} data-testid="sim-toggle" />
        <span class="track"></span><span class="knob"></span>
      </span>
      Use a simulated expression
    </label>
    {#if on}
      <div class="grid" role="radiogroup" aria-label="Simulated expression">
        {#each SIM_PRESETS as k (k)}
          <button class="btn sm pick" class:sel={app.sim.emotion === k} role="radio" aria-checked={app.sim.emotion === k}
                  onclick={() => app.setSimEmotion(k)} data-testid="sim-{k}">
            <i style:background={COLOR[k]}></i>{LABEL[k]}
          </button>
        {/each}
      </div>
      <div class="slider">
        <span class="faint">intensity</span>
        <input type="range" min="0.2" max="1" step="0.05" bind:value={app.sim.intensity} aria-label="Simulated intensity" data-testid="sim-intensity" />
        <span class="num val">{Math.round(Number(app.sim.intensity) * 100)}%</span>
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
  .grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
  .pick { justify-content: flex-start; }
  .pick i { width: 9px; height: 9px; border-radius: 3px; flex: 0 0 auto; }
  .pick.sel { color: var(--text); border-color: var(--edge-2); box-shadow: 0 0 0 1px rgb(232 184 95 / .6), var(--rise-1); }
  .slider { display: flex; align-items: center; gap: 10px; margin: 10px 0 12px; font-size: 12px; }
  .val { width: 38px; text-align: right; font-size: 12.5px; color: var(--text); }
</style>
