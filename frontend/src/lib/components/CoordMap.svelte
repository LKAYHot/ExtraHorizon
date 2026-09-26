<script>
  import { onMount } from 'svelte'
  import 'leaflet/dist/leaflet.css'
  import { app } from '$lib/app.svelte.js'
  import { OTHER, OVERLAP, PLAN_A, PLAN_B, fmtDate, fmtDistance, fmtTiming, findingsOfPair, sideOf } from '$lib/coord.js'

  // Leaflet map of the verified projects: the two compared plans in blue and orange, other plans
  // as gray context, overlaps (shared areas / shortest lines) in near-white. Basemap: standard
  // OpenStreetMap tiles (loaded by the browser from tile.openstreetmap.org — disclosed in
  // EXTERNAL_DEPENDENCIES.md), turned dark gray so the only hues on the map are the data's.
  let el = $state(null)
  let L = null
  let map = null
  let layers = null
  let byUid = new Map()
  let size = [0, 0] // the container size the view was last framed for

  const report = $derived(app.coordReport)
  const pair = $derived(app.coord.pair)
  const selected = $derived(app.coord.selected)

  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c])

  function popup(p) {
    const n = report.findings.filter((f) => f.a === p.uid || f.b === p.uid).length
    return `<div class="eh-pop"><div class="eh-pop-plan">${esc(p.plan_short)}</div>
      <div class="eh-pop-name">${esc(p.name)}</div>
      <div class="eh-pop-row">Project <b>${esc(p.project_id)}</b> · ${esc(p.status || 'status n/a')}</div>
      <div class="eh-pop-row">${esc(fmtDate(p.start))} → ${esc(fmtDate(p.end))}</div>
      <div class="eh-pop-row">${n} finding${n === 1 ? '' : 's'} with other plans</div>
      <a href="${esc(p.record_url)}" target="_blank" rel="noopener noreferrer">The county's record ↗</a></div>`
  }

  function draw() {
    if (!map || !L || !report) return
    layers?.remove()
    layers = L.layerGroup().addTo(map)
    byUid = new Map(report.projects_index.map((p) => [p.uid, p]))
    const pairFindings = findingsOfPair(report, pair)
    const involved = new Set(pairFindings.flatMap((f) => [f.a, f.b]))
    const style = (feature) => {
      const p = byUid.get(feature.properties.uid)
      const side = p ? sideOf(p.plan_short, pair) : null
      if (side === 'a') return { color: PLAN_A, weight: 1.5, fillColor: PLAN_A, fillOpacity: involved.has(p.uid) ? 0.42 : 0.18, opacity: 0.95 }
      if (side === 'b') return { color: PLAN_B, weight: 1.5, fillColor: PLAN_B, fillOpacity: involved.has(p.uid) ? 0.42 : 0.18, opacity: 0.95 }
      return { color: OTHER, weight: 0.8, fillColor: OTHER, fillOpacity: 0.08, opacity: 0.45 }
    }
    // context first, then the compared plans on top
    const ordered = [...report.projects_geojson.features].sort((f1, f2) => {
      const s1 = sideOf(byUid.get(f1.properties.uid)?.plan_short, pair) ? 1 : 0
      const s2 = sideOf(byUid.get(f2.properties.uid)?.plan_short, pair) ? 1 : 0
      return s1 - s2
    })
    L.geoJSON({ type: 'FeatureCollection', features: ordered }, {
      style,
      pointToLayer: (_f, latlng) => L.circleMarker(latlng, { radius: 5 }),
      onEachFeature: (feature, layer) => {
        const p = byUid.get(feature.properties.uid)
        if (p) layer.bindPopup(popup(p), { maxWidth: 300 })
      },
    }).addTo(layers)
    // overlaps of the chosen pair
    for (const f of pairFindings) {
      if (!f.geometry) continue
      const sel = f.id === selected
      L.geoJSON(f.geometry, {
        style: () => ({
          color: OVERLAP, weight: sel ? 4 : 2, opacity: sel ? 1 : 0.85, fillColor: OVERLAP, fillOpacity: sel ? 0.7 : 0.45,
          dashArray: f.distance_m > 0 ? '4 4' : null,
        }),
        pointToLayer: (_g, latlng) => L.circleMarker(latlng, { radius: sel ? 7 : 4 }),
      }).bindTooltip(`${f.id} · ${fmtDistance(f.distance_m)} · ${fmtTiming(f)}`, { sticky: true })
        .on('click', () => app.selectFinding(f.id))
        .addTo(layers)
    }
    // the two projects of the selected finding, outlined
    const f = report.findings.find((x) => x.id === selected)
    if (f) {
      L.geoJSON({ type: 'FeatureCollection', features: featuresOf([f.a, f.b]) }, {
        style: () => ({ color: OVERLAP, weight: 2.5, fill: false, opacity: 0.9 }),
        pointToLayer: (_g, latlng) => L.circleMarker(latlng, { radius: 8 }),
      }).addTo(layers)
    }
    fit(true)
  }

  const featuresOf = (uids) => {
    const want = new Set(uids)
    return report.projects_geojson.features.filter((x) => want.has(x.properties.uid))
  }

  // Frame where the selected finding overlaps (a state-road corridor can span the whole county, so not
  // both projects), else every project of the chosen pair's findings, else everything.
  function fit(animate) {
    if (!map || !L || !report) return
    size = [el.clientWidth, el.clientHeight]
    const f = report.findings.find((x) => x.id === selected)
    if (f?.geometry) {
      const spot = L.geoJSON(f.geometry).getBounds()
      if (spot.isValid()) return map.fitBounds(spot.pad(0.6), { maxZoom: 16, animate })
    }
    const uids = f ? [f.a, f.b] : findingsOfPair(report, pair).flatMap((x) => [x.a, x.b])
    const feats = featuresOf(uids)
    const target = L.geoJSON(feats.length ? { type: 'FeatureCollection', features: feats } : report.projects_geojson).getBounds()
    if (target.isValid()) map.fitBounds(target.pad(f ? 0.35 : 0.05), { maxZoom: f ? 17 : 15, animate })
  }

  onMount(() => {
    let ro = null
    let dead = false
    import('leaflet').then((mod) => {
      if (dead || !el) return
      L = mod.default ?? mod
      const [lat, lon] = report?.region?.center ?? [25.76, -80.3]
      map = L.map(el, { preferCanvas: true, zoomControl: true, attributionControl: true }).setView([lat, lon], 10)
      // OpenStreetMap's standard tiles (ODbL data, OSMF tile policy), darkened with a CSS filter
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, className: 'eh-dark-tiles',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
      }).addTo(map)
      // the panel settles its width after the map is created: frame the data again for the real size
      ro = new ResizeObserver(() => {
        if (!map || (el.clientWidth === size[0] && el.clientHeight === size[1])) return
        map.invalidateSize()
        fit(false)
      })
      ro.observe(el)
      draw()
    })
    return () => {
      dead = true
      ro?.disconnect()
      map?.remove()
      map = null
    }
  })

  $effect(() => {
    void report
    void pair
    void selected
    draw()
  })
