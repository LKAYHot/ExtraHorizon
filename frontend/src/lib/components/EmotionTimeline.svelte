<script>
  import { app } from '$lib/app.svelte.js'
  import { clock, signed } from '$lib/format.js'
  import { COLOR, EMOTIONS, LABEL, STACK } from '$lib/emotions.js'
  import { ChartArea, Table2 } from '$lib/icons.js'

  const WINDOW = 60_000
  const H = 168
  const M = { l: 32, r: 10, t: 18, b: 22 }
  const IDX = Object.fromEntries(EMOTIONS.map((k, i) => [k, i]))

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
  const x = (t) => M.l + ((t - (now - WINDOW)) / WINDOW) * pw
  const y = (v) => M.t + (1 - v) * ph

  const view = $derived.by(() => {
    void app.timelineVersion
    const t0 = now - WINDOW
    const samples = app.timeline.samples.filter((s) => s[0] >= t0 - 1000)
    const segs = []
    const rugs = []
    const sims = []
    let seg = null
    let rug = null
    let sim = null
    let prevT = null
    for (const s of samples) {
      const [t, status, source, , probs] = s
      const gap = prevT !== null && t - prevT > 1500
      prevT = t
      const xt = Math.max(M.l, x(t))
      if (status !== 'ok' || !probs) {
        seg = null
        sim = null
        if (!rug || gap) rugs.push((rug = { x0: xt, x1: xt }))
        else rug.x1 = xt
        continue
      }
      rug = null
      const total = probs.reduce((a, b) => a + b, 0) || 1
      if (!seg || gap) segs.push((seg = []))
      seg.push({ x: xt, p: probs.map((v) => v / total) })
      if (source === 'simulation') {
        if (!sim || gap) sims.push((sim = { x0: xt, x1: xt }))
        else sim.x1 = xt
      } else sim = null
    }
    const layers = STACK.map((k) => ({ k, d: '' }))
    let seps = ''
    for (const sg of segs) {
      const pts = sg.length === 1 ? [sg[0], { x: sg[0].x + 2, p: sg[0].p }] : sg
      const cum = pts.map(() => 0)
      STACK.forEach((k, li) => {
        const lower = cum.slice()
        const ei = IDX[k]
        for (let i = 0; i < pts.length; i++) cum[i] += pts[i].p[ei]
        let top = ''
        for (let i = 0; i < pts.length; i++) top += `${i ? 'L' : 'M'}${pts[i].x.toFixed(1)},${y(Math.min(1, cum[i])).toFixed(1)}`
        let back = ''
        for (let i = pts.length - 1; i >= 0; i--) back += `L${pts[i].x.toFixed(1)},${y(Math.min(1, lower[i])).toFixed(1)}`
        layers[li].d += `${top}${back}Z`
        if (li < STACK.length - 1) seps += top
      })
    }
    const markers = app.timeline.markers.filter((m) => m.t >= t0).map((m) => ({ ...m, x: x(m.t) }))
    return { samples, layers, seps, rugs, sims, markers }
  })

  const hover = $derived(cursor != null ? (view.samples[Math.min(cursor, view.samples.length - 1)] ?? null) : null)
  const hoverRows = $derived.by(() => {
    if (!hover || hover[1] !== 'ok' || !hover[4]) return []
    return EMOTIONS.map((k, i) => ({ k, p: hover[4][i] })).sort((a, b) => b.p - a.p)
  })
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

  function onMove(ev) {
    const r = ev.currentTarget.getBoundingClientRect()
    cursor = nearestIndex(ev.clientX - r.left)
  }

  function onKey(ev) {
    const n = view.samples.length
    if (!n) return
    if (ev.key === 'ArrowLeft') cursor = Math.max(0, (cursor ?? n) - 1)
    else if (ev.key === 'ArrowRight') cursor = Math.min(n - 1, (cursor ?? n - 2) + 1)
    else if (ev.key === 'Escape') cursor = null
    else return
    ev.preventDefault()
  }

  const tipLeft = $derived(hover ? x(hover[0]) : 0)
  const tipOnLeft = $derived(tipLeft > width / 2)

  const tableRows = $derived.by(() => {
    if (!table) return []
    const rows = view.markers.map((m) => ({
      t: m.t, what: m.kind === 'emotion' ? `→ ${m.label}` : m.label, top: '', va: '',
    }))
    let lastT = -Infinity
    const picked = []
    for (let i = view.samples.length - 1; i >= 0 && picked.length < 12; i--) {
      const s = view.samples[i]
      if (lastT - s[0] < 2000) continue // about one row every 2 s
      lastT = s[0]
      picked.push(s)
    }
    for (const s of picked) {
      if (s[1] !== 'ok' || !s[4]) {
        rows.push({ t: s[0], what: 'unknown', top: '', va: '' })
        continue
      }
      const top = EMOTIONS.map((k, i) => [k, s[4][i]]).sort((a, b) => b[1] - a[1]).slice(0, 3)
      rows.push({
        t: s[0],
        what: `${LABEL[s[3]] ?? '—'}${s[2] === 'simulation' ? ' (sim)' : ''}`,
        top: top.map(([k, p]) => `${LABEL[k]} ${Math.round(p * 100)}%`).join(' · '),
        va: `${signed(s[5])} / ${signed(s[6])}`,
      })
    }
    return rows.sort((a, b) => b.t - a.t)
  })
