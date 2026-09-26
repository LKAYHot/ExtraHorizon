<script>
  import { app } from '$lib/app.svelte.js'
  import { ALL_PAIRS, CATEGORY, PLAN_A, PLAN_B, fmtNum, orderPair, pairKey } from '$lib/coord.js'
  import { CalendarRange, CircleAlert, Construction, Crosshair, Database, ListChecks, MapIcon, RefreshCw, ScanFace, X } from '$lib/icons.js'
  import Select from './Select.svelte'
  import CoordBuild from './CoordBuild.svelte'
  import CountUp from './CountUp.svelte'
  import CoordMap from './CoordMap.svelte'
  import CoordFindings from './CoordFindings.svelte'
  import CoordTimeline from './CoordTimeline.svelte'
  import CoordSources from './CoordSources.svelte'

  const report = $derived(app.coordReport)
  const c = app.coord
  const s = $derived(report?.summary)
  const pairOptions = $derived([
    ...(report ? [{ value: ALL_PAIRS, label: 'All pairs of plans', hint: `${fmtNum(s?.findings)} findings` }] : []),
    ...(report?.pairs ?? []).map((p) => {
      const plans = orderPair(p.plans, report)
      return { value: pairKey(plans), label: `${plans[0]} ↔ ${plans[1]}`, hint: `${fmtNum(p.total)} · ${fmtNum(p.both)} close + same time` }
    }),
  ])
  const running = $derived(c.state === 'running')
  let stageH = $state(0) // the map block's height: a selected card scrolls in just below it
  const all = $derived(c.pair === ALL_PAIRS)
  const [planA, planB] = $derived(all ? ['utility networks', 'road and other work'] : (c.pair ?? ' ↔ ').split(' ↔ '))
</script>

