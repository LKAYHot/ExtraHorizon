<script>
  import { app } from '$lib/app.svelte.js'
  import { fmt2 } from '$lib/format.js'
  import { ChevronDown, Cpu } from '$lib/icons.js'

  let open = $state(false)
  const t = $derived(app.vision.camera === 'active' ? app.visionTick : null)
  const ROWS = [
    ['brow_lower', 'Brow lowering', '≈ AU4 · main cue'],
    ['lid_tighten', 'Lid tightening', '≈ AU7'],
    ['lip_press', 'Lip press', '≈ AU24'],
    ['smile', 'Smile', 'suppresses the proxy'],
  ]
</script>

<section class="card det">
  <button class="head" onclick={() => (open = !open)} aria-expanded={open}>
    <span class="eyebrow"><Cpu size={13} /> Signal details (how the proxy is computed)</span>
    <ChevronDown size={15} class="chev" />
  </button>
  {#if open}
    <p class="lead">
      MediaPipe Face Landmarker (local) gives expression coefficients. The proxy combines their rise above
      <strong>your own neutral baseline</strong> (captured for {app.vision.config.calibration_s} s) — it is a heuristic, not an emotion classifier.
    </p>
    {#if t?.features}
      <table>
        <thead><tr><th>cue</th><th>now</th><th>baseline</th><th>adds</th></tr></thead>
        <tbody>
          {#each ROWS as [k, label, note] (k)}
            <tr>
              <td>{label}<span class="note">{note}</span></td>
              <td class="num">{fmt2(t.features[k])}</td>
              <td class="num">{t.baseline ? fmt2(t.baseline[k]) : '—'}</td>
              <td class="num">{k === 'smile' ? (t.contrib ? `×${fmt2(t.contrib.smile_factor)}` : '—') : t.contrib ? fmt2(t.contrib[k]) : '—'}</td>
            </tr>
          {/each}
        </tbody>
      </table>
      <div class="meta num">
        {#if t.pose}yaw {t.pose.yaw}° · pitch {t.pose.pitch}° · {/if}{#if t.brightness != null}light {Math.round(t.brightness)} · {/if}analysis {t.proc_ms} ms
      </div>
    {:else}
      <p class="faint small">No face measurements right now ({app.vision.camera === 'active' ? 'no usable face' : 'camera not active'}).</p>
    {/if}
  {/if}
</section>

<style>
  .det { padding: 4px 12px; }
  .head { display: flex; align-items: center; justify-content: space-between; width: 100%; padding: 8px 0; border: 0; background: none; color: var(--muted); text-align: left; }
  .head :global(.chev) { transition: transform var(--t2) var(--ease); }
  .head[aria-expanded='false'] :global(.chev) { transform: rotate(-90deg); }
  .lead { margin: 0 0 8px; font-size: 12px; color: var(--muted); line-height: 1.5; }
  .lead strong { color: var(--text-2); }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { text-align: left; color: var(--faint); font-weight: 600; padding: 3px 4px; border-bottom: 1px solid var(--line-2); }
  td { padding: 4px; border-bottom: 1px solid var(--line); color: var(--text-2); vertical-align: top; }
  .note { display: block; font-size: 10.5px; color: var(--faint); }
  .meta { margin: 8px 0 10px; font-size: 11px; color: var(--faint); }
  .small { font-size: 12px; margin: 0 0 10px; }
</style>
