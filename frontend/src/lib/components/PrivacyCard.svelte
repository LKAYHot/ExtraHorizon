<script>
  import { app } from '$lib/app.svelte.js'
  import { isLoopbackHost } from '$lib/format.js'
  import { ShieldCheck, ShieldAlert } from '$lib/icons.js'

  const pageLocal = typeof location !== 'undefined' && isLoopbackHost(location.hostname)
  // the claim is shown only when BOTH sides confirm a loopback path (page host + backend's view of us)
  const local = $derived(pageLocal && app.vision.clientIsLoopback === true)
  const llm = $derived(app.health?.llm?.provider === 'mock' ? 'nobody (offline mock LLM)' : 'OpenAI')
  const tts = $derived(app.health?.tts?.provider === 'mock' ? 'nobody (offline mock voice)' : 'Fish Audio')
  const stt = $derived(app.health?.stt?.provider === 'mock' ? 'nobody (offline mock transcription)' : 'OpenAI')
</script>

<section class="card privacy" class:remote={!local} data-testid="privacy-card">
  <div class="eyebrow">
    {#if local}<ShieldCheck size={13} />{:else}<ShieldAlert size={13} />{/if} Privacy — what goes where
  </div>
  <ul>
    {#if local}
      <li><strong>Camera video stays on this computer.</strong> Frames are downsized in the browser, sent over a localhost WebSocket to the ExtraHorizon Python process, analysed in memory (MediaPipe face landmarks + an on-device expression model) and discarded — never saved.</li>
    {:else if app.viaTunnel}
      <li class="warn" data-testid="privacy-tunnel"><strong>Camera video goes to the presenter's computer.</strong> Frames are downsized in this browser and sent over HTTPS to <strong>Cloudflare</strong>, which forwards them through an encrypted tunnel (Cloudflare Tunnel) to the ExtraHorizon server — Cloudflare decrypts and re-encrypts the traffic in between. There they are analysed in memory (MediaPipe + an expression model) and discarded — never saved.</li>
    {:else}
      <li class="warn"><strong>The vision backend is not on this device</strong> ({location.host}). Camera frames travel over the network to it — the "video never leaves this device" claim does not apply here.</li>
    {/if}
    <li><strong>Microphone:</strong> audio goes to the ExtraHorizon backend{app.viaTunnel ? ' (the same way, through Cloudflare)' : ''}, which detects speech{local ? ' locally' : ''}; only the parts where you speak are sent to {stt} for transcription. Nothing is recorded.</li>
    <li><strong>Sent to {llm}:</strong> your messages (typed or transcribed), her earlier answers and a short words-only description of your apparent expression (e.g. “looks relaxed”, “frowning”). No images, landmarks or numbers.</li>
    <li><strong>Sent to {tts}:</strong> the text of her answers, to speak them in her voice.</li>
    <li data-testid="privacy-coord"><strong>Utility-coordination analysis</strong> (only when you use it): the server reads Miami-Dade County's public open data from ArcGIS Online — nothing about you is sent; the verified public facts about the projects go to {llm} so she can explain them; the map tiles are loaded by this browser from OpenStreetMap's tile servers, which see your IP address.</li>
    <li data-testid="privacy-hub"><strong>Hackathon hub</strong> (only when you use it): for a roadblock the server sends a short search made from the error — your file paths, addresses, ports, e-mails and key-like strings removed — to Stack Overflow (Stack Exchange API), GitHub, the npm registry and PyPI; learning searches send the topic words to GitHub, DEV Community and Stack Overflow. When you look for teammates, the server asks GitHub for public profiles by the language you need and the event's city and reads the first few profiles' public repositories (never anyone's e-mail, links or bio text); for mentors it reads Stack Overflow's top answerers for your stack; the help board reads Stack Overflow's unsolved questions for your stack. The verified results — and those public profiles — go to {llm} so she can explain them. What you put on the board (your card, help requests, shared fixes) is kept on this server, visible to everyone using this app, until you delete it; when someone asks for teammates, the matching cards (not the contact line) go to {llm}. Your GitHub username is sent to GitHub only if you tick the box.</li>
    <li><strong>Sent to Google by the MediaPipe library:</strong> anonymous usage metrics (e.g. frame counts, latency, OS/Python version) while the camera is on — per <a href="https://developers.google.com/edge/mediapipe/solutions/tasks#mediapipe_tasks_privacy_notice" target="_blank" rel="noopener noreferrer">Google's notice</a>, never the images or video.</li>
    <li><strong>Not stored:</strong> sessions live in memory; <em>New session</em> or closing the backend deletes them. The only thing kept is what you put on the hackathon board, until you delete it.</li>
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
