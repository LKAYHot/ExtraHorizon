<script>
  import { app } from '$lib/app.svelte.js'
  import { HeartPulse, TriangleAlert, RefreshCw } from '$lib/icons.js'
  import CameraCard from './CameraCard.svelte'
  import EmotionNow from './EmotionNow.svelte'
  import Circumplex from './Circumplex.svelte'
  import EmotionTimeline from './EmotionTimeline.svelte'
  import PromptCard from './PromptCard.svelte'
  import SimulationCard from './SimulationCard.svelte'
  import PrivacyCard from './PrivacyCard.svelte'

  const v = app.vision
  const REASONS = {
    disabled: 'Vision is switched off on the server (EH_VISION_ENABLED=false / --no-vision).',
    model_missing: 'A vision model file is missing — run setup (model download).',
    model_download_failed: 'A vision model could not be downloaded (offline?) — run setup again when online.',
    model_checksum_mismatch: 'A downloaded model failed its checksum — run setup again.',
  }
  const reasonText = (r) => (r ? (REASONS[r] ?? (r.startsWith('mediapipe_error') ? 'MediaPipe could not start on this machine — see the backend log.' : r)) : '')
  const banner = $derived.by(() => {
    if (v.socket === 'superseded' || app.voice.socket === 'superseded') return { text: 'This session is open in another tab.', action: 'Use here' }
    if (v.backend.available === false) return { text: 'Vision unavailable — chat and voice still work.', detail: reasonText(v.backend.reason) }
    if (v.socket === 'closed' && app.backendUp === false) return { text: 'Backend offline — reconnecting…' }
    if (['denied', 'unavailable', 'ended'].includes(v.camera)) return { text: 'Camera unavailable — chat and voice still work.', detail: v.cameraMessage }
    return null
  })

  function useHere() {
    v.reconnectNow()
    app.voice.reconnectNow()
  }
</script>

<aside class="panel" aria-label="Facial expression (estimate)">
  <header class="head">
    <div class="title"><HeartPulse size={16} /> <h2>Expression</h2><span class="chip">{app.local ? 'on-device · estimate' : 'estimate'}</span></div>
  </header>
  {#if banner}
    <div class="banner" role="status" data-testid="vision-banner">
      <TriangleAlert size={15} />
      <div class="grow"><strong>{banner.text}</strong>{#if banner.detail}<div class="detail">{banner.detail}</div>{/if}</div>
      {#if banner.action}<button class="btn sm" onclick={useHere}><RefreshCw size={13} /> {banner.action}</button>{/if}
    </div>
  {/if}
  <div class="stack">
    <CameraCard />
    <EmotionNow />
    <Circumplex />
    <EmotionTimeline />
    <PromptCard />
    <SimulationCard />
    <PrivacyCard />
  </div>
</aside>

<style>
  .panel {
    display: flex; flex-direction: column; min-height: 0; overflow-y: auto;
    background: linear-gradient(180deg, rgb(12 20 40 / .55), rgb(8 13 28 / .5));
    box-shadow: inset 1px 0 0 rgb(170 190 255 / .06), -30px 0 60px -40px rgb(0 0 10 / .9);
  }
  /* sticky header is opaque (nothing may show through it) with a soft shadow the content slides under */
  .head { position: sticky; top: 0; z-index: 3; padding: 14px 14px 10px; background: #0a1122; box-shadow: 0 10px 16px -12px rgb(0 0 10 / .8); margin-bottom: 4px; }
  .title { display: flex; align-items: center; gap: 8px; color: var(--muted); }
  h2 { font-size: 15px; font-weight: 650; color: var(--text); }
  .banner {
    display: flex; align-items: flex-start; gap: 9px; margin: 0 14px 10px; padding: 9px 11px; border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--warn) 10%, var(--plane)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--warn) 35%, transparent);
    font-size: 12.5px; color: var(--text-2); animation: eh-fade .3s var(--ease) both;
  }
  .banner :global(svg) { flex: 0 0 auto; color: var(--warn); margin-top: 1px; }
  .detail { color: var(--muted); font-size: 11.5px; margin-top: 2px; }
  .stack { display: flex; flex-direction: column; gap: 12px; padding: 0 14px 16px; }
  @media (max-width: 859px) { .panel { overflow: visible; } }
</style>
