<script>
  import { tick } from 'svelte'
  import { app } from '$lib/app.svelte.js'
  import { Sparkles, Lightbulb, ScanFace, Repeat } from '$lib/icons.js'
  import Message from './Message.svelte'
  import OfferBar from './OfferBar.svelte'
  import Composer from './Composer.svelte'

  const EXAMPLES = ['Explain recursion to me.', 'What is a derivative, intuitively?', 'How does public-key encryption work?']

  let feed = $state(null)
  let pinned = true // follow the stream unless the reader scrolled up

  const llm = $derived(app.health?.llm)
  const lastAssistantKey = $derived.by(() => {
    for (let i = app.messages.length - 1; i >= 0; i--) if (app.messages[i].role === 'assistant') return app.messages[i].key
    return null
  })
  const tail = $derived(app.messages.at(-1)?.text?.length ?? 0)

  function onScroll() {
    if (!feed) return
    pinned = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 80
  }

  $effect(() => {
    // re-run on new messages, streamed text and offer changes
    void app.messages.length
    void tail
    void app.offer
    if (!feed || !pinned) return
    tick().then(() => feed?.scrollTo({ top: feed.scrollHeight }))
  })
</script>

<main class="chat" aria-label="Conversation">
  <header class="head">
    <div class="title">
      <h1>Adaptive Tutor</h1>
      <span class="chip">{app.subject}</span>
    </div>
    <div class="meta">
      {#if llm?.provider === 'mock'}
        <span class="chip mock" title="EH_LLM_PROVIDER=mock — answers are scripted, no LLM is called">Mock LLM · offline</span>
      {:else if llm}
        <span class="chip" title="The only external service: the chat text goes to OpenAI">{llm.model}</span>
      {/if}
    </div>
  </header>

  <div class="feed" bind:this={feed} onscroll={onScroll} data-testid="feed">
    <div class="inner">
      {#if app.messages.length === 0}
        <section class="empty">
          <div class="hero-icon"><Sparkles size={22} /></div>
          <h2>What do you want to understand?</h2>
          <p>Ask anything. If a sustained <em>possible-confusion</em> signal is measured while you read the answer, ExtraHorizon offers to explain it a different way.</p>
          <div class="examples">
            {#each EXAMPLES as ex, i (ex)}
              <button class="btn" class:primary={i === 0} onclick={() => app.send(ex)} disabled={app.busy}>{ex}</button>
            {/each}
          </div>
          <ol class="how">
            <li><Lightbulb size={15} /><span><strong>Ask</strong> — the answer streams in.</span></li>
            <li><ScanFace size={15} /><span><strong>{app.local ? 'Local signal' : 'Camera signal'}</strong> — {app.local ? 'your camera is analysed on this computer' : 'camera frames are analysed by the ExtraHorizon backend'}; a confusion proxy is smoothed over time.</span></li>
            <li><Repeat size={15} /><span><strong>Adapt</strong> — after ~2 s above threshold, one click re-explains with an analogy, an example and short steps.</span></li>
          </ol>
        </section>
      {/if}

      {#each app.messages as m (m.key)}
        <Message {m} isLast={m.key === app.messages.at(-1)?.key} />
        {#if m.key === lastAssistantKey}
          <OfferBar message={m} />
        {/if}
      {/each}
    </div>
  </div>

  <Composer />
</main>

<style>
  .chat { position: relative; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
  .head {
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 14px 22px 12px; border-bottom: 1px solid var(--line);
    background: linear-gradient(180deg, rgb(10 16 34 / .6), rgb(10 16 34 / 0));
  }
  .title { display: flex; align-items: center; gap: 10px; min-width: 0; }
  h1 { font-size: 17px; font-weight: 650; }
  .meta { display: flex; gap: 6px; }
  .feed { flex: 1 1 auto; min-height: 0; overflow-y: auto; scroll-behavior: smooth; }
  .inner { max-width: var(--feed-w); margin: 0 auto; padding: 22px 22px 28px; display: flex; flex-direction: column; gap: 14px; }

  .empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: 12px; padding: 7vh 8px 10px; animation: eh-rise .6s var(--ease) both; }
  .hero-icon {
    width: 48px; height: 48px; border-radius: 14px; display: grid; place-items: center; color: #e9edff;
    background: var(--brand); box-shadow: var(--primary-rise), 0 18px 40px -16px var(--halo-violet);
  }
  .empty h2 { font-size: 24px; font-weight: 650; }
  .empty p { max-width: 520px; margin: 0; color: var(--muted); line-height: 1.6; }
  .empty em { color: var(--text-2); font-style: normal; }
  .examples { display: flex; flex-wrap: wrap; justify-content: center; gap: 8px; margin-top: 6px; }
  .how { list-style: none; margin: 18px 0 0; padding: 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; max-width: 720px; width: 100%; }
  .how li { display: flex; gap: 9px; align-items: flex-start; text-align: left; padding: 11px 12px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1); font-size: 12.5px; color: var(--muted); line-height: 1.45; }
  .how li :global(svg) { flex: 0 0 auto; margin-top: 2px; color: var(--accent); }
  .how strong { color: var(--text-2); }
  @media (max-width: 859px) {
    .feed { overflow: visible; }
    .how { grid-template-columns: 1fr; }
    .head { padding: 12px 16px; }
    .inner { padding: 16px; }
  }
</style>