</script>

<section class="card spot tl" data-testid="emotion-timeline">
  <div class="top">
    <div class="eyebrow"><ChartArea size={13} /> Expression timeline · last 60 s</div>
    <button class="btn sm ghost icon" class:on={table} onclick={() => (table = !table)} aria-pressed={table} title="Table view" aria-label="Toggle table view"><Table2 size={14} /></button>
  </div>
  <div class="subtitle">Share of each expression (smoothed estimate) — measured values only; gaps = unknown</div>

  {#if table}
    <div class="scroll">
      <table class="data">
        <thead><tr><th>time</th><th>expression</th><th>top three</th><th>valence / energy</th></tr></thead>
        <tbody>
          {#each tableRows as r, i (i)}
            <tr><td class="num">{clock(r.t)}</td><td>{r.what}</td><td>{r.top}</td><td class="num">{r.va}</td></tr>
          {:else}
            <tr><td colspan="4" class="faint">No measurements yet.</td></tr>
          {/each}
        </tbody>
      </table>
    </div>
  {:else}
    <div class="plot" bind:clientWidth={width}>
      <svg width={width} height={H} role="img" aria-label="Stacked timeline of the estimated facial expressions over the last 60 seconds">
        {#each [0, 0.5, 1] as g (g)}
          <line class="grid" x1={M.l} x2={M.l + pw} y1={y(g)} y2={y(g)} />
          <text class="tick" x={M.l - 6} y={y(g) + 3.5} text-anchor="end">{g * 100}%</text>
        {/each}
        {#each [60, 45, 30, 15] as s (s)}
          <text class="tick" x={M.l + ((WINDOW - s * 1000) / WINDOW) * pw} y={H - 6} text-anchor="middle">−{s}s</text>
        {/each}
        <text class="tick" x={M.l + pw - 10} y={H - 6} text-anchor="middle">now</text>

        {#each view.layers as l (l.k)}
          {#if l.d}<path class="layer" d={l.d} style:fill={COLOR[l.k]} />{/if}
        {/each}
        {#if view.seps}<path class="sep" d={view.seps} />{/if}

        <!-- labelled Demo simulation spans -->
        {#each view.sims as r, i (i)}
          <rect class="simband" x={r.x0} y={M.t - 7} width={Math.max(2, r.x1 - r.x0)} height="4" rx="1" />
        {/each}
        <!-- unknown periods: a rug under the plot, never drawn as a value -->
        {#each view.rugs as r, i (i)}
          <rect class="rug" x={r.x0} y={M.t + ph + 3} width={Math.max(2, r.x1 - r.x0)} height="3" rx="1.5" />
        {/each}

        {#each view.markers as m (m.t + m.kind + (m.ref ?? ''))}
          {#if m.kind === 'emotion'}
            <line class="etick" x1={m.x} x2={m.x} y1={M.t - 8} y2={M.t - 1} style:stroke={COLOR[m.ref] ?? 'var(--muted)'} />
          {:else}
            <line class="mline" x1={m.x} x2={m.x} y1={M.t} y2={M.t + ph} />
            <circle class="glyph" class:int={m.label === 'Interrupted'} cx={m.x} cy={M.t - 5} r="3.4" />
          {/if}
        {/each}

        {#if hover}
          <line class="cross" x1={x(hover[0])} x2={x(hover[0])} y1={M.t} y2={M.t + ph} />
        {/if}
        <rect class="hit" x={M.l} y={0} width={pw} height={H} tabindex="0" role="slider" aria-valuemin="0" aria-valuemax="1"
              aria-valuenow={hoverRows[0]?.p ?? undefined} aria-valuetext={hoverRows[0] ? `${LABEL[hoverRows[0].k]} ${Math.round(hoverRows[0].p * 100)}%` : 'unknown'}
              aria-label="Inspect timeline values (arrow keys)"
              onpointermove={onMove} onpointerleave={() => (cursor = null)} onkeydown={onKey} onblur={() => (cursor = null)} />
      </svg>
      {#if hover}
        <div class="tip" class:left={tipOnLeft} style:left="{tipLeft}px">
          <div class="tip-head">{clock(hover[0])}{#if hover[2] === 'simulation'}{' · '}simulated{/if}{#if hoverMarker}{' · '}{hoverMarker.kind === 'emotion' ? `→ ${hoverMarker.label}` : hoverMarker.label}{/if}</div>
          {#if hoverRows.length}
            <div class="tip-grid">
              {#each hoverRows as r (r.k)}
                <span class="tip-row"><i style:background={COLOR[r.k]}></i><strong class="num">{Math.round(r.p * 100)}%</strong> {LABEL[r.k]}</span>
              {/each}
            </div>
          {:else}
            <strong>unknown</strong>
          {/if}
        </div>
      {/if}
    </div>
    <div class="legend" aria-label="Legend">
      {#each [...STACK].reverse() as k (k)}
        <span><i style:background={COLOR[k]}></i>{LABEL[k]}</span>
      {/each}
      <span><i class="k-rug"></i>unknown</span>
      <span><svg width="10" height="10"><circle class="glyph" cx="5" cy="5" r="3.4" /></svg>answer</span>
    </div>
  {/if}
</section>

<style>
  .tl { padding: 12px 12px 10px; display: flex; flex-direction: column; gap: 4px; }
  .top { display: flex; align-items: center; justify-content: space-between; }
  .subtitle { font-size: 11.5px; color: var(--faint); }
  .btn.on { color: var(--text); background: var(--sheen), var(--raise); }
  .plot { position: relative; margin-top: 4px; border-radius: 10px; background: var(--viz-surface); box-shadow: var(--sink); overflow: hidden; }
  svg { display: block; }
  .grid { stroke: var(--viz-grid); stroke-width: 1; }
  .tick { fill: var(--faint); font-size: 9.5px; font-variant-numeric: tabular-nums; }
  .layer { opacity: .82; }
  .sep { fill: none; stroke: var(--viz-surface); stroke-width: 1.5; stroke-linejoin: round; }
  .simband { fill: #e8b85f; opacity: .8; }
  .rug { fill: var(--faint); opacity: .5; }
  .etick { stroke-width: 2.5; stroke-linecap: round; }
  .mline { stroke: var(--text-2); stroke-width: 1; opacity: .35; }
  .glyph { fill: var(--text-2); stroke: var(--viz-surface); stroke-width: 2; paint-order: stroke; }
  .glyph.int { fill: var(--viz-surface); stroke: var(--warn); stroke-width: 1.6; }
  .legend .glyph { stroke-width: 0; }
  .cross { stroke: var(--text); stroke-width: 1; opacity: .7; }
  .hit { fill: transparent; outline: none; cursor: crosshair; }
  .hit:focus-visible { stroke: var(--accent); stroke-width: 1; }
  .tip {
    position: absolute; top: 6px; transform: translateX(10px); pointer-events: none; z-index: 2;
    display: flex; flex-direction: column; gap: 4px; padding: 7px 9px; border-radius: 8px; min-width: 150px;
    background: rgb(12 18 36 / .95); box-shadow: var(--ring-2), var(--rise-2); font-size: 11px; color: var(--muted); white-space: nowrap;
  }
  .tip.left { transform: translateX(calc(-100% - 10px)); }
  .tip-head { color: var(--text-2); font-weight: 600; }
  .tip-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 1px 10px; }
  .tip-row { display: inline-flex; align-items: center; gap: 5px; }
  .tip-row i { width: 10px; height: 2.5px; border-radius: 2px; }
  .tip-row strong { color: var(--text); min-width: 28px; }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 10px; margin-top: 6px; font-size: 10.5px; color: var(--muted); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
  .k-rug { height: 3px !important; background: var(--faint); opacity: .6; }
  .scroll { max-height: 240px; overflow: auto; margin-top: 6px; }
  .data { width: 100%; border-collapse: collapse; font-size: 11px; }
  .data th { text-align: left; color: var(--faint); font-weight: 600; padding: 4px 6px; border-bottom: 1px solid var(--line-2); position: sticky; top: 0; background: var(--plane); }
  .data td { padding: 4px 6px; border-bottom: 1px solid var(--line); color: var(--text-2); vertical-align: top; }
</style>
