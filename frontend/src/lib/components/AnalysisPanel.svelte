<script>
  import { app } from '$lib/app.svelte.js'
  import { CATEGORY, PLAN_A, PLAN_B, fmtNum, orderPair, pairKey } from '$lib/coord.js'
  import { CalendarRange, CircleAlert, Construction, Database, ListChecks, LoaderCircle, MapIcon, RefreshCw, ScanFace, X } from '$lib/icons.js'
  import Select from './Select.svelte'
  import CoordMap from './CoordMap.svelte'
  import CoordFindings from './CoordFindings.svelte'
  import CoordTimeline from './CoordTimeline.svelte'
  import CoordSources from './CoordSources.svelte'

  let tab = $state('findings') // findings | timeline | sources
  const report = $derived(app.coordReport)
  const c = app.coord
  const s = $derived(report?.summary)
  const pairOptions = $derived((report?.pairs ?? []).map((p) => {
    const plans = orderPair(p.plans, report)
    return { value: pairKey(plans), label: `${plans[0]} ↔ ${plans[1]}`, hint: `${fmtNum(p.total)} · ${fmtNum(p.both)} close + same time` }
  }))
  const running = $derived(c.state === 'running')
  const readSteps = $derived(c.steps.filter((x) => x.step === 'fetch' && x.source && x.phase !== 'start'))
  const lastStep = $derived(c.steps.at(-1))
  const [planA, planB] = $derived((c.pair ?? ' ↔ ').split(' ↔ '))
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

  <div class="scroll">
    {#if running}
      <section class="card run" data-testid="coord-running">
        <div class="run-head"><LoaderCircle size={15} class="spin" /> Reading Miami-Dade's open data and verifying every record…</div>
        <div class="bar"><i style:width="{Math.min(100, (readSteps.length / 16) * 100)}%"></i></div>
        <div class="run-sub">{readSteps.length} of 16 layers read{#if lastStep?.step && lastStep.step !== 'fetch'}{' · '}{lastStep.step}{/if}</div>
      </section>
    {/if}

    {#if c.state === 'error'}
      <section class="card err" role="alert"><CircleAlert size={15} /> {c.error}</section>
    {/if}

    {#if report}
      <section class="tiles">
        <div class="tile"><span class="v num">{fmtNum(s.plans)}</span><span class="k">plans compared</span></div>
        <div class="tile"><span class="v num">{fmtNum(s.projects_verified)}</span><span class="k">future projects verified</span><span class="k2">of {fmtNum(s.records_received)} records</span></div>
        <div class="tile"><span class="v num" data-testid="coord-findings-count">{fmtNum(s.findings)}</span><span class="k">overlaps flagged</span>
          <span class="k2">{fmtNum(s.by_category.both ?? 0)} close + same time</span></div>
        <div class="tile"><span class="v num">{fmtNum(report.crosscheck.our_intersecting_confirmed)}<span class="of">/{fmtNum(report.crosscheck.our_intersecting)}</span></span>
          <span class="k">on the county's own list</span></div>
      </section>

      <section class="pairbar">
        <span class="lbl">Compare</span>
        <div class="pick"><Select options={pairOptions} value={c.pair} onchange={(v) => app.choosePair(v)} label="Pair of plans" testid="coord-pair" /></div>
        <span class="legend"><i style:background={PLAN_A}></i>{planA}</span>
        <span class="legend"><i style:background={PLAN_B}></i>{planB}</span>
        <span class="legend"><i class="ov"></i>overlap</span>
      </section>

      <div class="mapbox"><CoordMap /></div>

      <div class="tabs" role="tablist">
        <button role="tab" aria-selected={tab === 'findings'} class:sel={tab === 'findings'} onclick={() => (tab = 'findings')} data-testid="coord-tab-findings"><ListChecks size={13} /> Findings</button>
        <button role="tab" aria-selected={tab === 'timeline'} class:sel={tab === 'timeline'} onclick={() => (tab = 'timeline')} data-testid="coord-tab-timeline"><CalendarRange size={13} /> Schedules</button>
        <button role="tab" aria-selected={tab === 'sources'} class:sel={tab === 'sources'} onclick={() => (tab = 'sources')} data-testid="coord-tab-sources"><Database size={13} /> Sources & checks</button>
      </div>
      <section class="tabbody">
        {#if tab === 'findings'}<CoordFindings />{:else if tab === 'timeline'}<CoordTimeline />{:else}<CoordSources />{/if}
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
  .run { display: flex; flex-direction: column; gap: 8px; background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1); }
  .run-head { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text); }
  .bar { height: 4px; border-radius: 999px; background: var(--well); box-shadow: var(--sink); overflow: hidden; }
  .bar i { display: block; height: 100%; background: var(--accent); transition: width .2s linear; }
  .run-sub { font-size: 11.5px; color: var(--muted); }
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
  .mapbox { height: clamp(260px, 40vh, 460px); flex: 0 0 auto; }
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
