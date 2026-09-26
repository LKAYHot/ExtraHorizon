<script>
  import { app } from '$lib/app.svelte.js'
  import { OVERLAP, PLAN_A, PLAN_B, fmtDate, fmtTiming, findingsOfPair, sideOf } from '$lib/coord.js'

  // Gantt of the chosen pair's best findings: one row per finding, the plan-A project in blue
  // over the plan-B project in orange, the weeks both are scheduled shaded near-white, "today"
  // as a line. The findings list next to it is the table view of the same data.
  let { rows = 14 } = $props()
  let width = $state(520)
  let hover = $state(null) // {x, y, text}

  const report = $derived(app.coordReport)
  const pair = $derived(app.coord.pair)
  const index = $derived(new Map((report?.projects_index ?? []).map((p) => [p.uid, p])))
  const items = $derived.by(() => {
    const all = findingsOfPair(report, pair)
    const top = all.slice(0, rows)
    const sel = all.find((f) => f.id === app.coord.selected)
    if (sel && !top.includes(sel)) top.push(sel)
    return top.map((f) => {
      const a = index.get(f.a)
      const b = index.get(f.b)
      const [pa, pb] = sideOf(a.plan_short, pair) === 'b' ? [b, a] : [a, b]
      return { f, a: pa, b: pb }
    })
  })

  const DAY = 86400000
  const t = (iso) => Date.parse(`${iso}T00:00:00Z`)
  const today = $derived(report ? t(report.params.today) : Date.now())
  const domain = $derived.by(() => {
    if (!items.length) return [today - 365 * DAY, today + 3 * 365 * DAY]
    let lo = Infinity
    let hi = -Infinity
    for (const { a, b } of items) {
      lo = Math.min(lo, t(a.start), t(b.start))
      hi = Math.max(hi, t(a.end), t(b.end))
    }
    // keep the near term readable: at most 3 years back and 8 years ahead of today
    return [Math.max(lo, today - 3 * 365 * DAY), Math.min(hi, today + 8 * 365 * DAY)]
  })
  const LEFT = 44
  const RIGHT = 12
  const ROW = 26
  const TOP = 22
  const height = $derived(TOP + items.length * ROW + 8)
  const x = (ms) => LEFT + ((Math.min(Math.max(ms, domain[0]), domain[1]) - domain[0]) / (domain[1] - domain[0] || 1)) * (width - LEFT - RIGHT)
  const years = $derived.by(() => {
    const out = []
    const y0 = new Date(domain[0]).getUTCFullYear()
    const y1 = new Date(domain[1]).getUTCFullYear()
    const step = y1 - y0 > 8 ? 2 : 1
    for (let y = y0 + 1; y <= y1; y += step) out.push(y)
    return out
  })

  function bar(p, row, lane, color) {
    const x0 = x(t(p.start))
    const x1 = Math.max(x(t(p.end)), x0 + 3)
    return { x0, x1, y: TOP + row * ROW + (lane === 0 ? 5 : 13), color, clipL: t(p.start) < domain[0], clipR: t(p.end) > domain[1], p }
  }

  function show(e, text) {
    const r = e.currentTarget.ownerSVGElement.getBoundingClientRect()
    hover = { x: e.clientX - r.left, y: e.clientY - r.top, text }
  }
</script>