</script>

<div class="map" bind:this={el} data-testid="coord-map" aria-label="Map of the planned projects and their overlaps"></div>

<style>
  .map { width: 100%; height: 100%; min-height: 260px; border-radius: var(--radius-sm); overflow: hidden; background: #1b1c1e; box-shadow: var(--sink); }
  .map :global(.leaflet-container) { background: #1b1c1e; font-family: var(--font); }
  .map :global(.eh-dark-tiles) { filter: grayscale(100%) invert(100%) brightness(78%) contrast(92%); }
  .map :global(.leaflet-popup-content-wrapper), .map :global(.leaflet-popup-tip) {
    background: var(--raise); color: var(--text); box-shadow: var(--rise-3); border: 1px solid var(--edge-2);
  }
  .map :global(.leaflet-popup-content) { margin: 10px 12px; font-size: 12px; line-height: 1.45; }
  .map :global(.eh-pop-plan) { font-size: 11px; color: var(--muted); font-weight: 650; letter-spacing: .02em; }
  .map :global(.eh-pop-name) { font-weight: 650; margin: 2px 0 4px; }
  .map :global(.eh-pop-row) { color: var(--text-2); }
  .map :global(.eh-pop a) { color: var(--accent); display: inline-block; margin-top: 4px; }
  .map :global(.leaflet-control-attribution) { background: rgb(10 14 26 / .75); color: var(--muted); font-size: 10px; }
  .map :global(.leaflet-control-attribution a) { color: var(--text-2); }
  .map :global(.leaflet-bar a) { background: var(--raise); color: var(--text); border-color: var(--edge-2); }
  .map :global(.leaflet-tooltip) { background: var(--raise); color: var(--text); border: 1px solid var(--edge-2); box-shadow: var(--rise-2); font-size: 11.5px; }
</style>
