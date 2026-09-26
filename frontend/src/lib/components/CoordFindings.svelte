<script>
  import { tick, untrack } from 'svelte'
  import { app } from '$lib/app.svelte.js'
  import { CATEGORY, PLAN_A, PLAN_B, fmtDate, fmtDistance, fmtNum, fmtTiming, shownFindings, sideOf } from '$lib/coord.js'
  import { Check, CircleAlert, LoaderCircle, MapIcon, RefreshCw } from '$lib/icons.js'

  let { limit = 40 } = $props()
  let filter = $state('all') // all | both | near | same_time
  let shown = $state(40) // reset to `limit` whenever the pair or the filter changes (effect below)

  const report = $derived(app.coordReport)
  const pair = $derived(app.coord.pair)
  const index = $derived(new Map((report?.projects_index ?? []).map((p) => [p.uid, p])))
  const spot = $derived(app.coord.spot)
  const list = $derived(shownFindings(report, pair, spot).filter((f) => filter === 'all' || f.category === filter))
  const counts = $derived.by(() => {
    const c = { all: 0, both: 0, near: 0, same_time: 0 }
    for (const f of shownFindings(report, pair, spot)) {
      c.all++
      c[f.category]++
    }
    return c
  })
  const colorOf = (p) => {
    const side = sideOf(p.plan_short, pair, report)
    return side === 'a' ? PLAN_A : side === 'b' ? PLAN_B : 'var(--faint)'
  }

  $effect(() => {
    void pair
    void filter
    void spot
    shown = limit
  })
  // the finding she talks about is always on the list (the map follows the conversation, so does the list)
  $effect(() => {
    const i = list.findIndex((f) => f.id === app.coord.selected)
    if (i >= untrack(() => shown)) shown = i + 1
  })

  // …and its card comes into view under the map (the map block stays on top while the list scrolls)
  let listEl = $state()
  $effect(() => {
    const id = app.coord.selected
    void shown
    if (!id || !listEl) return
    tick().then(() => {
      const still = matchMedia('(prefers-reduced-motion: reduce)').matches
      listEl?.querySelector(`[data-id="${id}"]`)?.scrollIntoView({ block: 'nearest', behavior: still ? 'auto' : 'smooth' })
    })
  })
</script>

