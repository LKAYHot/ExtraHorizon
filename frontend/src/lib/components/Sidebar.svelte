<script>
  import { app } from '$lib/app.svelte.js'
  import { RotateCcw, GraduationCap, Server, Bot, ScanFace, LoaderCircle, Info, AudioLines, Ear, Drama, Languages } from '$lib/icons.js'
  import Logo from './Logo.svelte'
  import MicPicker from './MicPicker.svelte'
  import Select from './Select.svelte'

  const SUBJECTS = ['General', 'Computer Science', 'Mathematics', 'Physics', 'Chemistry', 'Biology', 'History', 'Economics', 'Language Learning']
  const SUBJECT_OPTIONS = SUBJECTS.map((s) => ({ value: s, label: s }))

  const llm = $derived(app.health?.llm)
  const tts = $derived(app.health?.tts ?? app.voice.info?.tts)
  const stt = $derived(app.health?.stt)
  const llmTone = $derived(
    !app.backendUp ? 'off' : !llm?.configured ? 'error' : llm.last_error ? 'warn' : llm.reachable === false ? 'error' : 'ok',
  )
  const llmText = $derived(
    !app.backendUp
      ? 'backend offline'
      : !llm
        ? 'checking…'
        : llm.provider === 'mock'
          ? 'Mock LLM (offline, scripted)'
          : !llm.configured
            ? 'API key missing (.env)'
            : `OpenAI · ${llm.model}`,
  )
  const ttsTone = $derived(!tts ? 'off' : !tts.configured ? 'error' : tts.state === 'ok' ? 'ok' : tts.state === 'off' ? 'off' : 'warn')
  const ttsText = $derived(
    !tts ? 'checking…'
      : tts.provider === 'mock' ? 'Mock voice (offline tone)'
        : !tts.configured ? 'FISH_API_KEY missing (.env)'
          : `Fish Audio · ${tts.model}${tts.state !== 'ok' ? ` · ${tts.state}` : ''}`,
  )
  const sttTone = $derived(!stt ? 'off' : !stt.configured || stt.vad === false ? 'error' : app.voice.mic === 'on' ? 'ok' : 'warn')
  const sttText = $derived(
    !stt ? 'checking…'
      : !stt.configured ? 'off (OPENAI_API_KEY / EH_STT_PROVIDER)'
        : stt.vad === false ? 'voice detection model missing — run setup'
          : `${stt.provider === 'mock' ? 'Mock STT' : stt.model} + Silero VAD · mic ${app.voice.mic}`,
  )
  const visionTone = $derived(
    app.vision.backend.available === false ? 'error' : app.vision.camera === 'active' && app.vision.socket === 'open' ? 'ok' : 'warn',
  )
  const visionText = $derived(
    app.vision.backend.available === false
      ? 'unavailable — chat still works'
      : app.vision.socket !== 'open'
        ? 'connecting…'
        : app.vision.camera === 'active'
          ? `${app.local ? 'local ' : ''}MediaPipe + emotion model · active`
          : `camera ${app.vision.camera}`,
  )
</script>

