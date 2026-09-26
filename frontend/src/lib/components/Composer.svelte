<script>
  import { app } from '$lib/app.svelte.js'
  import { ArrowUp, Square, Mic, MicOff, LoaderCircle, Hand, Ear } from '$lib/icons.js'
  import MicPicker from './MicPicker.svelte'

  let text = $state('')
  let ta = $state(null)
  let asking = $state(false) // microphone disclosure open
  const v = app.voice
  const ready = $derived(!!text.trim() && !app.busy)
  const canStop = $derived(app.busy || app.talkState === 'speaking' || app.talkState === 'thinking')
  const micOn = $derived(v.mic === 'on')
  const showDock = $derived(micOn || v.mic === 'starting' || !!v.caption.text || !!v.notice || ['denied', 'unavailable', 'error'].includes(v.mic) || asking)

  function autogrow() {
    if (!ta) return
    ta.style.height = 'auto'
    ta.style.height = Math.min(ta.scrollHeight, 180) + 'px'
    ta.style.overflowY = ta.scrollHeight > 180 ? 'auto' : 'hidden'
  }

  async function send() {
    if (!ready) return
    const ok = await app.send(text)
    if (ok) {
      text = ''
      queueMicrotask(autogrow)
    }
    ta?.focus()
  }

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault()
      send()
    }
  }

  function micClick() {
    if (!v.consented && v.mic !== 'on') {
      asking = !asking
      return
    }
    v.toggleMic()
  }

  function consent() {
    asking = false
    v.consent()
  }
</script>

