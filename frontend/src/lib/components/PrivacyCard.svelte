<script>
  import { app } from '$lib/app.svelte.js'
  import { isLoopbackHost } from '$lib/format.js'
  import { ShieldCheck, ShieldAlert } from '$lib/icons.js'

  const pageLocal = typeof location !== 'undefined' && isLoopbackHost(location.hostname)
  // the claim is shown only when BOTH sides confirm a loopback path (page host + backend's view of us)
  const local = $derived(pageLocal && app.vision.clientIsLoopback === true)
  const provider = $derived(app.health?.llm?.provider === 'mock' ? 'nobody (offline mock LLM)' : 'OpenAI')
</script>

<section class="card privacy" class:remote={!local} data-testid="privacy-card">
  <div class="eyebrow">
    {#if local}<ShieldCheck size={13} />{:else}<ShieldAlert size={13} />{/if} Privacy — what goes where
  </div>
  <ul>
    {#if local}
      <li><strong>Camera video stays on this computer.</strong> Frames are downsized in the browser and sent over a localhost WebSocket to the ExtraHorizon Python process, analysed in memory and discarded — never saved.</li>
    {:else}
      <li class="warn"><strong>The vision backend is not on this device</strong> ({location.host}). Camera frames travel over the network to it — the "video never leaves this device" claim does not apply here.</li>
    {/if}
    <li><strong>Sent to {provider}:</strong> your chat messages, the tutor's earlier answers in this session and — only after you click <em>Explain differently</em> — a short note asking for another explanation style. No images, face data or signal numbers.</li>
    <li><strong>Sent to Google by the MediaPipe library:</strong> anonymous usage metrics (e.g. frame counts, latency, OS/Python version) while the camera is on — per <a href="https://developers.google.com/edge/mediapipe/solutions/tasks#mediapipe_tasks_privacy_notice" target="_blank" rel="noopener noreferrer">Google's notice</a>, never the images or video.</li>
    <li><strong>Not stored:</strong> sessions live in memory; <em>Reset demo</em> or closing the backend deletes them.</li>
  </ul>
</section>

<style>
  .privacy { padding: 12px 14px; }
  .privacy.remote { box-shadow: 0 0 0 1px color-mix(in srgb, var(--warn) 40%, transparent), var(--rise-1); }
  ul { margin: 8px 0 0; padding-left: 16px; display: flex; flex-direction: column; gap: 6px; font-size: 12px; line-height: 1.5; color: var(--muted); }
  li::marker { color: var(--accent); }
  strong { color: var(--text-2); font-weight: 600; }
  em { font-style: normal; color: var(--text-2); }
  .warn { color: var(--warn); }
</style>
