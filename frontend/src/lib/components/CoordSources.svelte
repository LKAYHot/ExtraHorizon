<script>
  import { app } from '$lib/app.svelte.js'
  import { fmtNum } from '$lib/coord.js'
  import { Check, CircleAlert, ExternalLink, LoaderCircle, RefreshCw } from '$lib/icons.js'

  const report = $derived(app.coordReport)
  const x = $derived(report?.crosscheck)
  // why some of the county's pairs between verified projects are not flagged (said only if true)
  const notFlagged = $derived.by(() => {
    const same = x?.county_pairs_same_project ?? 0
    const other = x?.county_pairs_we_do_not_flag_count ?? x?.county_pairs_we_do_not_flag?.length ?? 0
    if (!same && !other) return ''
    if (!other) return `the other ${fmtNum(same)} pair one project with itself across two layers`
    const verb = other === 1 ? 'is' : 'are'
    if (!same) return `the other ${fmtNum(other)} ${verb} not flagged under these rules`
    return `of the others, ${fmtNum(same)} pair one project with itself across two layers and ${fmtNum(other)} ${verb} not flagged under these rules`
  })
  const byReason = $derived(Object.entries(x?.county_pairs_with_excluded_project ?? {}))
  const reasonSum = $derived(byReason.reduce((n, [, v]) => n + v, 0))
  // the form follows the report's rules (effect below) and can be edited before Apply
  let distance = $state(150)
  let windowDays = $state(60)
  let area = $state(1500)

  $effect(() => {
    if (!report) return
    distance = report.params.distance_m
    windowDays = report.params.window_days
    area = report.params.area_m
  })

  function apply(refresh = false) {
    const num = (v, lo, hi) => Math.min(hi, Math.max(lo, Number(v) || 0))
    app.applyCoordParams({ distance_m: num(distance, 0, 5000), window_days: Math.round(num(windowDays, 0, 3650)),
                           area_m: num(area, 1, 20000) }, refresh)
  }
</script>