<div class="timeline" bind:clientWidth={width} data-testid="coord-timeline">
  {#if !items.length}
    <p class="empty">No findings to place on the timeline for this pair.</p>
  {:else}
    <svg {width} {height} role="img" aria-label="Schedules of the two projects in each finding, with the time they overlap">
      {#each years as y (y)}
        {@const gx = x(Date.UTC(y, 0, 1))}
        <line x1={gx} x2={gx} y1={TOP - 6} y2={height - 6} class="grid" />
        {#if Math.abs(gx - x(today)) > 34}<text x={gx} y={12} class="tick" text-anchor="middle">{y}</text>{/if}
      {/each}
      {#each items as { f, a, b }, i (f.id)}
        {@const ba = bar(a, i, 0, PLAN_A)}
        {@const bb = bar(b, i, 1, PLAN_B)}
        <g class="row" class:sel={f.id === app.coord.selected} onclick={() => app.selectFinding(f.id)} role="button" tabindex="-1"
           onkeydown={(e) => e.key === 'Enter' && app.selectFinding(f.id)}>
          <rect x="0" y={TOP + i * ROW} width={width} height={ROW} class="hit" />
          <text x="4" y={TOP + i * ROW + 16} class="rid">{f.id}</text>
          {#if f.window?.[0]}
            <rect x={x(t(f.window[0]))} y={TOP + i * ROW + 2} width={Math.max(2, x(t(f.window[1])) - x(t(f.window[0])))} height={ROW - 4}
                  rx="3" fill={OVERLAP} opacity="0.16" />
          {/if}
          {#each [ba, bb] as bb2 (bb2.p.uid)}
            <rect x={bb2.x0} y={bb2.y} width={bb2.x1 - bb2.x0} height="7" rx="3.5" fill={bb2.color} role="img"
                  aria-label="{bb2.p.plan_short}: {bb2.p.name}, {fmtDate(bb2.p.start)} to {fmtDate(bb2.p.end)}"
                  onpointermove={(e) => show(e, `${bb2.p.plan_short} · ${bb2.p.name} · ${fmtDate(bb2.p.start)} → ${fmtDate(bb2.p.end)}`)}
                  onpointerleave={() => (hover = null)} />
            {#if bb2.clipL}<path d="M {bb2.x0 + 1} {bb2.y + 3.5} l 4 -3.5 v 7 z" class="clip" />{/if}
            {#if bb2.clipR}<path d="M {bb2.x1 - 1} {bb2.y + 3.5} l -4 -3.5 v 7 z" class="clip" />{/if}
          {/each}
          <title>{f.id}: {fmtTiming(f)}</title>
        </g>
      {/each}
      <line x1={x(today)} x2={x(today)} y1={TOP - 8} y2={height - 4} class="today" />
      <text x={x(today) + 4} y={TOP - 10} class="today-l">today</text>
    </svg>
    {#if hover}<div class="tip" style:left="{Math.min(hover.x + 12, width - 240)}px" style:top="{hover.y + 12}px">{hover.text}</div>{/if}
    <div class="legend">
      <span><i style:background={PLAN_A}></i>{pair?.split(' ↔ ')[0] ?? 'Plan A'}</span>
      <span><i style:background={PLAN_B}></i>{pair?.split(' ↔ ')[1] ?? 'Plan B'}</span>
      <span><i class="ov"></i>both scheduled</span>
      <span class="faint">▸ runs past the edge</span>
    </div>
  {/if}
</div>

<style>
  .timeline { position: relative; width: 100%; }
  .empty { color: var(--muted); font-size: 12.5px; margin: 6px 2px; }
  svg { display: block; }
  .grid { stroke: var(--viz-grid); stroke-width: 1; }
  .tick { fill: var(--faint); font-size: 10.5px; font-family: var(--mono); }
  .rid { fill: var(--muted); font: 600 10.5px var(--mono); }
  .row { cursor: pointer; }
  .row .hit { fill: transparent; }
  .row:hover .hit { fill: rgb(170 190 255 / .04); }
  .row.sel .hit { fill: rgb(238 242 255 / .07); }
  .row.sel .rid { fill: var(--text); }
  .clip { fill: #0b1020; opacity: .8; }
  .today { stroke: #eef2ff; stroke-width: 1.5; stroke-dasharray: 3 3; opacity: .8; }
  .today-l { fill: var(--text-2); font-size: 10.5px; }
  .tip { position: absolute; max-width: 240px; padding: 6px 8px; border-radius: 8px; background: var(--raise); border: 1px solid var(--edge-2); box-shadow: var(--rise-2); font-size: 11.5px; color: var(--text); pointer-events: none; z-index: 5; }
  .legend { display: flex; flex-wrap: wrap; gap: 4px 12px; margin-top: 6px; font-size: 11px; color: var(--text-2); }
  .legend span { display: inline-flex; align-items: center; gap: 5px; }
  .legend i { width: 14px; height: 6px; border-radius: 3px; display: inline-block; }
  .legend i.ov { background: #eef2ff; opacity: .35; height: 10px; }
  .legend .faint { color: var(--faint); }
</style>
