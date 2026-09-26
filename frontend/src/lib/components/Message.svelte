<script>
  import { app } from '$lib/app.svelte.js'
  import { renderMarkdown } from '$lib/markdown.js'
  import { hideOpenCue } from '$lib/cues.js'
  import { COLOR, LABEL } from '$lib/emotions.js'
  import { RefreshCw, CircleAlert, Mic, ScanFace, ChevronDown, Hand, AudioLines } from '$lib/icons.js'
  import Logo from './Logo.svelte'

  let { m, isLast = false } = $props()

  const streaming = $derived(m.status === 'pending' || m.status === 'streaming')
  const html = $derived(m.role === 'assistant' ? renderMarkdown(streaming ? hideOpenCue(m.text) : m.text) : '')
  const speaking = $derived(
    m.role === 'assistant' && m.turn_no != null && app.voice.playing && app.voice.playingKind === 'answer' && app.voice.playingTurn === m.turn_no,
  )
  const ctx = $derived(m.emotion_context)
  let showCtx = $state(false)
  // only the latest typed answer is retryable — re-running an older one would reorder the history
  const canRetry = $derived(isLast && !!m.request && m.error?.code !== 'reset' && m.error?.status !== 409 && m.error?.status !== 422)
  const HINTS = {
    network: 'Start the backend (see README), then retry.',
    client_timeout: 'The connection went quiet — retry; if it repeats, check the backend log.',
  }
</script>