{#if report}
  <div class="sources" data-testid="coord-sources">
    <section class="block">
      <h3>Rules</h3>
      <form class="params" novalidate onsubmit={(e) => { e.preventDefault(); apply(false) }}>
        <label>Close = within <input class="input num" type="number" min="0" max="5000" step="10" bind:value={distance} /> m</label>
        <label>Same time = at most <input class="input num" type="number" min="0" max="3650" step="5" bind:value={windowDays} /> days apart</label>
        <label>"Same time" alone within <input class="input num" type="number" min="100" max="20000" step="100" bind:value={area} /> m</label>
        <div class="row">
          <button class="btn sm primary" type="submit" disabled={app.coord.busy} data-testid="coord-apply">
            {#if app.coord.busy}<LoaderCircle size={12} class="spin" />{/if} Apply
          </button>
          <button class="btn sm ghost" type="button" onclick={() => apply(true)} disabled={app.coord.busy}
                  title="Read every layer from the county's services again" data-testid="coord-refresh">
            <RefreshCw size={12} /> Read the county's data again
          </button>
        </div>
      </form>
    </section>

    <section class="block">
      <h3>Cross-check with the county's own conflict list</h3>
      <p class="lead">
        Miami-Dade's coordination system publishes the pairs of projects it found overlapping
        ({fmtNum(x.county_pairs)} pairs{#if report.conflicts_source.last_edit}, last regenerated {report.conflicts_source.last_edit}{/if}).
      </p>
      <ul class="facts">
        <li><b class="num">{fmtNum(x.our_intersecting_confirmed)}</b> of our {fmtNum(x.our_intersecting)} pairs with intersecting footprints are also on the county's list;
          <b class="num">{fmtNum(x.our_intersecting_not_listed)}</b> are not — each is marked so a coordinator can check it.</li>
        <li>Of the county's pairs between projects we verified we flag <b class="num">{fmtNum(x.county_pairs_we_also_flag)}</b> of {fmtNum(x.county_pairs_between_verified_projects)}{#if notFlagged}{' '}({notFlagged}){/if}.</li>
        {#if byReason.length}
          {@const total = x.county_pairs_with_excluded_project_total ?? reasonSum}
          <li>County pairs with a project we excluded: <b class="num">{fmtNum(total)}</b> — by reason: {byReason.map(([k, v]) => `${k} ${fmtNum(v)}`).join('; ')}{#if reasonSum > total}{' '}(a pair with two excluded projects counts under both){/if}.</li>
        {/if}
      </ul>
      <div class="src-row">
        <a class="src" href={report.conflicts_source.item_url} target="_blank" rel="noopener noreferrer">{report.conflicts_source.title} <ExternalLink size={11} /></a>
        <span class="checks">{#each report.conflicts_source.checks ?? [] as c (c.code)}<span class="ck" class:bad={!c.ok} title={c.detail}>{#if c.ok}<Check size={11} />{:else}<CircleAlert size={11} />{/if}{c.code}</span>{/each}</span>
      </div>
    </section>

    {#if report.boundary_source}
      {@const b = report.boundary_source}
      <section class="block" data-testid="coord-boundary">
        <h3>Inside the county</h3>
        <p class="lead">{#if report.region?.check === "the county's boundary"}Footprints are checked against the county's own boundary
          polygon — work entirely outside it (for example FDOT's projects in the Keys) is excluded.{:else}<span class="warn">The county's
          boundary could not be read: footprints were checked against a bounding box.</span>{/if}</p>
        <div class="src-row">
          <a class="src" href={b.item_url} target="_blank" rel="noopener noreferrer">{b.title} <ExternalLink size={11} /></a>
          <span class="checks">{#each b.checks ?? [] as c (c.code)}<span class="ck" class:bad={!c.ok} title={c.detail}>{#if c.ok}<Check size={11} />{:else}<CircleAlert size={11} />{/if}{c.code}</span>{/each}</span>
        </div>
      </section>
    {/if}

    <section class="block">
      <h3>Sources — {report.publisher}</h3>
      <p class="lead">Read {report.generated_at_local}{#if report.offline}{' · '}<b class="warn">OFFLINE TEST FIXTURE — not the county's data</b>{/if}{#if report.stale_note}{' · '}<span class="warn">{report.stale_note}</span>{/if}.
        Every record is checked: an ID, both dates, start ≤ end, plausible years, not finished (status or end date), a valid footprint inside the county.</p>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Layer</th><th class="r">Received</th><th class="r">Verified</th><th>Excluded</th><th>Checks</th></tr></thead>
          <tbody>
            {#each report.sources as s (s.key)}
              <tr class:empty={s.reported === 0}>
                <td><a href={s.item_url} target="_blank" rel="noopener noreferrer">{s.title.replace('Utility Coordination - ', '')}</a>
                  {#if s.utility}<span class="kind">utility</span>{/if}
                  {#if s.last_edit}<div class="sub">edited {s.last_edit}</div>{/if}
                  {#if s.error}<div class="sub warn">{s.error}</div>{/if}</td>
                <td class="r num">{fmtNum(s.received)}<span class="sub">/{fmtNum(s.reported)}</span></td>
                <td class="r num"><b>{fmtNum(s.verified)}</b></td>
                <td>{#if s.error && !s.received}<span class="sub warn">could not be read — left out</span>{:else if s.reported === 0}<span class="sub">published but empty</span>{:else}
                  {#each s.excluded as e (e.code)}<span class="ex" title={e.label}>{e.label.split(' (')[0]} <b class="num">{fmtNum(e.count)}</b></span>{/each}{/if}</td>
                <td class="checks">{#each s.checks as c (c.code)}<span class="ck" class:bad={!c.ok} title={c.detail}>{#if c.ok}<Check size={11} />{:else}<CircleAlert size={11} />{/if}{c.code}</span>{/each}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="lead fine">Map: © <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a>
        contributors (ODbL) — the tiles are loaded by this browser from tile.openstreetmap.org. Contact details in the
        county's records stay out of what {app.persona} is told.</p>
    </section>
  </div>
{/if}

<style>
  .sources { display: flex; flex-direction: column; gap: 12px; }
  .block { display: flex; flex-direction: column; gap: 6px; }
  h3 { margin: 0; font-size: 12px; font-weight: 650; color: var(--text); letter-spacing: .01em; }
  .lead { margin: 0; font-size: 12px; color: var(--text-2); line-height: 1.5; }
  .lead.fine { font-size: 11px; color: var(--muted); }
  .lead a { color: var(--text-2); }
  .facts { margin: 0; padding-left: 16px; font-size: 12px; color: var(--text-2); line-height: 1.5; display: flex; flex-direction: column; gap: 3px; }
  .facts li::marker { color: var(--accent); }
  .facts b { color: var(--text); }
  .src { font-size: 11.5px; color: var(--accent); text-decoration: none; display: inline-flex; align-items: center; gap: 3px; }
  .params { display: flex; flex-direction: column; gap: 6px; font-size: 12px; color: var(--text-2); }
  .params label { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .params .input { width: 76px; height: 28px; padding: 0 8px; font-size: 12px; }
  .params .row { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 2px; }
  .table-wrap { overflow-x: auto; border-radius: var(--radius-xs); box-shadow: var(--ring); }
  table { width: 100%; border-collapse: collapse; font-size: 11.5px; }
  th { text-align: left; color: var(--muted); font-weight: 600; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
  td { padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; color: var(--text-2); }
  tr.empty td { color: var(--faint); }
  td a { color: var(--text); text-decoration: none; }
  td a:hover { text-decoration: underline; }
  .r { text-align: right; }
  .sub { display: block; font-size: 10.5px; color: var(--faint); }
  td.r .sub { display: inline; }
  .kind { margin-left: 5px; font-size: 9.5px; padding: 0 5px; border-radius: 999px; box-shadow: inset 0 0 0 1px var(--edge-2); color: var(--muted); }
  .ex { display: inline-block; margin: 0 6px 2px 0; white-space: nowrap; }
  .ex b { color: var(--text); }
  .checks { white-space: nowrap; }
  .ck { display: inline-flex; align-items: center; gap: 2px; margin-right: 6px; color: var(--ok); }
  .ck.bad { color: var(--warn); }
  .warn { color: var(--warn); }
  .src-row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
</style>