<div class="findings" data-testid="coord-findings">
  <div class="filters" role="radiogroup" aria-label="Kind of overlap">
    {#each [['all', 'All'], ['both', CATEGORY.both.short], ['near', CATEGORY.near.short], ['same_time', CATEGORY.same_time.short]] as [k, label] (k)}
      <button role="radio" aria-checked={filter === k} class:sel={filter === k} onclick={() => (filter = k)} data-testid="coord-filter-{k}">
        {label} <span class="n num">{fmtNum(counts[k])}</span>
      </button>
    {/each}
  </div>

  {#if report && !spot && report.findings_total > report.findings.length}
    <p class="note" data-testid="coord-listed">Listing the {fmtNum(report.findings.length)} strongest of {fmtNum(report.findings_total)} findings —
      every pair of plans and every finding {app.persona} highlights included.</p>
  {/if}
  {#if !list.length}
    <p class="empty">No findings of this kind for this pair of plans.</p>
  {/if}

  <ul class="list" bind:this={listEl}>
    {#each list.slice(0, shown) as f, i (f.id)}
      {@const a = index.get(f.a)}
      {@const b = index.get(f.b)}
      {@const rc = app.coord.rechecks[f.id]}
      <li class="card-f" class:sel={f.id === app.coord.selected} data-testid="coord-finding" data-id={f.id}
          style:animation-delay="{Math.min(i, 12) * 35}ms">
        <div class="top">
          <button class="fid" onclick={() => app.selectFinding(f.id)} title="Show on the map">{f.id}</button>
          <span class="cat {f.category}">{CATEGORY[f.category].short}</span>
          <span class="measure num">{fmtDistance(f.distance_m)}{#if f.shared_area_m2 >= 1}{' · '}{fmtNum(f.shared_area_m2)} m² shared{/if}</span>
          <span class="measure num">{fmtTiming(f)}</span>
          <span class="grow"></span>
          {#if f.county?.listed}
            <a class="county yes" href={f.county.record_url} target="_blank" rel="noopener noreferrer" title="The county's own conflict list has this pair"><Check size={11} /> county list</a>
          {:else}
            <span class="county no" title="The county's conflict list does not have this pair — worth a coordinator's look">not in county list</span>
          {/if}
        </div>
        {#each [a, b] as p (p.uid)}
          <div class="proj">
            <i class="dot" style:background={colorOf(p)}></i>
            <div class="ptext">
              <span class="plan">{p.plan_short}</span>
              <a class="pname" href={p.record_url} target="_blank" rel="noopener noreferrer" title="Open the county's record">{p.name}</a>
              <span class="pmeta">Project {p.project_id} · {p.status || 'status n/a'} · {fmtDate(p.start)} → {fmtDate(p.end)}</span>
            </div>
          </div>
        {/each}
        {#if f.id === app.coord.selected}
          <ul class="actions">
            {#each f.actions as act (act)}<li>{act}</li>{/each}
          </ul>
        {/if}
        <div class="bottom">
          <button class="btn sm ghost" onclick={() => app.selectFinding(f.id)}><MapIcon size={12} /> Show on map</button>
          <button class="btn sm ghost" onclick={() => app.recheckFinding(f.id)} disabled={rc?.state === 'checking'}
                  title="Read both projects again from the county's service now" data-testid="coord-recheck">
            {#if rc?.state === 'checking'}<LoaderCircle size={12} class="spin" />{:else}<RefreshCw size={12} />{/if} Re-check live
          </button>
          {#if rc && rc.state !== 'checking'}
            <span class="rc {rc.state}" data-testid="coord-recheck-result">
              {#if rc.state === 'ok'}<Check size={12} /> unchanged at the source{#if rc.distance_m_live != null}{' · '}{fmtDistance(rc.distance_m_live)}{/if}
              {:else if rc.state === 'changed'}<CircleAlert size={12} /> changed at the source: {rc.records.flatMap((r) => r.changed ?? (r.error ? [r.error] : [])).join(', ') || 'distance'}
              {:else}<CircleAlert size={12} /> could not re-check now: {rc.message ?? rc.records?.filter((r) => !r.found).map((r) => r.error).join(', ')}{/if}
            </span>
          {/if}
        </div>
      </li>
    {/each}
  </ul>
  {#if list.length > shown}
    <button class="btn sm more" onclick={() => (shown += limit)}>Show {Math.min(limit, list.length - shown)} more of {fmtNum(list.length - shown)}</button>
  {/if}
</div>

<style>
  .findings { display: flex; flex-direction: column; gap: 8px; min-height: 0; }
  .filters { display: inline-flex; flex-wrap: wrap; gap: 4px; padding: 2px; border-radius: 9px; background: var(--well-bg); box-shadow: var(--sink); align-self: flex-start; }
  .filters button { height: 26px; padding: 0 9px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); font-size: 11.5px; font-weight: 600; cursor: pointer; }
  .filters button:hover { color: var(--text-2); }
  .filters button.sel { background: var(--sheen), var(--raise-hi); color: var(--text); box-shadow: var(--ring-2), var(--rise-1); }
  .filters .n { color: var(--faint); margin-left: 3px; font-weight: 500; }
  .empty { color: var(--muted); font-size: 12.5px; margin: 6px 2px; }
  .list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 7px; }
  .card-f { padding: 9px 11px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1); display: flex; flex-direction: column; gap: 6px;
    scroll-margin-top: calc(var(--stage-h, 0px) + 10px); scroll-margin-bottom: 12px; }
  .card-f.sel { box-shadow: 0 0 0 1.5px color-mix(in srgb, #eef2ff 70%, transparent), var(--rise-2); }
  .top { display: flex; align-items: center; gap: 7px; flex-wrap: wrap; font-size: 11.5px; }
  .fid { border: 0; background: var(--well); color: var(--text); font: 650 11.5px var(--mono); padding: 2px 7px; border-radius: 6px; cursor: pointer; box-shadow: var(--sink); }
  .cat { padding: 1px 7px; border-radius: 999px; font-weight: 650; font-size: 10.5px; letter-spacing: .01em; }
  .cat.both { background: rgb(238 242 255 / .92); color: #0b1020; }
  .cat.near { background: rgb(238 242 255 / .16); color: var(--text); box-shadow: inset 0 0 0 1px rgb(238 242 255 / .4); }
  .cat.same_time { background: transparent; color: var(--text-2); box-shadow: inset 0 0 0 1px var(--edge-2); }
  .measure { color: var(--text-2); }
  .grow { flex: 1; }
  .county { display: inline-flex; align-items: center; gap: 3px; font-size: 10.5px; font-weight: 600; text-decoration: none; }
  .county.yes { color: var(--ok); }
  .county.no { color: var(--faint); }
  .proj { display: flex; gap: 8px; align-items: flex-start; }
  .dot { width: 9px; height: 9px; border-radius: 3px; margin-top: 4px; flex: 0 0 auto; }
  .ptext { display: flex; flex-direction: column; min-width: 0; line-height: 1.35; }
  .plan { font-size: 10.5px; color: var(--muted); font-weight: 650; letter-spacing: .02em; }
  .pname { font-size: 12.5px; color: var(--text); text-decoration: none; overflow: hidden; text-overflow: ellipsis; }
  .pname:hover { text-decoration: underline; }
  .pmeta { font-size: 11px; color: var(--faint); }
  .actions { margin: 0; padding-left: 18px; font-size: 11.5px; color: var(--text-2); display: flex; flex-direction: column; gap: 2px; }
  .actions li::marker { color: var(--accent); }
  .bottom { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .rc { display: inline-flex; align-items: center; gap: 4px; font-size: 11px; }
  .rc.ok { color: var(--ok); }
  .rc.changed, .rc.error { color: var(--warn); }
  .more { align-self: center; }
  .note { margin: 0 2px 8px; font-size: 11.5px; color: var(--muted); }
  .card-f { animation: card-in .4s ease-out both; }
  @keyframes card-in { from { opacity: 0; transform: translateY(6px); } }
  @media (prefers-reduced-motion: reduce) { .card-f { animation: none; } }
</style>
