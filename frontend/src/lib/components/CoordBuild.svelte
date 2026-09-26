<script>
  import { app } from '$lib/app.svelte.js'
  import { fmtNum } from '$lib/coord.js'
  import { Check, Database, Layers, LoaderCircle, ScanSearch, ShieldCheck } from '$lib/icons.js'
  import CountUp from './CountUp.svelte'

  // The analysis being built, step by step, from the server's progress events: the county's layers come in
  // one by one, then every record is verified, the plans are compared and checked against the county's list.
  const LAYERS = 16 // 14 project layers + the county's conflict list + its boundary
  const steps = $derived(app.coord.steps)
  const layers = $derived.by(() => {
    const done = new Map()
    for (const x of steps) {
      if (x.step === 'fetch' && x.source && x.phase && x.phase !== 'start') done.set(x.source, x)
    }
    return [...done.values()]
  })
  const records = $derived(layers.reduce((n, x) => n + (x.source?.startsWith('UtilCoord') ? x.records ?? 0 : 0), 0))
  const last = (step, phase) => steps.findLast((x) => x.step === step && (!phase || x.phase === phase))
  const verified = $derived(last('verify', 'done'))
  const compared = $derived(last('compare', 'done'))
  const crossed = $derived(last('crosscheck'))
  // 1 reading · 2 verifying · 3 comparing · 4 cross-checking
  const stage = $derived(compared ? 4 : verified ? 3 : last('verify') ? 2 : 1)
  const recent = $derived(layers.slice(-4).reverse())
  const waiting = $derived(steps.at(-1)?.phase === 'waiting')
</script>

<section class="build" data-testid="coord-running" aria-live="polite">
  <div class="head"><LoaderCircle size={15} class="spin" /> Building the analysis from Miami-Dade's open data…</div>
  <ol class="steps">
    <li class:on={stage === 1} class:done={stage > 1}>
      <span class="dot">{#if stage > 1}<Check size={12} />{:else}<Database size={12} />{/if}</span>
      <div class="txt">
        <b>Reading the county's layers</b>
        <span class="sub"><CountUp value={layers.length} duration={300} /> of {LAYERS} · <CountUp value={records} /> records{#if waiting} · the county's service is slow…{/if}</span>
        <span class="bar"><i style:width="{Math.min(100, (layers.length / LAYERS) * 100)}%"></i></span>
        {#if stage === 1 && recent.length}
          <span class="feed">{#each recent as x (x.source)}<span class="layer" class:bad={x.phase === 'error'}>{x.title?.replace('Utility Coordination - ', '') ?? x.source}{#if x.records != null}{' '}<em>{fmtNum(x.records)}</em>{/if}</span>{/each}</span>
        {/if}
      </div>
    </li>
    <li class:on={stage === 2} class:done={stage > 2}>
      <span class="dot">{#if stage > 2}<Check size={12} />{:else}<ShieldCheck size={12} />{/if}</span>
      <div class="txt"><b>Verifying every record</b>
        <span class="sub">{#if verified}<CountUp value={verified.projects} /> future projects pass every check{:else}IDs, dates, status, footprints, the county's boundary{/if}</span></div>
    </li>
    <li class:on={stage === 3} class:done={stage > 3}>
      <span class="dot">{#if stage > 3}<Check size={12} />{:else}<Layers size={12} />{/if}</span>
      <div class="txt"><b>Comparing the utilities' plans</b>
        <span class="sub">{#if compared}<CountUp value={compared.findings} /> overlaps in space or time{:else}close by · at the same time · both{/if}</span></div>
    </li>
    <li class:on={stage === 4}>
      <span class="dot"><ScanSearch size={12} /></span>
      <div class="txt"><b>Cross-checking with the county's own list</b>
        <span class="sub">{#if crossed}<CountUp value={crossed.county_pairs} /> pairs on the county's list{:else}the county's Potential Collaboration Project list{/if}</span></div>
    </li>
  </ol>
</section>

<style>
  .build { display: flex; flex-direction: column; gap: 10px; padding: 12px 14px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1); }
  .head { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); }
  .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
  li { display: flex; gap: 10px; opacity: .45; transition: opacity .3s; }
  li.on, li.done { opacity: 1; }
  .dot { width: 22px; height: 22px; flex: 0 0 22px; border-radius: 50%; display: grid; place-items: center; background: var(--well-bg); color: var(--muted); box-shadow: var(--sink); }
  li.on .dot { color: var(--primary-ink); background: var(--primary-bg); box-shadow: var(--primary-rise); animation: glow 1.4s ease-in-out infinite; }
  li.done .dot { color: var(--ok); }
  @keyframes glow { 50% { box-shadow: 0 0 0 5px color-mix(in srgb, var(--accent) 25%, transparent); } }
  .txt { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; font-size: 12.5px; }
  .txt b { font-weight: 600; color: var(--text); }
  .sub { color: var(--muted); font-size: 11.5px; font-variant-numeric: tabular-nums; }
  .bar { height: 4px; border-radius: 999px; background: var(--well); box-shadow: var(--sink); overflow: hidden; margin-top: 2px; }
  .bar i { display: block; height: 100%; background: linear-gradient(90deg, var(--accent), color-mix(in srgb, var(--accent) 50%, white)); background-size: 200% 100%; transition: width .35s ease-out; animation: shimmer 1.2s linear infinite; }
  @keyframes shimmer { to { background-position: -200% 0; } }
  .feed { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 3px; }
  .layer { font-size: 11px; color: var(--text-2); background: var(--well-bg); border-radius: 6px; padding: 1px 6px; animation: pop .35s ease-out both; }
  .layer em { font-style: normal; color: var(--muted); }
  .layer.bad { color: var(--warn); }
  @keyframes pop { from { opacity: 0; transform: translateY(4px) scale(.96); } }
  @media (prefers-reduced-motion: reduce) { li.on .dot, .bar i, .layer { animation: none; } }
</style>
