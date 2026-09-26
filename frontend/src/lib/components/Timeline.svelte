<script>
  import { app } from '$lib/app.svelte.js'
  import { clock, fmt2, reasonText } from '$lib/format.js'
  import { ChartLine, Table2 } from '$lib/icons.js'

  const WINDOW = 60_000
  const H = 156
  const M = { l: 30, r: 34, t: 18, b: 22 }
  const MARK = {
    answer: 'Answer',
    adapted: 'Adapted answer',
    event: 'Possible confusion detected',
    decrease: 'Decrease observed',
  }

  let width = $state(340)
  let now = $state(Date.now())
  let cursor = $state(null) // index into view.samples
  let table = $state(false)

  // the time axis follows the data (rAF-coalesced) and keeps moving at least twice a second
  $effect(() => {
    void app.timelineVersion
    const id = requestAnimationFrame(() => (now = Date.now()))
    return () => cancelAnimationFrame(id)
  })
  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 500)
    return () => clearInterval(t)
  })

  const pw = $derived(Math.max(60, width - M.l - M.r))
  const ph = H - M.t - M.b
  const thr = $derived(app.vision.config.threshold ?? 0.65)
  const x = (t) => M.l + ((t - (now - WINDOW)) / WINDOW) * pw
  const y = (v) => M.t + (1 - v) * ph

  const view = $derived.by(() => {
    void app.timelineVersion
    const t0 = now - WINDOW
    const samples = app.timeline.samples.filter((s) => s[0] >= t0 - 1000)
    const segments = []
    const rugs = []
    let seg = null
    let rug = null
    let prevT = null
    for (const s of samples) {
      const [t, , sm, status, source] = s
      const gap = prevT !== null && t - prevT > 1500
      prevT = t
      const xt = Math.max(M.l, x(t))
      if (sm == null || status !== 'ok') {
        seg = null
        if (!rug || gap) rugs.push((rug = { x0: xt, x1: xt }))
        else rug.x1 = xt
        continue
      }
      rug = null
      const sim = source === 'simulation'
      if (!seg || gap || seg.sim !== sim) segments.push((seg = { sim, pts: [] }))
      seg.pts.push([xt, y(sm)])
    }
    const paths = segments.map((sg) => ({
      sim: sg.sim,
      d: sg.pts.map((p, i) => `${i ? 'L' : 'M'}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(''),
      dot: sg.pts.length === 1 ? sg.pts[0] : null,
    }))
    const markers = app.timeline.markers.filter((m) => m.t >= t0).map((m) => ({ ...m, x: x(m.t) }))
    const last = samples.at(-1)
    const lastKnown = last && last[2] != null && last[3] === 'ok' ? { x: x(last[0]), y: y(last[2]), v: last[2] } : null
    return { samples, paths, rugs, markers, lastKnown }
  })

  const hover = $derived(cursor != null ? view.samples[Math.min(cursor, view.samples.length - 1)] ?? null : null)
  const hoverMarker = $derived.by(() => {
    if (!hover) return null
    const hx = x(hover[0])
    let best = null
    for (const m of view.markers) if (Math.abs(m.x - hx) < 7 && (!best || Math.abs(m.x - hx) < Math.abs(best.x - hx))) best = m
    return best
  })

  function nearestIndex(px) {
    const s = view.samples
    if (!s.length) return null
    const t = now - WINDOW + ((px - M.l) / pw) * WINDOW
    let lo = 0
    let hi = s.length - 1
    while (lo < hi) {
      const mid = (lo + hi) >> 1
      if (s[mid][0] < t) lo = mid + 1
      else hi = mid
    }
    if (lo > 0 && Math.abs(s[lo - 1][0] - t) < Math.abs(s[lo][0] - t)) lo--
    return lo
  }

  function onMove(e) {
    const r = e.currentTarget.getBoundingClientRect()
    cursor = nearestIndex(e.clientX - r.left)
  }

  function onKey(e) {
    const n = view.samples.length
    if (!n) return
    if (e.key === 'ArrowLeft') cursor = Math.max(0, (cursor ?? n) - 1)
    else if (e.key === 'ArrowRight') cursor = Math.min(n - 1, (cursor ?? n - 2) + 1)
    else if (e.key === 'Escape') cursor = null
    else return
    e.preventDefault()
  }

  const tableRows = $derived.by(() => {
    if (!table) return []
    const rows = view.markers.map((m) => ({ t: m.t, what: MARK[m.kind] ?? m.label, value: '' }))
    const recent = view.samples.slice(-8).map((s) => ({
      t: s[0],
      what: s[3] === 'ok' ? `signal (${s[4]})` : `unknown`,
      value: s[3] === 'ok' ? fmt2(s[2]) : s[3],
    }))
    return [...rows, ...recent].sort((a, b) => b.t - a.t)
  })
</script>

<section class="card spot tl" data-testid="timeline">
  <div class="top">
    <div class="eyebrow"><ChartLine size={13} /> Timeline · last 60 s</div>
    <button class="btn sm ghost icon" class:on={table} onclick={() => (table = !table)} aria-pressed={table} title="Table view" aria-label="Toggle table view"><Table2 size={14} /></button>
  </div>
  <div class="subtitle">Smoothed confusion proxy <em>(estimate)</em> — measured values only; gaps = unknown</div>

  {#if table}
    <table class="data">
      <thead><tr><th>time</th><th>what</th><th>value</th></tr></thead>
      <tbody>
        {#each tableRows as r, i (i)}
          <tr><td class="num">{clock(r.t)}</td><td>{r.what}</td><td class="num">{r.value}</td></tr>
        {:else}
          <tr><td colspan="3" class="faint">No measurements yet.</td></tr>
        {/each}
      </tbody>
    </table>
  {:else}
    <div class="plot" bind:clientWidth={width}>
      <svg width={width} height={H} role="img" aria-label="Timeline of the smoothed confusion proxy over the last 60 seconds">
        <!-- grid: solid hairlines -->
        {#each [0, 0.5, 1] as g (g)}
          <line class="grid" x1={M.l} x2={M.l + pw} y1={y(g)} y2={y(g)} />
          <text class="tick" x={M.l - 6} y={y(g) + 3.5} text-anchor="end">{g}</text>
        {/each}
        {#each [60, 45, 30, 15] as s (s)}
          <text class="tick" x={M.l + ((WINDOW - s * 1000) / WINDOW) * pw} y={H - 6} text-anchor="middle">−{s}s</text>
        {/each}
        <text class="tick" x={M.l + pw} y={H - 6} text-anchor="middle">now</text>

        <!-- threshold (a real threshold → dashed) -->
        <line class="thr" x1={M.l} x2={M.l + pw} y1={y(thr)} y2={y(thr)} />
        <text class="thr-label" x={M.l + pw + 4} y={y(thr) + 3.5}>{thr}</text>

        <!-- unknown periods: a rug under the plot, never plotted as zero -->
        {#each view.rugs as r, i (i)}
          <rect class="rug" x={r.x0} y={M.t + ph + 3} width={Math.max(2, r.x1 - r.x0)} height="3" rx="1.5" />
        {/each}

        <!-- chat / engine markers -->
        {#each view.markers as m (m.t + m.kind + (m.ref ?? ''))}
          <line class="mline {m.kind}" x1={m.x} x2={m.x} y1={M.t - 2} y2={M.t + ph} />
          {#if m.kind === 'event'}
            <path class="glyph event" d="M{m.x},{M.t - 12} l5,8 h-10 z" />
          {:else if m.kind === 'decrease'}
            <path class="glyph decrease" d="M{m.x - 5},{M.t - 12} h10 l-5,8 z" />
          {:else if m.kind === 'adapted'}
            <path class="glyph adapted" d="M{m.x},{M.t - 13} l4.5,4.5 -4.5,4.5 -4.5,-4.5 z" />
          {:else}
            <circle class="glyph answer" cx={m.x} cy={M.t - 8} r="3.6" />
          {/if}
        {/each}

        <!-- the series -->
        {#each view.paths as p, i (i)}
          {#if p.dot}
            <circle class="pt" class:sim={p.sim} cx={p.dot[0]} cy={p.dot[1]} r="2.5" />
          {:else}
            <path class="line" class:sim={p.sim} d={p.d} />
          {/if}
        {/each}
        {#if view.lastKnown}
          <circle class="end" cx={view.lastKnown.x} cy={view.lastKnown.y} r="4" />
          <text class="end-label num" x={view.lastKnown.x + 7} y={view.lastKnown.y + 4}>{fmt2(view.lastKnown.v)}</text>
        {/if}

        {#if hover}
          <line class="cross" x1={x(hover[0])} x2={x(hover[0])} y1={M.t} y2={M.t + ph} />
          {#if hover[2] != null}<circle class="hover-dot" cx={x(hover[0])} cy={y(hover[2])} r="4.5" />{/if}
        {/if}

        <!-- hit area bigger than the marks -->
        <rect class="hit" x={M.l} y={0} width={pw} height={H} tabindex="0" role="slider" aria-valuemin="0" aria-valuemax="1"
              aria-valuenow={hover?.[2] ?? undefined} aria-label="Inspect timeline values (arrow keys)"
              onpointermove={onMove} onpointerleave={() => (cursor = null)} onkeydown={onKey} onblur={() => (cursor = null)} />
      </svg>
      {#if hover}
        <div class="tip" style:left="{Math.min(Math.max(x(hover[0]), 70), width - 70)}px">
          {#if hover[2] != null && hover[3] === 'ok'}
            <strong class="num">{fmt2(hover[2])}</strong>
            <span>{hover[4] === 'simulation' ? 'simulated' : 'camera'} · {clock(hover[0])}</span>
          {:else}
            <strong>unknown</strong><span>{clock(hover[0])}</span>
          {/if}
          {#if hoverMarker}<span class="tip-mark">{MARK[hoverMarker.kind] ?? hoverMarker.label}</span>{/if}
        </div>
      {/if}
    </div>
    <div class="legend">
      <span><i class="k-line"></i>proxy</span>
      <span><i class="k-line sim"></i>simulated</span>
      <span><i class="k-rug"></i>unknown</span>
      <span><svg width="10" height="10"><path class="glyph event" d="M5,1 l4.5,8 h-9 z" /></svg>possible confusion</span>
      <span><svg width="10" height="10"><circle class="glyph answer" cx="5" cy="5" r="3.5" /></svg>answer</span>
      <span><svg width="10" height="10"><path class="glyph adapted" d="M5,.5 l4.5,4.5 -4.5,4.5 -4.5,-4.5 z" /></svg>adapted</span>
      <span><svg width="10" height="10"><path class="glyph decrease" d="M.5,1 h9 l-4.5,8 z" /></svg>decrease</span>
    </div>
  {/if}
</section>

<style>
  .tl { padding: 12px 12px 10px; display: flex; flex-direction: column; gap: 4px; }
  .top { display: flex; align-items: center; justify-content: space-between; }
  .subtitle { font-size: 11.5px; color: var(--faint); }
  .subtitle em { font-style: normal; color: var(--muted); }
  .btn.on { color: var(--text); background: var(--sheen), var(--raise); }
  .plot { position: relative; margin-top: 4px; border-radius: 10px; background: var(--viz-surface); box-shadow: var(--sink); overflow: hidden; }
  svg { display: block; }
  .grid { stroke: var(--viz-grid); stroke-width: 1; }
  .tick { fill: var(--faint); font-size: 9.5px; font-variant-numeric: tabular-nums; }
  .thr { stroke: var(--muted); stroke-width: 1; stroke-dasharray: 4 3; opacity: .8; }
  .thr-label { fill: var(--muted); font-size: 10px; font-variant-numeric: tabular-nums; }
  .rug { fill: var(--faint); opacity: .5; }
  .mline { stroke: var(--line-3); stroke-width: 1; opacity: .7; }
  .mline.event { stroke: var(--viz-event); opacity: .55; }
  .mline.decrease { stroke: var(--viz-decrease); opacity: .55; }
  .glyph { stroke: var(--viz-surface); stroke-width: 2; paint-order: stroke; }
  .glyph.event { fill: var(--viz-event); }
  .glyph.decrease { fill: var(--viz-decrease); }
  .glyph.answer { fill: var(--muted); }
  .glyph.adapted { fill: var(--viz-surface); stroke: var(--text-2); stroke-width: 1.6; }
  .legend .glyph { stroke-width: 0; }
  .legend .glyph.adapted { fill: none; stroke: var(--text-2); stroke-width: 1.3; }
  .line { fill: none; stroke: var(--viz-signal); stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .line.sim { stroke-dasharray: 5 4; }
  .pt { fill: var(--viz-signal); }
  .end { fill: var(--viz-signal); stroke: var(--viz-surface); stroke-width: 2; }
  .end-label { fill: var(--text-2); font-size: 10.5px; font-weight: 600; }
  .cross { stroke: var(--text-2); stroke-width: 1; opacity: .55; }
  .hover-dot { fill: var(--viz-signal); stroke: var(--text); stroke-width: 2; }
  .hit { fill: transparent; outline: none; cursor: crosshair; }
  .hit:focus-visible { stroke: var(--accent); stroke-width: 1; }
  .tip {
    position: absolute; top: 6px; transform: translateX(-50%); pointer-events: none;
    display: flex; flex-direction: column; align-items: center; gap: 1px; padding: 5px 9px; border-radius: 8px;
    background: rgb(12 18 36 / .94); box-shadow: var(--ring-2), var(--rise-2); font-size: 11px; color: var(--muted); white-space: nowrap;
  }
  .tip strong { color: var(--text); font-size: 13px; }
  .tip-mark { color: var(--text-2); }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 11px; margin-top: 6px; font-size: 10.5px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .k-line { width: 14px; height: 0; border-top: 2px solid var(--viz-signal); }
  .k-line.sim { border-top-style: dashed; }
  .k-rug { width: 12px; height: 3px; border-radius: 2px; background: var(--faint); opacity: .6; }
  .data { width: 100%; border-collapse: collapse; font-size: 11.5px; margin-top: 6px; }
  .data th { text-align: left; color: var(--faint); font-weight: 600; padding: 4px 6px; border-bottom: 1px solid var(--line-2); }
  .data td { padding: 4px 6px; border-bottom: 1px solid var(--line); color: var(--text-2); }
</style>
