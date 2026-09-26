<script>
  import { app } from '$lib/app.svelte.js'
  import { RotateCcw, GraduationCap, Server, Bot, ScanFace, LoaderCircle, WandSparkles, Info } from '$lib/icons.js'
  import Logo from './Logo.svelte'

  const SUBJECTS = ['General', 'Computer Science', 'Mathematics', 'Physics', 'Chemistry', 'Biology', 'History', 'Economics', 'Language Learning']

  const llm = $derived(app.health?.llm)
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
  const visionTone = $derived(
    app.vision.backend.available === false ? 'error' : app.vision.camera === 'active' && app.vision.socket === 'open' ? 'ok' : 'warn',
  )
  const visionText = $derived(
    app.vision.backend.available === false
      ? 'unavailable — chat still works'
      : app.vision.socket !== 'open'
        ? 'connecting…'
        : app.vision.camera === 'active'
          ? `${app.local ? 'local ' : ''}MediaPipe · active`
          : `camera ${app.vision.camera}`,
  )
</script>

<aside class="sidebar" aria-label="ExtraHorizon navigation">
  <div class="brand">
    <Logo size={34} />
    <div class="name">
      <span class="chrome-text sheen">ExtraHorizon</span>
      <small>Adaptive AI tutor</small>
    </div>
  </div>

  <button class="btn primary reset" onclick={() => app.reset()} disabled={app.resetting} data-testid="reset">
    {#if app.resetting}<LoaderCircle size={15} class="spin" />{:else}<RotateCcw size={15} />{/if}
    New session / Reset demo
  </button>

  <section class="block">
    <div class="eyebrow"><GraduationCap size={13} /> Mode</div>
    <div class="mode raised">
      <div class="mode-head"><span class="dot tone-accent"></span><strong>Adaptive Tutor</strong></div>
      <p>Answers normally. When a sustained <em>possible-confusion</em> signal is measured after an answer, it offers to explain differently.</p>
    </div>
    <label class="field">
      <span>Subject</span>
      <select class="select" value={app.subject} onchange={(e) => app.setSubject(e.currentTarget.value)} data-testid="subject">
        {#each SUBJECTS as s (s)}<option value={s}>{s}</option>{/each}
      </select>
    </label>
    <label class="toggle" title="After a detected event, start the re-explanation automatically after a 3 s countdown (you can cancel).">
      <span class="switch">
        <input type="checkbox" checked={app.autoAdapt} onchange={(e) => app.setAutoAdapt(e.currentTarget.checked)} />
        <span class="track"></span><span class="knob"></span>
      </span>
      <span><WandSparkles size={13} /> Auto-adapt <small class="faint">(beta, off by default)</small></span>
    </label>
  </section>

  <section class="block status">
    <div class="eyebrow"><Info size={13} /> System</div>
    <div class="row"><Server size={14} /><span class="grow">Backend</span><span class="dot tone-{app.backendUp ? 'ok' : app.backendUp === false ? 'error' : 'warn'}"></span></div>
    <div class="sub">{app.backendUp ? (app.local ? 'local · FastAPI' : `FastAPI · ${location.host}`) : app.backendUp === false ? 'offline — retrying…' : 'connecting…'}</div>
    <div class="row"><Bot size={14} /><span class="grow">Language model</span><span class="dot tone-{llmTone}"></span></div>
    <div class="sub" class:mock={llm?.provider === 'mock'}>{llmText}</div>
    {#if llm?.last_error}
      <div class="sub err">{llm.last_error.message}</div>
    {/if}
    <div class="row"><ScanFace size={14} /><span class="grow">Vision</span><span class="dot tone-{visionTone}"></span></div>
    <div class="sub">{visionText}</div>
  </section>

  <footer class="note">
    Experimental estimate of visible behavioural cues — <strong>not</strong> a reading of anyone's inner state.
  </footer>
</aside>

<style>
  .sidebar {
    display: flex; flex-direction: column; gap: 18px; min-height: 0; overflow-y: auto;
    padding: 18px 16px;
    background: linear-gradient(180deg, rgb(12 20 40 / .72), rgb(8 13 28 / .66));
    box-shadow: inset -1px 0 0 rgb(170 190 255 / .06), 30px 0 60px -40px rgb(0 0 10 / .9);
  }
  .brand { display: flex; align-items: center; gap: 10px; padding: 2px 2px 4px; }
  .name { display: flex; flex-direction: column; line-height: 1.15; }
  .name span { font: 700 19px/1.1 var(--font-display); letter-spacing: -.02em; }
  .name small { color: var(--muted); font-size: 11.5px; letter-spacing: .01em; }
  .reset { width: 100%; height: 38px; }
  .block { display: flex; flex-direction: column; gap: 10px; }
  .mode { border-radius: var(--radius-sm); padding: 10px 12px; }
  .mode-head { display: flex; align-items: center; gap: 8px; font-size: 13.5px; }
  .mode p { margin: 6px 0 0; color: var(--muted); font-size: 12px; line-height: 1.45; }
  .mode em { color: var(--text-2); font-style: normal; }
  .field { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--muted); }
  .toggle { display: flex; align-items: center; gap: 10px; font-size: 12.5px; color: var(--text-2); cursor: pointer; }
  .toggle > span:last-child { display: inline-flex; align-items: center; gap: 5px; flex-wrap: wrap; }
  .status .row { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--text-2); }
  .status .row :global(svg) { color: var(--muted); }
  .status .sub { margin: -6px 0 2px 22px; font-size: 11.5px; color: var(--faint); overflow-wrap: anywhere; }
  .status .sub.mock { color: var(--warn); }
  .status .sub.err { color: var(--error); }
  .note { margin-top: auto; font-size: 11.5px; line-height: 1.5; color: var(--faint); border-top: 1px solid var(--line); padding-top: 12px; }
  .note strong { color: var(--muted); }

  @media (max-width: 1199px) {
    .sidebar { flex-direction: row; flex-wrap: wrap; align-items: center; gap: 12px 16px; padding: 10px 14px; overflow: visible; }
    .reset { width: auto; }
    .mode, .note, .status, .eyebrow { display: none; }
    .block { flex-direction: row; align-items: center; }
    .field { flex-direction: row; align-items: center; }
  }
</style>
