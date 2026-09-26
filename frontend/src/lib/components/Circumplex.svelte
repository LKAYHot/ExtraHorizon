<script>
  import { app } from '$lib/app.svelte.js'
  import { signed } from '$lib/format.js'
  import { COLOR, LABEL, arousalWord, valenceWord } from '$lib/emotions.js'
  import { Compass } from '$lib/icons.js'

  const TRAIL_MS = 20_000
  let width = $state(320)
  const H = $derived(Math.round(Math.min(200, Math.max(150, width * 0.56))))
  const M = { l: 12, r: 12, t: 18, b: 20 }
  const pw = $derived(Math.max(60, width - M.l - M.r))
  const ph = $derived(H - M.t - M.b)
  const x = (v) => M.l + ((v + 1) / 2) * pw
  const y = (a) => M.t + (1 - (a + 1) / 2) * ph

  const e = $derived(app.emotion)
  const known = $derived(e?.status === 'ok' && e.valence != null && e.arousal != null)

  // recent path (measured samples only; a gap breaks the line)
  const trail = $derived.by(() => {
    void app.timelineVersion
    const s = app.timeline.samples
    const last = s.at(-1)?.[0] ?? 0
    const segs = []
    let cur = null
    let prevT = null
    for (let i = s.length - 1; i >= 0; i--) {
      const [t, status, , , , v, a] = s[i]
      if (t < last - TRAIL_MS) break
      const gap = prevT !== null && prevT - t > 1500
      prevT = t
      if (status !== 'ok' || v == null || a == null) {
        cur = null
        continue
      }
      if (!cur || gap) segs.push((cur = []))
      cur.push(`${x(v).toFixed(1)},${y(a).toFixed(1)}`)
    }
    return segs.filter((g) => g.length > 1).map((g) => g.join(' '))
  })
</script>

<section class="card spot cx" data-testid="circumplex">
  <div class="top">
    <div class="eyebrow"><Compass size={13} /> Mood map <em>valence × energy</em></div>
  </div>
  <div class="plot" bind:clientWidth={width}>
    <svg width={width} height={H} role="img"
         aria-label={known ? `Mood: ${valenceWord(e.valence)}, ${arousalWord(e.arousal)}` : 'Mood unknown'}>
      <rect class="bg" x={M.l} y={M.t} width={pw} height={ph} rx="8" />
      <line class="axis" x1={M.l} x2={M.l + pw} y1={y(0)} y2={y(0)} />
      <line class="axis" x1={x(0)} x2={x(0)} y1={M.t} y2={M.t + ph} />
      <text class="q" x={M.l + pw - 6} y={M.t + 13} text-anchor="end">excited</text>
      <text class="q" x={M.l + 6} y={M.t + 13}>tense</text>
      <text class="q" x={M.l + 6} y={M.t + ph - 6}>down</text>
      <text class="q" x={M.l + pw - 6} y={M.t + ph - 6} text-anchor="end">content</text>
      <text class="ax" x={x(0)} y={M.t - 6} text-anchor="middle">more energy ↑</text>
      <text class="ax" x={x(0)} y={M.t + ph + 13} text-anchor="middle">calmer ↓</text>
      <text class="ax" x={M.l} y={M.t + ph + 13}>← unpleasant</text>
      <text class="ax" x={M.l + pw} y={M.t + ph + 13} text-anchor="end">pleasant →</text>
      {#each trail as pts, i (i)}
        <polyline class="trail" points={pts} />
      {/each}
      {#if known}
        <circle class="dot" cx={x(e.valence)} cy={y(e.arousal)} r="6.5" style:fill={COLOR[e.dominant] ?? 'var(--text-2)'}>
          <title>{LABEL[e.dominant] ?? 'Current'} · valence {signed(e.valence)} · energy {signed(e.arousal)}</title>
        </circle>
      {/if}
    </svg>
  </div>
  <div class="read num" data-testid="va-readout">
    {#if known}
      <span>valence <strong>{signed(e.valence)}</strong> ({valenceWord(e.valence)})</span>
      <span>energy <strong>{signed(e.arousal)}</strong> ({arousalWord(e.arousal)})</span>
    {:else}
      <span class="faint">unknown — no measured face</span>
    {/if}
  </div>
</section>

<style>
  .cx { padding: 12px 12px 10px; display: flex; flex-direction: column; gap: 6px; }
  .top { display: flex; align-items: center; justify-content: space-between; }
  .eyebrow em { font-style: italic; text-transform: none; letter-spacing: 0; font-weight: 500; color: var(--muted); }
  .plot { border-radius: 10px; background: var(--viz-surface); box-shadow: var(--sink); overflow: hidden; }
  svg { display: block; }
  .bg { fill: none; }
  .axis { stroke: var(--viz-grid); stroke-width: 1; }
  .q { fill: var(--faint); font-size: 10px; }
  .ax { fill: var(--muted); font-size: 9.5px; }
  .trail { fill: none; stroke: var(--muted); stroke-width: 1.5; stroke-linejoin: round; stroke-linecap: round; opacity: .45; }
  .dot { stroke: var(--viz-surface); stroke-width: 2; transition: cx .18s linear, cy .18s linear, fill var(--t3) var(--ease); }
  .read { display: flex; justify-content: space-between; gap: 8px; font-size: 11.5px; color: var(--muted); }
  .read strong { color: var(--text); font-weight: 650; }
</style>