<div class="dock">
  {#if showDock}
    <div class="voice card" data-testid="voice-dock">
      {#if asking}
        <div class="consent" data-testid="mic-consent">
          <p class="lead"><Mic size={14} /> Talk to {app.persona} hands-free</p>
          <ul>
            <li>Your microphone audio goes to {app.local ? "this computer's ExtraHorizon backend, where speech is detected locally" : `the ExtraHorizon backend at ${location.host}, where speech is detected`} (Silero VAD).</li>
            <li>Only the parts where you speak are sent to <strong>OpenAI</strong> for transcription (gpt-live-transcribe). Nothing is recorded or stored.</li>
            <li>Speak over her to interrupt; say “wait, stop” to just make her stop. Headphones avoid echo.</li>
          </ul>
          <div class="row">
            <button class="btn primary sm" onclick={consent} data-testid="mic-on"><Mic size={13} /> Turn on microphone</button>
            <button class="btn sm ghost" onclick={() => (asking = false)}>Not now</button>
            <span class="grow"></span>
            <MicPicker compact />
          </div>
        </div>
      {:else if ['denied', 'unavailable', 'error'].includes(v.mic)}
        <div class="line warn" data-testid="mic-error"><MicOff size={14} /> {v.micMessage || 'The microphone is unavailable.'}</div>
      {:else}
        <div class="line state" data-testid="voice-state">
          <span class="state-text">
          {#if v.hearing}
            <span class="dot tone-ok pulse"></span> Hearing you…
          {:else if app.talkState === 'thinking'}
            <span class="dot tone-accent pulse"></span> {app.persona} is thinking{#if v.filler}<em>&nbsp;— “{v.filler}”</em>{/if}
          {:else if app.talkState === 'speaking'}
            <span class="dot tone-accent"></span> {app.persona} is speaking — talk over her to interrupt
          {:else if micOn}
            <Ear size={13} /> Listening — just start talking (English or Russian)
          {:else if v.mic === 'starting'}
            <LoaderCircle size={13} class="spin" /> Starting the microphone…
          {/if}
          </span>
          {#if micOn || v.mic === 'starting'}<MicPicker compact />{/if}
        </div>
        {#if v.caption.text}
          <div class="caption" class:final={v.caption.final} data-testid="live-caption">“{v.caption.text}”</div>
        {/if}
        {#if v.notice}
          <div class="line notice" data-testid="voice-notice"><Hand size={13} /> {v.notice.text}</div>
        {/if}
      {/if}
    </div>
  {/if}

  <div class="card composer">
    <button class="mic" class:on={micOn} class:busy={v.mic === 'starting'} style:--lvl={micOn ? v.level : 0}
            onclick={micClick} aria-pressed={micOn} data-testid="mic-toggle"
            title={micOn ? 'Microphone on — hands-free conversation (click to turn off)' : 'Talk instead of typing'}
            aria-label={micOn ? 'Turn the microphone off' : 'Turn the microphone on'}>
      {#if v.mic === 'starting'}<LoaderCircle size={17} class="spin" />{:else if micOn}<Mic size={17} />{:else}<MicOff size={17} />{/if}
    </button>
    <textarea
      bind:this={ta}
      bind:value={text}
      rows="1"
      oninput={autogrow}
      onkeydown={onKey}
      placeholder={micOn ? 'Talk, or type here… (Enter to send)' : 'Ask anything… (Enter to send, Shift+Enter for a new line)'}
      aria-label="Message to the tutor"
      maxlength="4000"
      data-testid="composer"
    ></textarea>
    {#if canStop}
      <button class="send stop" onclick={() => app.stopAnswer()} aria-label="Stop her answer" title="Stop (Esc)" data-testid="stop"><Square size={13} fill="currentColor" /></button>
    {/if}
    <button class="send" class:ready onclick={send} disabled={!ready} aria-label="Send" title="Send (Enter)" data-testid="send">
      <ArrowUp size={18} strokeWidth={2.4} />
    </button>
  </div>
  <p class="fine">Answers: OpenAI · voice: Fish Audio · speech-to-text: OpenAI. Camera frames {app.local ? 'stay on this computer' : 'go to the ExtraHorizon backend'} — only a short text description of your expression reaches the model.</p>
</div>

<style>
  .dock { padding: 8px 22px 14px; max-width: calc(var(--feed-w) + 44px); width: 100%; margin: 0 auto; display: flex; flex-direction: column; gap: 8px; }
  .voice { padding: 9px 13px; display: flex; flex-direction: column; gap: 5px; animation: eh-rise .3s var(--ease) both; }
  .line { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--muted); }
  .line em { font-style: italic; color: var(--text-2); }
  .line.state { justify-content: space-between; flex-wrap: wrap; row-gap: 4px; }
  .state-text { display: inline-flex; align-items: center; gap: 7px; min-width: 0; }
  .line.warn { color: var(--warn); }
  .line.notice { color: #f2d7a8; }
  .caption { font-size: 14px; color: var(--muted); font-style: italic; line-height: 1.45; overflow-wrap: anywhere; }
  .caption.final { color: var(--text); font-style: normal; }
  .consent .lead { margin: 0 0 4px; display: flex; align-items: center; gap: 6px; font-weight: 600; color: var(--text-2); font-size: 13px; }
  .consent ul { margin: 0 0 8px; padding-left: 18px; font-size: 12px; color: var(--muted); line-height: 1.5; display: flex; flex-direction: column; gap: 2px; }
  .consent strong { color: var(--text-2); }
  .row { display: flex; gap: 8px; }

  .composer {
    position: relative; display: flex; align-items: flex-end; gap: 10px;
    padding: 10px 10px 10px 10px; border-radius: var(--radius-lg);
    background: var(--sheen), var(--plane-hi); box-shadow: var(--ring-2), var(--rise-3);
    transition: box-shadow var(--t3) var(--ease);
  }
  /* focus: a beam of light runs along the border (blue → violet) */
  .composer::before {
    content: ''; position: absolute; inset: 0; border-radius: inherit; padding: 1px; pointer-events: none;
    background: conic-gradient(from var(--beam), transparent 0 56%, rgb(122 152 255 / .25) 74%, rgb(165 139 255 / .95) 99%, transparent 100%);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor; mask-composite: exclude;
    opacity: 0; transition: opacity var(--t3) var(--ease);
  }
  .composer:focus-within::before { opacity: 1; animation: eh-beam 5s linear infinite; }
  .composer:focus-within { box-shadow: var(--ring-2), var(--rise-3), 0 0 44px -22px var(--halo); }
  textarea {
    flex: 1 1 auto; min-width: 0; resize: none; border: 0; outline: none; background: transparent;
    padding: 6px 0; min-height: 34px; max-height: 180px; line-height: 1.5; font-size: 15px; color: var(--text); overflow-y: hidden;
  }
  textarea::placeholder { color: var(--faint); }
  .mic {
    position: relative; flex: 0 0 auto; width: 36px; height: 36px; border-radius: 50%; border: 0; display: grid; place-items: center;
    background: var(--sheen), var(--raise); color: var(--muted); box-shadow: var(--ring), var(--rise-1);
    transition: background var(--t2) var(--ease), color var(--t2) var(--ease), box-shadow var(--t2) var(--ease);
  }
  .mic::after {
    content: ''; position: absolute; inset: -4px; border-radius: 50%; pointer-events: none;
    box-shadow: 0 0 0 2px rgb(95 203 159 / .75); opacity: 0;
    transform: scale(calc(.92 + var(--lvl) * .3)); transition: transform 80ms linear, opacity var(--t2) var(--ease);
  }
  .mic.on { background: linear-gradient(180deg, #5fcb9f, #3fa57c); color: #04130d; box-shadow: 0 0 0 1px rgb(95 203 159 / .5), 0 8px 22px -10px rgb(95 203 159 / .6); }
  .mic.on::after { opacity: calc(.25 + var(--lvl) * .75); }
  .mic:hover { color: var(--text); }
  .mic.on:hover { color: #04130d; }
  .send {
    flex: 0 0 auto; width: 36px; height: 36px; border-radius: 11px; border: 0; display: grid; place-items: center;
    background: var(--sheen), var(--raise); color: var(--faint); box-shadow: var(--ring), var(--rise-1);
    transition: transform var(--t2) var(--spring), background var(--t2) var(--ease), color var(--t2) var(--ease), box-shadow var(--t2) var(--ease);
  }
  .send.ready { background: var(--primary-bg); color: var(--primary-ink); box-shadow: var(--primary-rise); }
  .send.ready:hover { transform: translateY(-1px) scale(1.04); }
  .send.stop { color: var(--error); box-shadow: 0 0 0 1px color-mix(in srgb, var(--error) 40%, transparent), var(--rise-1); }
  .fine { margin: 0 4px; font-size: 11px; color: var(--faint); text-align: center; }
  @media (max-width: 859px) { .dock { padding: 8px 12px 12px; position: sticky; bottom: 0; background: linear-gradient(180deg, transparent, var(--bg) 30%); } }
</style>
