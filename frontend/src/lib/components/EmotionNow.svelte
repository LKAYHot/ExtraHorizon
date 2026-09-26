<script>
  import { app } from '$lib/app.svelte.js'
  import { reasonText } from '$lib/format.js'
  import { COLOR, LABEL, ROWS, arousalWord, seconds, strengthWord, valenceWord } from '$lib/emotions.js'
  import { Activity, RefreshCw } from '$lib/icons.js'

  const v = app.vision
  const LEVELS = [
    ['calm', 'Calm', 'Only clear, sustained expressions are reported'],
    ['balanced', 'Balanced', 'Default'],
    ['expressive', 'Expressive', 'Reacts to subtler expressions'],
  ]
  const e = $derived(app.emotion)
  const known = $derived(e?.status === 'ok' && !!e.probs)
  const simulated = $derived(e?.source === 'simulation')
  const calibrating = $derived(e?.status === 'calibrating') // a face is there and being learned
  const dom = $derived(known ? e.dominant : null)
  const mood = $derived(known ? [valenceWord(e.valence), arousalWord(e.arousal)].filter(Boolean).join(' · ') : '')
  const sub = $derived(
    dom
      ? [dom === 'neutral' ? 'relaxed' : strengthWord(e.dominant_prob),
         e.dominant_for_s < 1 ? 'just now' : `for ${seconds(e.dominant_for_s)}`, mood].filter(Boolean).join(' · ')
      : '',
  )
  const rows = $derived(ROWS.map((k) => ({ k, p: known ? (e.probs[k] ?? 0) : null })))
  const why = $derived.by(() => {
    if (e) return reasonText(e.reason)
    if (v.socket !== 'open' && v.socket !== 'superseded') return 'Connecting to the vision backend…'
    if (v.camera !== 'active' && !app.sim.enabled) return 'Camera is off'
    return 'Waiting for a reading…'
  })
</script>

<section class="card spot now" data-testid="emotion-now">
  <div class="top">
    <div class="eyebrow"><Activity size={13} /> Expression now <em>estimate</em></div>
    {#if simulated}<span class="chip sim" data-testid="sim-badge">SIMULATION</span>{:else if known}<span class="chip">camera · calibrated</span>{/if}
  </div>

  <div class="hero">
    {#if calibrating && !simulated}
      <span class="swatch cal"></span>
      <div class="hero-text grow">
        <span class="value unknown" data-testid="emotion-dominant" data-emotion="">Calibrating…</span>
        <span class="sub">Look at the screen with a relaxed face — learning <em>your</em> neutral expression</span>
        <span class="progress"><i style:width="{Math.round((v.calibration?.progress ?? 0) * 100)}%"></i></span>
      </div>
    {:else if dom}
      <span class="swatch" style:background={COLOR[dom]}></span>
      <div class="hero-text">
        <span class="value" data-testid="emotion-dominant" data-emotion={dom}>{LABEL[dom]}</span>
        <span class="sub">{sub}</span>
      </div>
    {:else}
      <span class="swatch empty"></span>
      <div class="hero-text">
        <span class="value unknown" data-testid="emotion-dominant" data-emotion="">Unknown</span>
        <span class="sub warn">{why}</span>
      </div>
    {/if}
  </div>

  <ul class="bars" aria-label="Smoothed probability of each expression (after calibration)">
    {#each rows as r (r.k)}
      <li class:dom={r.k === dom} class:off={r.p == null}>
        <span class="label">{LABEL[r.k]}</span>
        <span class="track"><i style:width="{(r.p ?? 0) * 100}%" style:background={COLOR[r.k]}></i></span>
        <span class="pct num">{r.p == null ? '—' : `${Math.round(r.p * 100)}%`}</span>
      </li>
    {/each}
  </ul>

  <div class="controls">
    <div class="seg" role="radiogroup" aria-label="Sensitivity">
      {#each LEVELS as [key, label, hint] (key)}
        <button role="radio" aria-checked={v.sensitivity === key} class:sel={v.sensitivity === key} title={hint}
                onclick={() => v.setSensitivity(key)} data-testid="sensitivity-{key}">{label}</button>
      {/each}
    </div>
    <button class="btn sm ghost" onclick={() => v.recalibrate()} disabled={v.camera !== 'active' || app.sim.enabled}
            title="Learn your relaxed face again (~3 s)"><RefreshCw size={12} /> Recalibrate</button>
  </div>
</section>

<style>
  .now { padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .eyebrow em { font-style: italic; text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--muted); }
  .hero { display: flex; align-items: center; gap: 12px; min-height: 48px; }
  .swatch { width: 14px; height: 40px; border-radius: 5px; flex: 0 0 auto; box-shadow: 0 0 0 2px var(--viz-surface), 0 8px 20px -8px rgb(0 0 10 / .8); transition: background var(--t3) var(--ease); }
  .swatch.empty { background: repeating-linear-gradient(135deg, var(--line-2) 0 4px, transparent 4px 8px); }
  .swatch.cal { background: repeating-linear-gradient(135deg, rgb(165 139 255 / .6) 0 4px, transparent 4px 8px); }
  .hero-text { display: flex; flex-direction: column; min-width: 0; gap: 2px; }
  .value { font: 650 28px/1.05 var(--font-display); letter-spacing: -.02em; color: var(--text); }
  .value.unknown { color: var(--faint); }
  .sub { font-size: 12px; color: var(--muted); }
  .sub em { font-style: italic; color: var(--text-2); }
  .sub.warn { color: var(--warn); }
  .progress { display: block; height: 4px; border-radius: 999px; background: var(--well); box-shadow: var(--sink); overflow: hidden; margin-top: 4px; }
  .progress i { display: block; height: 100%; background: #a58bff; border-radius: inherit; transition: width .2s linear; }
  .bars { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 5px; }
  .bars li { display: grid; grid-template-columns: 82px 1fr 38px; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); }
  .bars li.dom { color: var(--text); font-weight: 650; }
  .bars li.off { opacity: .55; }
  .track { position: relative; height: 8px; border-radius: 4px; background: var(--well); box-shadow: var(--sink); overflow: hidden; }
  .track i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 0 4px 4px 0; transition: width .18s linear; }
  .pct { text-align: right; color: var(--text-2); }
  .controls { display: flex; align-items: center; justify-content: space-between; gap: 8px; flex-wrap: wrap; }
  .seg { display: inline-flex; padding: 2px; border-radius: 9px; background: var(--well-bg); box-shadow: var(--sink); }
  .seg button {
    height: 24px; padding: 0 9px; border: 0; border-radius: 7px; background: transparent; color: var(--muted);
    font-size: 11.5px; font-weight: 600; transition: background var(--t2) var(--ease), color var(--t2) var(--ease);
  }
  .seg button:hover { color: var(--text-2); }
  .seg button.sel { background: var(--sheen), var(--raise-hi); color: var(--text); box-shadow: var(--ring-2), var(--rise-1); }
</style>