<aside class="panel analysis" aria-label="Utility coordination analysis" data-testid="analysis-panel">
  <header class="head">
    <div class="title"><Construction size={16} /> <h2>Utility coordination</h2>
      <span class="chip">{report?.offline ? 'TEST FIXTURE' : 'Miami-Dade · open data'}</span>
    </div>
    <div class="actions">
      {#if report}
        <button class="btn sm" onclick={() => app.runAnalysis()} disabled={app.busy || running} title="Run again and let {app.persona} explain it"
                data-testid="coord-rerun"><RefreshCw size={12} /> Ask again</button>
      {/if}
      <button class="btn sm icon ghost" onclick={() => app.closeAnalysisView()} title="Back to the camera panel (the analysis stays open)"
              aria-label="Back to the camera panel" data-testid="coord-hide"><ScanFace size={14} /></button>
      {#if report}
        <button class="btn sm icon ghost" onclick={() => app.closeAnalysis()} title="Close the analysis — her answers are ordinary tutoring again"
                aria-label="Close the analysis" data-testid="coord-close"><X size={14} /></button>
      {/if}
    </div>
  </header>

  <div class="scroll" style:--stage-h="{stageH}px">
    {#if running}<CoordBuild />{/if}

    {#if c.state === 'error'}
      <section class="card err" role="alert"><CircleAlert size={15} /> {c.error}</section>
    {/if}

    {#if report}
      <section class="tiles">
        <div class="tile"><span class="v num"><CountUp value={s.plans} /></span><span class="k">plans compared</span></div>
        <div class="tile"><span class="v num"><CountUp value={s.projects_verified} /></span><span class="k">future projects verified</span><span class="k2">of {fmtNum(s.records_received)} records</span></div>
        <div class="tile"><span class="v num" data-testid="coord-findings-count"><CountUp value={s.findings} /></span><span class="k">overlaps flagged</span>
          <span class="k2">{fmtNum(s.by_category.both ?? 0)} close + same time</span></div>
        <div class="tile"><span class="v num"><CountUp value={report.crosscheck.our_intersecting_confirmed} /><span class="of">/{fmtNum(report.crosscheck.our_intersecting)}</span></span>
          <span class="k">on the county's own list</span></div>
      </section>

      <!-- the map follows the conversation, so it stays in view: the list scrolls under this block -->
      <div class="stage" bind:clientHeight={stageH}>
        <section class="pairbar">
          <span class="lbl">Compare</span>
          <div class="pick"><Select options={pairOptions} value={c.pair} onchange={(v) => app.choosePair(v)} label="Pair of plans" testid="coord-pair" /></div>
          <span class="legend"><i style:background={PLAN_A}></i>{planA}</span>
          <span class="legend"><i style:background={PLAN_B}></i>{planB}</span>
          <span class="legend"><i class="ov"></i>overlap</span>
        </section>

        {#if c.spot}
          <section class="spot" data-testid="coord-spot">
            <Crosshair size={13} />
            <span class="spot-t">{app.persona} is showing <b>{c.spot.label || 'these findings'}</b> —
              {#if !c.spot.ids.length}the project (no findings under these rules){:else if (c.spot.total ?? 0) > c.spot.ids.length}the best {fmtNum(c.spot.ids.length)} of {fmtNum(c.spot.total)} findings{:else}{fmtNum(c.spot.ids.length)} finding{c.spot.ids.length === 1 ? '' : 's'}{/if}</span>
            <button class="btn sm ghost" onclick={() => app.clearSpot()} data-testid="coord-spot-clear">Show all</button>
          </section>
        {/if}

        <div class="mapbox"><CoordMap /></div>
      </div>

      <div class="tabs" role="tablist">
        <button role="tab" aria-selected={c.tab === 'findings'} class:sel={c.tab === 'findings'} onclick={() => (c.tab = 'findings')} data-testid="coord-tab-findings"><ListChecks size={13} /> Findings</button>
        <button role="tab" aria-selected={c.tab === 'timeline'} class:sel={c.tab === 'timeline'} onclick={() => (c.tab = 'timeline')} data-testid="coord-tab-timeline"><CalendarRange size={13} /> Schedules</button>
        <button role="tab" aria-selected={c.tab === 'sources'} class:sel={c.tab === 'sources'} onclick={() => (c.tab = 'sources')} data-testid="coord-tab-sources"><Database size={13} /> Sources & checks</button>
      </div>
      <section class="tabbody">
        {#if c.tab === 'findings'}<CoordFindings />{:else if c.tab === 'timeline'}<CoordTimeline />{:else}<CoordSources />{/if}
      </section>
    {:else if !running}
      <section class="card intro" data-testid="coord-intro">
        <div class="intro-icon"><MapIcon size={22} /></div>
        <h3>Where do the utilities' plans overlap?</h3>
        <p>{app.persona} reads Miami-Dade County's public <b>Utility Coordination</b> data — water, sewer, stormwater,
          roadway and paving projects of WASD, DTPW, FDOT and the cities — keeps only verified future or ongoing work,
          and flags pairs of plans that are <b>physically close</b> or <b>scheduled at the same time</b>, where crews,
          equipment and one excavation could be shared. Every finding links to the county's own records and is
          cross-checked against the county's conflict list.</p>
        <button class="btn primary" onclick={() => app.runAnalysis()} disabled={app.busy} data-testid="coord-run">
          <Construction size={14} /> Compare the utilities' plans
        </button>
        <ul class="kinds">
          <li><b>{CATEGORY.both.short}</b> — within the distance and the time window</li>
          <li><b>{CATEGORY.near.short}</b> — within the distance, at different times: sequence the work</li>
          <li><b>{CATEGORY.same_time.short}</b> — the same weeks, nearby: share crews and equipment</li>
        </ul>
      </section>
    {/if}
  </div>
</aside>

<style>
  .analysis { display: flex; flex-direction: column; min-width: 0; min-height: 0; border-left: 1px solid var(--line); background: linear-gradient(180deg, rgb(10 16 34 / .5), rgb(8 13 28 / .35)); }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 16px 10px; border-bottom: 1px solid var(--line); }
  .title { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .title :global(svg) { color: var(--accent); }
  h2 { font-size: 15px; font-weight: 650; margin: 0; white-space: nowrap; }
  .actions { display: flex; gap: 6px; }
  .scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 16px 16px; display: flex; flex-direction: column; gap: 10px; }
  .card { padding: 12px 14px; border-radius: var(--radius-sm); }
  .spot { display: flex; align-items: center; gap: 8px; padding: 6px 8px 6px 10px; border-radius: var(--radius-sm); font-size: 12px;
    color: var(--text-2); background: color-mix(in srgb, var(--accent) 10%, var(--plane-bg)); box-shadow: var(--ring); animation: spot-in .3s ease-out both; }
  .spot :global(svg) { color: var(--accent); flex: 0 0 auto; }
  .spot-t { flex: 1; min-width: 0; }
  .spot-t b { color: var(--text); font-weight: 600; }
  @keyframes spot-in { from { opacity: 0; transform: translateY(-4px); } }
  .tiles .tile { animation: tile-in .45s ease-out both; }
  .tiles .tile:nth-child(2) { animation-delay: .06s; }
  .tiles .tile:nth-child(3) { animation-delay: .12s; }
  .tiles .tile:nth-child(4) { animation-delay: .18s; }
  @keyframes tile-in { from { opacity: 0; transform: translateY(6px); } }
  @media (prefers-reduced-motion: reduce) { .spot, .tiles .tile { animation: none; } }
  .err { display: flex; gap: 8px; align-items: center; color: var(--warn); background: color-mix(in srgb, var(--warn) 10%, transparent); font-size: 12.5px; }
  .tiles { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 8px; }
  .tile { padding: 9px 10px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1); display: flex; flex-direction: column; gap: 1px; min-width: 0; }
  .tile .v { font: 650 22px/1.1 var(--font-display); color: var(--text); letter-spacing: -.02em; }
  .tile .of { font-size: 13px; color: var(--muted); }
  .tile .k { font-size: 11px; color: var(--muted); }
  .tile .k2 { font-size: 10.5px; color: var(--faint); }
  .pairbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .pairbar .lbl { font-size: 12px; color: var(--muted); }
  .pick { flex: 1 1 260px; min-width: 200px; display: flex; }
  .pick :global(.sel) { flex: 1; }
  .legend { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--text-2); }
  .legend i { width: 12px; height: 12px; border-radius: 3px; display: inline-block; }
  .legend i.ov { background: #eef2ff; opacity: .6; }
  .mapbox { height: clamp(260px, 40vh, 460px); flex: 0 0 auto; isolation: isolate; /* Leaflet's z-indices stay inside */ }
  .stage { position: sticky; top: -12px; /* over the scroller's own top padding */ z-index: 5; display: flex; flex-direction: column; gap: 10px; margin: -8px -16px 0;
    padding: 8px 16px 10px; background: color-mix(in srgb, var(--surface) 55%, var(--bg)); box-shadow: 0 12px 14px -12px rgb(0 0 0 / .7); }
  @media (max-height: 700px) {
    .stage { position: static; box-shadow: none; background: none; }
    .scroll { --stage-h: 0px !important; }
  }
  .tabs { display: inline-flex; gap: 4px; padding: 2px; border-radius: 9px; background: var(--well-bg); box-shadow: var(--sink); align-self: flex-start; }
  .tabs button { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 10px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer; }
  .tabs button.sel { background: var(--sheen), var(--raise-hi); color: var(--text); box-shadow: var(--ring-2), var(--rise-1); }
  .tabbody { min-height: 0; }
  .intro { display: flex; flex-direction: column; gap: 10px; align-items: flex-start; background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1); }
  .intro-icon { width: 40px; height: 40px; border-radius: 12px; display: grid; place-items: center; background: var(--primary-bg); color: var(--primary-ink); box-shadow: var(--primary-rise); }
  .intro h3 { margin: 0; font: 650 17px/1.25 var(--font-display); }
  .intro p { margin: 0; font-size: 12.5px; line-height: 1.55; color: var(--text-2); }
  .kinds { margin: 0; padding-left: 16px; font-size: 12px; color: var(--muted); display: flex; flex-direction: column; gap: 3px; }
  .kinds b { color: var(--text-2); }
  @media (max-width: 859px) { .tiles { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
</style>
