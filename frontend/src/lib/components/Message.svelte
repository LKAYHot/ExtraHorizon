<script>
  import { app } from '$lib/app.svelte.js'
  import { renderMarkdown } from '$lib/markdown.js'
  import { Repeat, RefreshCw, CircleAlert, WandSparkles } from '$lib/icons.js'
  import Logo from './Logo.svelte'
  import WhyAdapted from './WhyAdapted.svelte'

  let { m, isLast = false } = $props()

  const html = $derived(m.role === 'assistant' ? renderMarkdown(m.text) : '')
  const adapted = $derived(!!m.adaptation)
  const streaming = $derived(m.status === 'pending' || m.status === 'streaming')
  // Retry helps for network/LLM failures (also after fixing .env); not for a reset session or an
  // offer the server no longer accepts (409) / an invalid request (422)
  // only the latest answer is retryable — re-running an older one would reorder the history
  const canRetry = $derived(isLast && m.error?.code !== 'reset' && m.error?.status !== 409 && m.error?.status !== 422)
  // extra guidance only where the server message does not already say what to do
  const HINTS = {
    network: 'Start the backend (see README), then retry.',
    client_timeout: 'The connection went quiet — retry; if it repeats, check the backend log.',
  }
</script>

{#if m.role === 'user'}
  {#if m.mode === 'explain_differently'}
    <div class="action" data-testid="user-action"><Repeat size={13} /> Explain differently</div>
  {:else}
    <div class="user" data-testid="user-message">{m.text}</div>
  {/if}
{:else}
  <article class="assistant" class:adapted aria-busy={streaming} data-testid="assistant-message" data-status={m.status}>
    <div class="avatar"><Logo size={26} /></div>
    <div class="body">
      {#if adapted}
        <div class="badge" data-testid="adapted-badge"><WandSparkles size={13} /> Adapted · {m.adaptation.strategy.label}</div>
      {/if}
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
        <div class="foot faint">
          {m.model ?? ''}{#if m.ttft_ms != null} · first token {(m.ttft_ms / 1000).toFixed(2)} s{/if}
        </div>
      {/if}

      {#if adapted && m.status !== 'error'}
        <WhyAdapted {m} />
      {/if}
    </div>
  </article>
{/if}

<style>
  .user {
    align-self: flex-end; max-width: min(78%, 620px);
    padding: 10px 14px; border-radius: 16px 16px 5px 16px;
    background: linear-gradient(180deg, #2a3a72, #222f5f); color: #f2f5ff;
    box-shadow: var(--ring-2), var(--rise-1);
    white-space: pre-wrap; overflow-wrap: anywhere; line-height: 1.5;
    animation: eh-rise .35s var(--ease) both;
  }
  .action {
    align-self: flex-end; display: inline-flex; align-items: center; gap: 6px;
    padding: 6px 12px; border-radius: 999px; font-size: 12.5px; font-weight: 600; color: #e6dcff;
    background: linear-gradient(180deg, rgb(165 139 255 / .24), rgb(122 152 255 / .16));
    box-shadow: 0 0 0 1px rgb(165 139 255 / .4), var(--rise-1);
    animation: eh-rise .35s var(--ease) both;
  }
  .assistant { display: flex; gap: 11px; align-items: flex-start; animation: eh-rise .4s var(--ease) both; }
  .avatar { flex: 0 0 auto; margin-top: 2px; filter: drop-shadow(0 6px 12px rgb(0 0 10 / .5)); }
  .body {
    flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 8px;
    padding: 12px 16px 12px; border-radius: 5px 16px 16px 16px;
    background: var(--sheen), var(--plane); box-shadow: var(--ring), var(--rise-1);
  }
  .adapted .body { box-shadow: 0 0 0 1px rgb(165 139 255 / .35), var(--rise-2), 0 18px 40px -26px var(--halo-violet); }
  .badge {
    align-self: flex-start; display: inline-flex; align-items: center; gap: 6px;
    padding: 3px 9px; border-radius: 999px; font-size: 11.5px; font-weight: 650; color: #e6dcff;
    background: rgb(165 139 255 / .16); box-shadow: 0 0 0 1px rgb(165 139 255 / .38);
  }
  .thinking { padding: 4px 0; }
  .foot { font-size: 11px; }
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
  .md.streaming > :global(:last-child)::after {
    content: ''; display: inline-block; width: 7px; height: 1.05em; margin-left: 3px; vertical-align: -2px;
    border-radius: 2px; background: var(--accent); animation: eh-caret 1s steps(1) infinite;
  }
</style>
