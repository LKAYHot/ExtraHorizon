<script>
  import { app } from '$lib/app.svelte.js'
  import { clock, fmt2 } from '$lib/format.js'
  import { ChevronDown, Activity, SlidersHorizontal, Zap, WandSparkles, Lock, ChartLine, FlaskConical } from '$lib/icons.js'

  let { m } = $props()
  let open = $state(true)
  let showText = $state(false)

  const a = $derived(m.adaptation)
  const simulated = $derived(a.signal.source === 'simulation')
  // an observed decrease after THIS adapted answer — shown only if it was actually measured
  const decrease = $derived(app.events.find((e) => e.kind === 'signal_decreased' && e.answer_id === m.id) ?? null)
</script>

<section class="why" class:open data-testid="why-adapted">
  <button class="toggle" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="eyebrow">Why it adapted</span>
    {#if simulated}<span class="chip sim">SIMULATED SIGNAL</span>{/if}
    <span class="grow"></span>
    <ChevronDown size={15} class="chev" />
  </button>

  {#if open}
    <dl>
      <dt><Activity size={13} /> Signal</dt>
      <dd>
        <strong>Confusion proxy <em>(estimate)</em></strong> ·
        {#if simulated}<span class="sim-text">manual Demo simulation — not live recognition</span>{:else}local camera, live{/if}
        <div class="nums num">smoothed {fmt2(a.signal.smoothed)} · raw {fmt2(a.signal.raw)} · above threshold for {a.signal.held_s.toFixed(1)} s</div>
      </dd>

      <dt><SlidersHorizontal size={13} /> Rule</dt>
      <dd class="num">EMA α {a.rule.alpha} → smoothed &gt; {a.rule.threshold} continuously ≥ {a.rule.hold_s} s · then {a.rule.cooldown_s} s cooldown</dd>

      <dt><Zap size={13} /> Decision</dt>
      <dd class="num">“Possible confusion detected” at {clock(a.event_t)} → you chose <em>Explain differently</em></dd>

      <dt><WandSparkles size={13} /> Strategy</dt>
      <dd><strong>{a.strategy.label}</strong><div class="muted">{a.strategy.description}</div></dd>

      <dt><Lock size={13} /> Sent to model</dt>
      <dd>
        Only this note + the chat text — no image, no landmarks, no numbers.
        <button class="link" onclick={() => (showText = !showText)} aria-expanded={showText}>{showText ? 'Hide' : 'Show'} exact text</button>
        {#if showText}<blockquote data-testid="instruction-text">{a.instruction}</blockquote>{/if}
      </dd>

      <dt><ChartLine size={13} /> After</dt>
      <dd>
        {#if decrease}
          <span class="obs">Confusion proxy stayed below {decrease.relief?.threshold ?? '—'} for {decrease.held_s.toFixed(1)} s at {clock(decrease.t)} (observed{decrease.source === 'simulation' ? ', simulated input' : ''}).</span>
          <div class="faint">An observation of the estimate — not proof of understanding.</div>
        {:else}
          <span class="faint">No decrease observed yet{simulated ? '' : ' — nothing is claimed until it is measured'}.</span>
        {/if}
      </dd>
    </dl>
  {/if}
</section>

<style>
  .why { margin-top: 2px; border-radius: var(--radius-sm); background: var(--well-bg); box-shadow: var(--sink); padding: 2px 12px 4px; }
  .toggle { display: flex; align-items: center; gap: 8px; width: 100%; padding: 8px 0; border: 0; background: none; color: var(--muted); }
  .toggle :global(.chev) { transition: transform var(--t2) var(--ease); }
  .why:not(.open) .toggle :global(.chev) { transform: rotate(-90deg); }
  dl { display: grid; grid-template-columns: 118px minmax(0, 1fr); gap: 8px 12px; margin: 2px 0 10px; font-size: 12.5px; }
  dt { display: flex; align-items: flex-start; gap: 6px; color: var(--faint); font-weight: 600; padding-top: 1px; }
  dt :global(svg) { flex: 0 0 auto; margin-top: 2px; }
  dd { margin: 0; color: var(--text-2); line-height: 1.5; min-width: 0; }
  dd em { font-style: normal; color: var(--muted); }
  .nums { color: var(--muted); font-size: 12px; }
  .sim-text { color: var(--warn); font-weight: 600; }
  .obs { color: #8fe0bf; }
  .link { border: 0; background: none; padding: 0; margin-left: 4px; color: var(--accent); text-decoration: underline; text-underline-offset: 3px; font-size: 12px; }
  blockquote { margin: 6px 0 0; padding: 8px 10px; border-radius: 8px; background: rgb(0 0 10 / .35); border-left: 3px solid var(--accent-2); color: var(--text-2); font-size: 12px; line-height: 1.5; }
  @media (max-width: 560px) { dl { grid-template-columns: 1fr; } }
</style>