<aside class="sidebar" aria-label="ExtraHorizon navigation">
  <div class="brand">
    <Logo size={34} />
    <div class="name">
      <span class="chrome-text sheen">ExtraHorizon</span>
      <small>Emotion-aware voice tutor</small>
    </div>
  </div>

  <button class="btn primary reset" onclick={() => app.reset()} disabled={app.resetting} data-testid="reset">
    {#if app.resetting}<LoaderCircle size={15} class="spin" />{:else}<RotateCcw size={15} />{/if}
    New session
  </button>

  <section class="block">
    <div class="eyebrow"><Drama size={13} /> Tutor</div>
    <div class="persona raised" data-testid="persona">
      <div class="p-head"><span class="dot tone-accent"></span><strong>{app.persona}</strong><span class="chip tiny">tsundere · expert</span></div>
      <p>Prickly on the outside, rigorous on the inside. She answers aloud, reacts to your expression and can be interrupted any time — just start talking.</p>
      <div class="lang"><Languages size={12} /> Speaks English · understands Russian</div>
    </div>
    <div class="field">
      <span>Subject</span>
      <Select options={SUBJECT_OPTIONS} value={app.subject} onchange={(s) => app.setSubject(s)} label="Subject" testid="subject" />
    </div>
    <MicPicker />
    <label class="toggle" title="Show the voice-acting cues (e.g. [huffy and flustered]) as stage directions in the chat">
      <span class="switch">
        <input type="checkbox" checked={app.showCues} onchange={(e) => app.setShowCues(e.currentTarget.checked)} data-testid="show-cues" />
        <span class="track"></span><span class="knob"></span>
      </span>
      <span>Show voice cues</span>
    </label>
  </section>

  <section class="block status">
    <div class="eyebrow"><Info size={13} /> System</div>
    <div class="row"><Server size={14} /><span class="grow">Backend</span><span class="dot tone-{app.backendUp ? 'ok' : app.backendUp === false ? 'error' : 'warn'}"></span></div>
    <div class="sub">{app.backendUp ? (app.local ? 'local · FastAPI' : app.viaTunnel ? "presenter's PC · Cloudflare Tunnel" : `FastAPI · ${location.host}`) : app.backendUp === false ? 'offline — retrying…' : 'connecting…'}</div>
    <div class="row"><Bot size={14} /><span class="grow">Language model</span><span class="dot tone-{llmTone}"></span></div>
    <div class="sub" class:mock={llm?.provider === 'mock'}>{llmText}</div>
    {#if llm?.last_error}
      <div class="sub err">{llm.last_error.message}</div>
    {/if}
    <div class="row"><AudioLines size={14} /><span class="grow">Voice</span><span class="dot tone-{ttsTone}"></span></div>
    <div class="sub" class:mock={tts?.provider === 'mock'}>{ttsText}</div>
    {#if tts?.last_error}
      <div class="sub err">{tts.last_error}</div>
    {/if}
    <div class="row"><Ear size={14} /><span class="grow">Speech recognition</span><span class="dot tone-{sttTone}"></span></div>
    <div class="sub" class:mock={stt?.provider === 'mock'}>{sttText}</div>
    <div class="row"><ScanFace size={14} /><span class="grow">Vision</span><span class="dot tone-{visionTone}"></span></div>
    <div class="sub">{visionText}</div>
  </section>

  <footer class="note">
    <GraduationCap size={13} />
    <span>Facial-expression estimates are experimental and can be wrong — they describe how a face <strong>looks</strong>, not what anyone feels.</span>
  </footer>
</aside>

<style>
  .sidebar {
    display: flex; flex-direction: column; gap: 16px; min-height: 0; overflow-y: auto;
    padding: 18px 16px;
    background: linear-gradient(180deg, rgb(12 20 40 / .72), rgb(8 13 28 / .66));
    box-shadow: inset -1px 0 0 rgb(170 190 255 / .06), 30px 0 60px -40px rgb(0 0 10 / .9);
  }
  /* a column taller than the window scrolls — nothing gets squashed (e.g. the New session button) */
  .sidebar > * { flex-shrink: 0; }
  .brand { display: flex; align-items: center; gap: 10px; padding: 2px 2px 4px; }
  .name { display: flex; flex-direction: column; line-height: 1.15; }
  .name span { font: 700 19px/1.1 var(--font-display); letter-spacing: -.02em; }
  .name small { color: var(--muted); font-size: 11.5px; letter-spacing: .01em; }
  .reset { width: 100%; height: 38px; }
  .block { display: flex; flex-direction: column; gap: 10px; }
  .persona { border-radius: var(--radius-sm); padding: 10px 12px; }
  .p-head { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
  .chip.tiny { height: 20px; padding: 0 7px; font-size: 10.5px; margin-left: auto; }
  .persona p { margin: 6px 0 6px; color: var(--muted); font-size: 12px; line-height: 1.45; }
  .lang { display: flex; align-items: center; gap: 5px; font-size: 11px; color: var(--faint); }
  .field { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--muted); }
  .toggle { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--text-2); cursor: pointer; }
  .status .row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); }
  .status .row :global(svg) { color: var(--muted); }
  .status .sub { margin: -6px 0 2px 22px; font-size: 11.5px; color: var(--faint); overflow-wrap: anywhere; }
  .status .sub.mock { color: var(--warn); }
  .status .sub.err { color: var(--error); }
  .note { margin-top: auto; display: flex; gap: 7px; align-items: flex-start; font-size: 11.5px; line-height: 1.5; color: var(--faint); border-top: 1px solid var(--line); padding-top: 12px; }
  .note :global(svg) { flex: 0 0 auto; margin-top: 2px; }
  .note strong { color: var(--muted); }

  @media (max-width: 1199px) {
    .sidebar { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 12px 16px; padding: 10px 14px; overflow: visible; }
    .sidebar > * { flex-shrink: 1; }
    .reset { width: auto; }
    .persona, .note, .status, .eyebrow { display: none; }
    .block { flex-direction: row; align-items: center; }
    .field, .sidebar :global(.picker) { flex-direction: row; align-items: center; }
  }
</style>
