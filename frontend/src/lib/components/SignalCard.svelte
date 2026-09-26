<script>
  import { app } from '$lib/app.svelte.js'
  import { ago, fmt2, reasonText } from '$lib/format.js'
  import { Activity, TriangleAlert, Clock } from '$lib/icons.js'

  let now = $state(Date.now())
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 1000)
    return () => clearInterval(t)
  })

  const e = $derived(app.engine)
  const cfg = $derived(app.vision.config)
  const known = $derived(e?.status === 'ok' && e.smoothed != null)
  const simulated = $derived(e?.source === 'simulation')
  const pct = $derived(known ? Math.round(e.smoothed * 1000) / 10 : 0)
  const holdPct = $derived(known && e.held_s > 0 ? Math.min(100, (e.held_s / e.hold_s) * 100) : 0)
  const ev = $derived(app.latestConfusion)
  const flash = $derived(now - app.lastEventAt < 2500)

  const EVENT_STATUS = {
    offered: 'offered below the answer',
    used: 'used — answer adapted',
    expired: 'expired (a new question was asked)',
    unattached: 'no answer to adapt yet — ask a question first',
  }
</script>

<section class="card spot sig" class:flash data-testid="signal-card">
  <div class="top">
    <div class="eyebrow"><Activity size={13} /> Confusion proxy <em>estimate</em></div>
    {#if simulated}<span class="chip sim" data-testid="sim-badge">SIMULATION</span>{:else if e}<span class="chip">camera</span>{/if}
  </div>

  <div class="value-row">
    {#if known}
      <span class="value" data-testid="signal-value">{fmt2(e.smoothed)}</span>
      <span class="raw faint num">raw {fmt2(e.raw)}</span>
    {:else}
      <span class="value unknown" data-testid="signal-value">—</span>
      <span class="reason">{e ? reasonText(e.reason) : app.vision.socket !== 'open' && app.vision.socket !== 'superseded' ? 'Reconnecting to the vision backend…' : 'No signal yet'}</span>
    {/if}
  </div>

  <div class="meter" role="meter" aria-valuemin="0" aria-valuemax="1" aria-valuenow={known ? e.smoothed : undefined}
       aria-label="Smoothed confusion proxy (estimate)" aria-valuetext={known ? fmt2(e.smoothed) : 'unknown'}>
    <div class="fill" class:above={known && e.above} style:width="{pct}%"></div>
    <div class="thr" style:left="{cfg.threshold * 100}%" title="threshold {cfg.threshold}"></div>
  </div>
  <div class="scale faint num"><span>0</span><span style:left="{cfg.threshold * 100}%">threshold {cfg.threshold}</span><span>1</span></div>

  <div class="state">
    {#if e && e.armed === false && known && e.above && !(e.cooldown_left_s > 0)}
      <span class="faint">event already raised for this episode — waiting for the signal to drop or a new answer</span>
    {:else if e?.cooldown_left_s > 0}
      <span class="chip"><Clock size={12} /> cooldown {Math.ceil(e.cooldown_left_s)} s</span>
    {:else if known && e.above}
      <span class="hold"><span class="bar"><i style:width="{holdPct}%"></i></span><span class="num">above threshold {e.held_s.toFixed(1)} / {e.hold_s} s</span></span>
    {:else if known}
      <span class="faint">below threshold — no event</span>
    {:else}
      <span class="faint">unknown — hold timer reset</span>
    {/if}
  </div>

  {#if ev}
    <div class="event" class:fresh={flash} data-testid="event-card">
      <TriangleAlert size={14} />
      <div>
        <strong>{ev.label}</strong> <span class="faint">· {ago(ev.t, now)}</span>
        {#if ev.source === 'simulation'}<span class="chip sim">SIMULATED</span>{/if}
        <div class="faint small">{EVENT_STATUS[ev.status] ?? ev.status}</div>
      </div>
    </div>
  {/if}
</section>

<style>
  .sig { padding: 12px 14px; display: flex; flex-direction: column; gap: 8px; transition: box-shadow .6s var(--ease), --spot-a var(--t3) var(--ease); }
  .sig.flash { box-shadow: 0 0 0 1px rgb(217 89 38 / .6), 0 18px 40px -18px rgb(217 89 38 / .55); }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .eyebrow em { font-style: italic; text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--muted); }
  .value-row { display: flex; align-items: baseline; gap: 10px; min-height: 40px; }
  .value { font: 650 34px/1 var(--font-display); letter-spacing: -.02em; color: var(--text); }
  .value.unknown { color: var(--faint); }
  .raw { font-size: 12px; }
  .reason { font-size: 12.5px; color: var(--warn); }
  .meter { position: relative; height: 10px; border-radius: 999px; background: color-mix(in srgb, var(--viz-signal) 16%, var(--well)); box-shadow: var(--sink); }
  .fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; background: var(--viz-signal); transition: width .25s linear, background-color .3s var(--ease); }
  .fill.above { background: var(--viz-event); }
  .thr { position: absolute; top: -4px; bottom: -4px; width: 2px; margin-left: -1px; border-radius: 1px; background: var(--text-2); box-shadow: 0 0 0 2px var(--plane); }
  .scale { position: relative; height: 14px; font-size: 10.5px; }
  .scale span { position: absolute; top: 0; }
  .scale span:first-child { left: 0; }
  .scale span:nth-child(2) { transform: translateX(-50%); white-space: nowrap; }
  .scale span:last-child { right: 0; }
  .state { font-size: 12px; min-height: 22px; display: flex; align-items: center; }
  .hold { display: flex; align-items: center; gap: 8px; color: #f3a57f; width: 100%; }
  .hold .bar { flex: 0 0 90px; height: 4px; border-radius: 999px; background: var(--well); box-shadow: var(--sink); overflow: hidden; }
  .hold i { display: block; height: 100%; background: var(--viz-event); border-radius: inherit; }
  .event { display: flex; gap: 8px; align-items: flex-start; padding: 9px 10px; border-radius: var(--radius-sm); background: rgb(217 89 38 / .09); box-shadow: 0 0 0 1px rgb(217 89 38 / .3); font-size: 12.5px; }
  .event :global(svg) { flex: 0 0 auto; color: #f08a5d; margin-top: 2px; }
  .event.fresh { animation: eh-pop .5s var(--spring) both; }
  .small { font-size: 11.5px; margin-top: 2px; }
</style>
