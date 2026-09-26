<script>
  import { onMount, untrack } from 'svelte'
  import 'leaflet/dist/leaflet.css'
  import { app } from '$lib/app.svelte.js'
  import { OTHER, OVERLAP, PLAN_A, PLAN_B, fmtDate, fmtDistance, fmtTiming, shownFindings, sideOf } from '$lib/coord.js'

  // Leaflet map of the verified projects: the two compared plans in blue and orange (or, for all pairs,
  // utility networks blue and road work orange), other plans as gray context, overlaps (shared areas /
  // shortest lines) in near-white. Basemap: standard OpenStreetMap tiles (loaded by the browser from
  // tile.openstreetmap.org — disclosed in EXTERNAL_DEPENDENCIES.md), turned dark gray so the only hues on
  // the map are the data's.
  //
  // A new analysis is *built* on the map: the county's projects are drawn in a west-to-east sweep (context,
  // then road work, then the utility networks), the overlaps light up, and the camera flies to the finding
  // being discussed; the selected overlap pulses. Everything later only restyles or flies (no redraw).
  let el = $state(null)
  let L = null
  let map = null
  let base = null // the projects (one layer per project, restyled on pair / spotlight changes)
  let overlays = null // the overlaps of the current view
  let marks = null // the selected finding: outlines + pulsing ring
  let byUid = new Map()
  let layerOf = new Map()
  let builtFor = null // the report id the base layer was built for
  let size = [0, 0] // the container size the view was last framed for
  let busyUntil = 0 // the build animation is running: wait before flying
  const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

  const report = $derived(app.coordReport)
  const pair = $derived(app.coord.pair)
  const spot = $derived(app.coord.spot)
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

  const visible = () => shownFindings(report, pair, spot)

  function styleOf(p, involved) {
    const side = p ? sideOf(p.plan_short, pair, report) : null
    const on = involved.has(p?.uid)
    if (side === 'a') return { color: PLAN_A, weight: on ? 2 : 1.4, fillColor: PLAN_A, fillOpacity: on ? 0.42 : 0.14, opacity: on ? 1 : 0.7 }
    if (side === 'b') return { color: PLAN_B, weight: on ? 2 : 1.4, fillColor: PLAN_B, fillOpacity: on ? 0.42 : 0.14, opacity: on ? 1 : 0.7 }
    return { color: OTHER, weight: 0.8, fillColor: OTHER, fillOpacity: 0.07, opacity: 0.4 }
  }

  /** The projects, once per report — with the build animation. */
  function buildBase() {
    base?.remove()
    base = L.featureGroup().addTo(map)
    byUid = new Map(report.projects_index.map((p) => [p.uid, p]))
    layerOf = new Map()
    const gj = L.geoJSON(report.projects_geojson, {
      style: () => styleOf(null, new Set()),
      pointToLayer: (_f, latlng) => L.circleMarker(latlng, { radius: 5 }),
      onEachFeature: (feature, layer) => {
        const p = byUid.get(feature.properties.uid)
        if (p) {
          layer.bindPopup(popup(p), { maxWidth: 300 })
          layerOf.set(p.uid, layer)
        }
      },
    }).addTo(base)
    builtFor = report.id
    restyle()
    if (reduced) return
    // a west-to-east sweep across the county (not the projects' extent: one corridor runs down the Keys):
    // context first, then the road work, then the utility networks
    const b = county()
    const w = b.getWest()
    const span = Math.max(1e-6, b.getEast() - w)
    gj.eachLayer((layer) => {
      const node = layer.getElement?.()
      if (!node) return
      const p = byUid.get(layer.feature?.properties?.uid)
      const util = report.plans.find((x) => x.label === p?.plan_short)?.utility
      const group = !sideOf(p?.plan_short, pair, report) ? 0 : util ? 2 : 1
      const c = layer.getBounds ? layer.getBounds().getCenter() : layer.getLatLng()
      const delay = group * 420 + Math.min(1, Math.max(0, (c.lng - w) / span)) * 900
      node.setAttribute('pathLength', '1')
      node.classList.add('eh-draw')
      node.style.animationDelay = `${Math.round(delay)}ms`
      // once drawn, never again: bringToFront() re-appends the node, which would restart the animation
      node.addEventListener('animationend', () => {
        node.classList.remove('eh-draw')
        node.style.animationDelay = ''
        node.removeAttribute('pathLength')
      }, { once: true })
    })
    busyUntil = performance.now() + 2000
  }

  /** Colours for the chosen pair / spotlight — no redraw. */
  function restyle() {
    if (!base) return
    const involved = new Set(visible().flatMap((f) => [f.a, f.b]))
    for (const [uid, layer] of layerOf) {
      layer.setStyle(styleOf(byUid.get(uid), involved))
      if (involved.has(uid)) layer.bringToFront()
    }
  }

  /** The overlaps of the current view (they light up once the projects are drawn). */
  function drawOverlaps(animate) {
    overlays?.remove()
    overlays = L.featureGroup().addTo(map)
    const list = visible()
    list.forEach((f, i) => {
      if (!f.geometry) return
      const g = L.geoJSON(f.geometry, {
        style: () => ({ color: OVERLAP, weight: 2, opacity: 0.9, fillColor: OVERLAP, fillOpacity: 0.5,
                        dashArray: f.distance_m > 0 ? '4 4' : null }),
        pointToLayer: (_g, latlng) => L.circleMarker(latlng, { radius: 4 }),
      }).bindTooltip(`${f.id} · ${fmtDistance(f.distance_m)} · ${fmtTiming(f)}`, { sticky: true })
        .on('click', () => app.selectFinding(f.id))
        .addTo(overlays)
      if (animate && !reduced) {
        g.eachLayer((layer) => {
          const node = layer.getElement?.()
          if (!node) return
          node.classList.add('eh-ignite')
          node.style.animationDelay = `${Math.round(1500 + Math.min(i, 60) * 18)}ms`
        })
      }
    })
  }

  /** The finding being discussed: its two projects outlined, a pulse on the overlap, the camera on it —
   *  or the project she showed. */
  function drawSelection() {
    marks?.remove()
    marks = L.featureGroup().addTo(map)
    const f = report.findings.find((x) => x.id === selected)
    if (!f && spot?.project) {
      L.geoJSON({ type: 'FeatureCollection', features: featuresOf([spot.project]) }, {
        style: () => ({ color: OVERLAP, weight: 3, fill: false, opacity: 0.95 }),
        pointToLayer: (_g, latlng) => L.circleMarker(latlng, { radius: 8 }),
        interactive: false,
      }).addTo(marks)
      return
    }
    if (!f) return
    // during a build it appears once the projects are drawn
    const late = reduced ? 0 : Math.max(0, busyUntil - performance.now())
    if (late) marks.on('layeradd', (e) => lateIn(e.layer, late))
    L.geoJSON({ type: 'FeatureCollection', features: featuresOf([f.a, f.b]) }, {
      style: () => ({ color: OVERLAP, weight: 2.5, fill: false, opacity: 0.95 }),
      pointToLayer: (_g, latlng) => L.circleMarker(latlng, { radius: 8 }),
      interactive: false,
    }).addTo(marks)
    const spotBounds = f.geometry ? L.geoJSON(f.geometry).getBounds() : null
    if (spotBounds?.isValid()) {
      const center = spotBounds.getCenter()
      L.geoJSON(f.geometry, {
        style: () => ({ color: OVERLAP, weight: 4, opacity: 1, fillColor: OVERLAP, fillOpacity: 0.75,
                        dashArray: f.distance_m > 0 ? '4 4' : null }),
        pointToLayer: (_g, latlng) => L.circleMarker(latlng, { radius: 7 }),
      }).bindTooltip(`${f.id} · ${fmtDistance(f.distance_m)} · ${fmtTiming(f)}`, { sticky: true }).addTo(marks)
      const ring = L.circleMarker(center, { radius: 14, color: OVERLAP, weight: 2, fill: false, opacity: 0.9, interactive: false }).addTo(marks)
      ring.getElement?.()?.classList.add('eh-pulse')
    }
  }

  function lateIn(layer, ms) {
    const each = (l) => {
      const node = l.getElement?.()
      if (node) {
        node.classList.add('eh-late')
        node.style.animationDelay = `${Math.round(ms)}ms`
      }
      l.eachLayer?.(each)
    }
    each(layer)
  }

  const featuresOf = (uids) => {
    const want = new Set(uids)
    return report.projects_geojson.features.filter((x) => want.has(x.properties.uid))
  }

  // Frame where the selected finding overlaps (a state-road corridor can span the whole county — one even runs
  // down the Keys — so never whole projects when an overlap is known), else where the spotlight's / the pair's
  // findings overlap, else the county.
  function target() {
    const f = report.findings.find((x) => x.id === selected)
    if (f?.geometry) {
      const b = L.geoJSON(f.geometry).getBounds()
      if (b.isValid()) return [b.pad(0.6), 16]
    }
    if (!f && spot?.project) {
      const b = L.geoJSON({ type: 'FeatureCollection', features: featuresOf([spot.project]) }).getBounds()
      if (b.isValid()) return [b.pad(0.25), 16]
    }
    const geoms = visible().map((x) => x.geometry).filter(Boolean)
    if (geoms.length) {
      const b = L.geoJSON({ type: 'GeometryCollection', geometries: geoms }).getBounds()
      if (b.isValid()) return [b.pad(0.15), 15]
    }
    return [county(), 12]
  }

  function county() {
    const [w, s, e, n] = report.region?.bbox ?? [-80.95, 25.1, -80.05, 26.0]
    return L.latLngBounds([s, w], [n, e])
  }

  let flyTimer = null
  function fly(smooth) {
    if (!map || !L || !report) return
    size = [el.clientWidth, el.clientHeight]
    const t = target()
    if (!t) return
    const [bounds, maxZoom] = t
    clearTimeout(flyTimer)
    if (!smooth || reduced) return map.fitBounds(bounds, { maxZoom, animate: false })
    const wait = Math.max(0, busyUntil - performance.now())
    flyTimer = setTimeout(() => map && map.flyToBounds(bounds, { maxZoom, duration: 1.1, easeLinearity: 0.2 }), wait)
  }

  function render(kind) {
    if (!map || !L || !report) return
    if (builtFor !== report.id) {
      // the build: the whole county first, then the projects sweep in, then the camera flies in
      map.fitBounds(county(), { animate: false })
      buildBase()
      drawOverlaps(true)
      drawSelection()
      fly(true)
      return
    }
    if (kind === 'view') {
      restyle()
      drawOverlaps(false)
    }
    drawSelection()
    fly(true)
  }

  onMount(() => {
    let ro = null
    let dead = false
    import('leaflet').then((mod) => {
      if (dead || !el) return
      L = mod.default ?? mod
      const [lat, lon] = report?.region?.center ?? [25.76, -80.3]
      // SVG (not canvas): every project is an element the build animation can draw
      map = L.map(el, { preferCanvas: false, renderer: L.svg({ padding: 0.5 }), zoomControl: true, attributionControl: true })
        .setView([lat, lon], 10)
      // OpenStreetMap's standard tiles (ODbL data, OSMF tile policy), darkened with a CSS filter
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, className: 'eh-dark-tiles',
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
      }).addTo(map)
      // the panel settles its width after the map is created: frame the data again for the real size
      ro = new ResizeObserver(() => {
        if (!map || (el.clientWidth === size[0] && el.clientHeight === size[1])) return
        map.invalidateSize()
        fly(false)
      })
      ro.observe(el)
      render('view')
    })
    return () => {
      dead = true
      clearTimeout(flyTimer)
      ro?.disconnect()
      map?.remove()
      map = null
    }
  })

  // the report / the pair / the spotlight change what is drawn; a selection only moves the camera
  // (render reads everything: untracked, so each effect runs only for its own inputs)
  $effect(() => {
    void report
    void pair
    void spot
    untrack(() => render('view'))
  })
  $effect(() => {
    void selected
    untrack(() => render('select'))
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

  /* the build: each project is drawn along its outline, then filled */
  .map :global(path.eh-draw) { stroke-dasharray: 1; animation: eh-draw 1.1s cubic-bezier(.3, .7, .2, 1) both; }
  @keyframes eh-draw {
    from { stroke-dashoffset: 1; fill-opacity: 0; opacity: .2; }
    60% { fill-opacity: 0; }
    to { stroke-dashoffset: 0; }
  }
  /* the overlaps light up once the projects are there */
  .map :global(path.eh-ignite) { transform-box: fill-box; transform-origin: center; animation: eh-ignite .7s cubic-bezier(.2, .9, .3, 1.4) both; }
  @keyframes eh-ignite {
    from { opacity: 0; transform: scale(.2); stroke-width: 8; }
    60% { opacity: 1; stroke-width: 5; }
    to { transform: scale(1); }
  }
  /* the finding being discussed pulses */
  .map :global(path.eh-pulse) { transform-box: fill-box; transform-origin: center; animation: eh-pulse 1.8s ease-out infinite; }
  @keyframes eh-pulse {
    from { transform: scale(.6); opacity: .95; }
    to { transform: scale(2.4); opacity: 0; }
  }
  .map :global(path.eh-late) { animation: eh-late .5s ease-out both; }
  .map :global(path.eh-late.eh-pulse) { animation: eh-late .5s ease-out both, eh-pulse 1.8s ease-out infinite; }
  @keyframes eh-late { from { opacity: 0; } }
  @media (prefers-reduced-motion: reduce) {
    .map :global(path.eh-draw), .map :global(path.eh-ignite), .map :global(path.eh-pulse), .map :global(path.eh-late) { animation: none; }
  }
</style>
