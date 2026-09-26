<script>
  import { app } from '$lib/app.svelte.js'
  import { ArrowUp, Square } from '$lib/icons.js'

  let text = $state('')
  let ta = $state(null)
  const ready = $derived(!!text.trim() && !app.busy)

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
</script>

<div class="dock">
  <div class="card">
    <textarea
      bind:this={ta}
      bind:value={text}
      rows="1"
      oninput={autogrow}
      onkeydown={onKey}
      placeholder="Ask the tutor anything… (Enter to send, Shift+Enter for a new line)"
      aria-label="Message to the tutor"
      maxlength="4000"
      data-testid="composer"
    ></textarea>
    {#if app.busy}
      <button class="send stop" onclick={() => app.stopAnswer()} aria-label="Stop the answer" title="Stop"><Square size={13} fill="currentColor" /></button>
    {:else}
      <button class="send" class:ready onclick={send} disabled={!ready} aria-label="Send" title="Send (Enter)" data-testid="send">
        <ArrowUp size={18} strokeWidth={2.4} />
      </button>
    {/if}
  </div>
  <p class="fine">Answers come from OpenAI. Camera frames are {app.local ? 'analysed locally and' : 'analysed by the ExtraHorizon backend and are'} never sent to it.</p>
</div>

<style>
  .dock { padding: 8px 22px 14px; max-width: calc(var(--feed-w) + 44px); width: 100%; margin: 0 auto; }
  .card {
    position: relative; display: flex; align-items: flex-end; gap: 10px;
    padding: 10px 10px 10px 16px; border-radius: var(--radius-lg);
    background: var(--sheen), var(--plane-hi); box-shadow: var(--ring-2), var(--rise-3);
    transition: box-shadow var(--t3) var(--ease);
  }
  /* focus: a beam of light runs along the border (blue → violet) */
  .card::before {
    content: ''; position: absolute; inset: 0; border-radius: inherit; padding: 1px; pointer-events: none;
    background: conic-gradient(from var(--beam), transparent 0 56%, rgb(122 152 255 / .25) 74%, rgb(165 139 255 / .95) 99%, transparent 100%);
    -webkit-mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    mask: linear-gradient(#000 0 0) content-box, linear-gradient(#000 0 0);
    -webkit-mask-composite: xor; mask-composite: exclude;
    opacity: 0; transition: opacity var(--t3) var(--ease);
  }
  .card:focus-within::before { opacity: 1; animation: eh-beam 5s linear infinite; }
  .card:focus-within { box-shadow: var(--ring-2), var(--rise-3), 0 0 44px -22px var(--halo); }
  textarea {
    flex: 1 1 auto; min-width: 0; resize: none; border: 0; outline: none; background: transparent;
    padding: 6px 0; min-height: 34px; max-height: 180px; line-height: 1.5; font-size: 15px; color: var(--text); overflow-y: hidden;
  }
  textarea::placeholder { color: var(--faint); }
  .send {
    flex: 0 0 auto; width: 36px; height: 36px; border-radius: 11px; border: 0; display: grid; place-items: center;
    background: var(--sheen), var(--raise); color: var(--faint); box-shadow: var(--ring), var(--rise-1);
    transition: transform var(--t2) var(--spring), background var(--t2) var(--ease), color var(--t2) var(--ease), box-shadow var(--t2) var(--ease);
  }
  .send.ready { background: var(--primary-bg); color: var(--primary-ink); box-shadow: var(--primary-rise); }
  .send.ready:hover { transform: translateY(-1px) scale(1.04); }
  .send.stop { color: var(--error); box-shadow: 0 0 0 1px color-mix(in srgb, var(--error) 40%, transparent), var(--rise-1); }
  .fine { margin: 7px 4px 0; font-size: 11px; color: var(--faint); text-align: center; }
  @media (max-width: 859px) { .dock { padding: 8px 12px 12px; position: sticky; bottom: 0; background: linear-gradient(180deg, transparent, var(--bg) 30%); } }
</style>