{#if m.role === 'user'}
  <div class="user-wrap">
    <div class="user" data-testid="user-message">{m.text}</div>
    {#if m.source === 'voice'}<div class="said" data-testid="spoken-tag"><Mic size={11} /> spoken</div>{/if}
  </div>
{:else}
  <article class="assistant" class:speaking aria-busy={streaming} data-testid="assistant-message" data-status={m.status} data-turn={m.turn_no}>
    <div class="avatar"><Logo size={26} /></div>
    <div class="body">
      {#if m.text}
        <div class="md" class:streaming>{@html html}</div>
      {:else if streaming}
        <div class="thinking"><span class="typing" aria-label="Thinking"><i></i><i></i><i></i></span></div>
      {/if}

      {#if m.status === 'error'}
        <div class="error" role="alert" data-testid="chat-error">
          <CircleAlert size={15} />
          <div class="grow">
            <strong>{m.text ? 'The answer was interrupted.' : 'No answer.'}</strong>
            {m.error?.message}
            {#if HINTS[m.error?.code]}<span class="hint">{HINTS[m.error.code]}</span>{/if}
          </div>
          {#if canRetry}
            <button class="btn sm" onclick={() => app.retry(m.id)} disabled={app.busy} data-testid="retry"><RefreshCw size={13} /> Retry</button>
          {/if}
        </div>
      {:else if m.status === 'done'}
        <div class="foot">
          {#if m.interrupted}<span class="tag int" data-testid="interrupted-tag"><Hand size={11} /> interrupted</span>{/if}
          {#if speaking}<span class="tag talk" data-testid="speaking-tag"><AudioLines size={11} /> speaking</span>{/if}
          <span class="faint">{m.model ?? ''}{#if m.ttft_ms != null} · first token {(m.ttft_ms / 1000).toFixed(2)} s{/if}</span>
          {#if ctx}
            <button class="ctx-btn" onclick={() => (showCtx = !showCtx)} aria-expanded={showCtx} data-testid="ctx-toggle">
              <ScanFace size={12} />
              {#if ctx.available}
                <i class="sw" style:background={COLOR[ctx.dominant]}></i>{LABEL[ctx.dominant] ?? ctx.dominant} — expression sent
              {:else}
                no expression sent
              {/if}
              <ChevronDown size={12} class="chev" />
            </button>
          {/if}
        </div>
      {:else if speaking}
        <div class="foot"><span class="tag talk"><AudioLines size={11} /> speaking</span></div>
      {/if}

      {#if showCtx && ctx}
        <div class="ctx" data-testid="ctx-note">
          {#if ctx.available}
            <div class="ctx-title">Added to her prompt for this answer{#if ctx.source === 'simulation'} <span class="chip sim">SIMULATED</span>{/if}</div>
            <p class="note-text" data-testid="ctx-note-text">{ctx.note}</p>
          {:else}
            <div class="ctx-title">Nothing about your face was sent with this question</div>
            <p class="note-text faint">{ctx.text}</p>
          {/if}
        </div>
      {/if}
    </div>
  </article>
{/if}

<style>
  .user-wrap { align-self: flex-end; display: flex; flex-direction: column; align-items: flex-end; gap: 3px; max-width: min(78%, 620px); animation: eh-rise .35s var(--ease) both; }
  .user {
    padding: 10px 14px; border-radius: 16px 16px 5px 16px;
    background: linear-gradient(180deg, #2a3a72, #222f5f); color: #f2f5ff;
    box-shadow: var(--ring-2), var(--rise-1);
    white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5;
  }
  .said { display: inline-flex; align-items: center; gap: 4px; font-size: 10.5px; color: var(--faint); padding-right: 4px; }
  .assistant { display: flex; gap: 11px; align-items: flex-start; animation: eh-rise .4s var(--ease) both; }
  .avatar { flex: 0 0 auto; margin-top: 2px; filter: drop-shadow(0 6px 12px rgb(0 0 10 / .5)); }
  .body {
    flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 8px;
    padding: 12px 16px 12px; border-radius: 5px 16px 16px 16px;
    background: var(--sheen), var(--plane); box-shadow: var(--ring), var(--rise-1);
    transition: box-shadow var(--t3) var(--ease);
  }
  .speaking .body { box-shadow: 0 0 0 1px rgb(122 152 255 / .45), var(--rise-2), 0 18px 40px -26px var(--halo); }
  .thinking { padding: 4px 0; }
  .foot { display: flex; align-items: center; flex-wrap: wrap; gap: 6px 8px; font-size: 11px; }
  .tag { display: inline-flex; align-items: center; gap: 4px; height: 20px; padding: 0 7px; border-radius: 999px; font-weight: 600; font-size: 10.5px; }
  .tag.int { color: var(--warn); box-shadow: 0 0 0 1px color-mix(in srgb, var(--warn) 40%, transparent); }
  .tag.talk { color: #cdd8ff; background: rgb(122 152 255 / .14); box-shadow: 0 0 0 1px rgb(122 152 255 / .35); }
  .ctx-btn {
    margin-left: auto; display: inline-flex; align-items: center; gap: 5px; height: 22px; padding: 0 8px;
    border: 0; border-radius: 999px; background: var(--fill-2); color: var(--muted); font-size: 11px;
  }
  .ctx-btn:hover { color: var(--text-2); background: var(--fill-3); }
  .ctx-btn :global(.chev) { transition: transform var(--t2) var(--ease); }
  .ctx-btn[aria-expanded='true'] :global(.chev) { transform: rotate(180deg); }
  .sw { width: 8px; height: 8px; border-radius: 2px; display: inline-block; }
  .ctx { padding: 9px 11px; border-radius: var(--radius-sm); background: var(--well-bg); box-shadow: var(--sink); font-size: 12px; animation: eh-fade .25s var(--ease) both; }
  .ctx-title { color: var(--muted); font-size: 11px; font-weight: 600; letter-spacing: .02em; display: flex; align-items: center; gap: 6px; }
  .note-text { margin: 4px 0 0; color: var(--text-2); line-height: 1.5; font-family: var(--mono); font-size: 11.5px; }
  .error {
    display: flex; gap: 10px; align-items: flex-start; padding: 10px 12px; border-radius: var(--radius-sm);
    background: color-mix(in srgb, var(--error) 10%, var(--well)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--error) 35%, transparent);
    color: var(--text-2); font-size: 13px;
  }
  .error > :global(svg) { color: var(--error); flex: 0 0 auto; margin-top: 2px; }
  .error strong { color: var(--text); margin-right: 4px; }
  .hint { display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }

  /* markdown */
  .md { line-height: 1.62; color: var(--text-2); overflow-wrap: anywhere; }
  .md :global(p) { margin: 0 0 .7em; }
  .md :global(p:last-child) { margin-bottom: 0; }
  .md :global(strong) { color: var(--text); }
  .md :global(ul), .md :global(ol) { margin: .2em 0 .75em; padding-left: 1.35em; }
  .md :global(li) { margin: .18em 0; }
  .md :global(li::marker) { color: var(--accent); }
  .md :global(code) { font-family: var(--mono); font-size: .88em; padding: .1em .38em; border-radius: 5px; background: var(--well); box-shadow: inset 0 0 0 1px var(--edge); color: #d9e1ff; }
  .md :global(pre) { margin: .5em 0 .8em; padding: 11px 13px; border-radius: 10px; background: var(--well-bg); box-shadow: var(--sink); overflow-x: auto; }
  .md :global(pre code) { padding: 0; background: none; box-shadow: none; font-size: 12.5px; line-height: 1.55; }
  .md :global(table) { border-collapse: collapse; margin: .4em 0 .8em; font-size: 13px; }
  .md :global(th), .md :global(td) { border: 1px solid var(--line-2); padding: 4px 9px; text-align: left; }
  .md :global(th) { background: var(--fill-2); color: var(--text); }
  .md :global(blockquote) { margin: .4em 0; padding-left: 12px; border-left: 3px solid var(--line-3); color: var(--muted); }
  .md :global(h1), .md :global(h2), .md :global(h3) { font-size: 15px; margin: .8em 0 .4em; color: var(--text); }
  .md :global(em) { color: var(--text); }
  /* voice cues → quiet stage directions */
  .md :global(.cue) {
    display: inline-block; margin: 0 .3em 0 0; padding: 0 .45em; border-radius: 6px; vertical-align: 1px;
    font-size: .78em; font-style: italic; line-height: 1.55; color: #c9b8ff;
    background: rgb(165 139 255 / .1); box-shadow: inset 0 0 0 1px rgb(165 139 255 / .22);
  }
  .md :global(.cue.sound) { color: #9fd8c1; background: rgb(95 203 159 / .09); box-shadow: inset 0 0 0 1px rgb(95 203 159 / .22); }
  .md :global(.cue.timing) { display: none; }
  :global(.hide-cues) .md :global(.cue) { display: none; }
  .md.streaming > :global(:last-child)::after {
    content: ''; display: inline-block; width: 7px; height: 1.05em; margin-left: 3px; vertical-align: -2px;
    border-radius: 2px; background: var(--accent); animation: eh-caret 1s steps(1) infinite;
  }
</style>
