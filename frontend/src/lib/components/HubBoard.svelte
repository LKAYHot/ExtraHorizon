<script>
  import { app } from '$lib/app.svelte.js'
  import { HandHelping, Check, Trash, ThumbsUp, Lightbulb, Search, ExternalLink, Send, X, MessageSquareQuote, RefreshCw, CircleAlert } from '$lib/icons.js'
  import { safeUrl } from '$lib/hub.svelte.js'

  const h = app.hub
  let q = $state('')
  let solving = $state(null) // {id, note, share, fix}
  const oq = $derived(h.questions)

  // real open questions (Stack Overflow, nobody has answered yet): loaded when the board opens, refreshed now and then
  $effect(() => {
    h.loadQuestions()
    const t = setInterval(() => { if (!document.hidden) h.loadQuestions() }, 5 * 60_000)
    return () => clearInterval(t)
  })

  function asked(day) {
    if (!day) return ''
    const d = Math.round((Date.now() - new Date(`${day}T12:00:00Z`).getTime()) / 86_400_000)
    return d <= 0 ? 'today' : d === 1 ? 'yesterday' : `${d} days ago`
  }

  const requests = $derived((h.board?.requests ?? []).filter((r) => r.status !== 'solved' || r.mine))
  // a request about something on my card (a mentor sees whom to help first)
  const mySkills = $derived(new Set(h.me?.skills ?? []))
  const forMe = (r) => !r.mine && r.status === 'open' && (r.tags ?? []).some((t) => mySkills.has(t))
  const cards = $derived.by(() => {
    const all = h.board?.cards ?? []
    const t = q.trim().toLowerCase()
    if (!t) return all
    return all.filter((c) => `${c.title} ${c.problem} ${c.fix} ${(c.tags ?? []).join(' ')}`.toLowerCase().includes(t))
  })

  function ago(ms) {
    const m = Math.max(0, Math.round((Date.now() - (ms ?? Date.now())) / 60000))
    return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
  }

  async function solve(e) {
    e.preventDefault()
    const s = solving
    const ok = await h.resolve(s.id, { note: s.note, share: s.share && !!s.fix.trim(), fix: s.fix })
    if (ok) solving = null
  }
</script>

<h3><HandHelping size={13} /> Help requests</h3>
<div class="list" data-testid="hub-requests">
  {#each requests as r (r.id)}
    <article class="req" class:mine={r.mine} class:forme={forMe(r)} data-testid="hub-request" data-status={r.status} data-rid={r.id}>
      <div class="top">
        <span class="st {r.status}">{r.status}</span>
        {#if forMe(r)}<span class="match" data-testid="hub-for-me">matches your skills</span>{/if}
        <span class="who">{r.author}</span><span class="when">{ago(r.created)}</span>
      </div>
      <div class="title">{r.title}</div>
      {#if r.problem}<p class="prob">{r.problem}</p>{/if}
      {#if r.tags?.length}<div class="tags">{#each r.tags as t, i (i)}<span class="tag">{t}</span>{/each}</div>{/if}
      {#if r.claimed_by}<div class="claimed"><Check size={11} /> {r.claimed_by.name} is on it</div>{/if}
      {#if r.solved_note}<div class="claimed">solved: {r.solved_note}</div>{/if}
      <div class="acts">
        {#if r.mine}
          {#if r.status !== 'solved'}
            <button class="btn sm" onclick={() => (solving = { id: r.id, note: '', share: true, fix: '' })} data-testid="hub-solved"><Check size={12} /> Solved</button>
            <button class="btn sm ghost" onclick={() => h.withdraw(r.id)}><Trash size={12} /> Withdraw</button>
          {/if}
        {:else if r.status === 'open'}
          <button class="btn sm" onclick={() => h.claim(r.id)} disabled={h.busy || !h.me} title={h.me ? '' : 'Create your card first (People tab)'}
                  data-testid="hub-claim"><HandHelping size={12} /> I can help</button>
        {/if}
        {#if r.status === 'claimed' && (r.mine || (h.me && r.claimed_by?.id === h.me.id))}
          <button class="btn sm ghost" onclick={() => h.release(r.id)} disabled={h.busy} data-testid="hub-release">Give it back</button>
        {/if}
      </div>
      {#if solving?.id === r.id}
        <form class="solve" onsubmit={solve} data-testid="hub-solve-form">
          <input class="input" bind:value={solving.note} maxlength="400" placeholder="What was it? (optional)" />
          <label class="check"><input type="checkbox" bind:checked={solving.share} /> Share what fixed it with the next team</label>
          {#if solving.share}<textarea class="input area" rows="3" bind:value={solving.fix} maxlength="800" placeholder="What fixed it, in your words" data-testid="hub-solve-fix"></textarea>{/if}
          <div class="acts"><button class="btn primary sm" type="submit" disabled={h.busy}><Send size={12} /> Done</button>
            <button type="button" class="btn sm ghost" onclick={() => (solving = null)}><X size={12} /> Cancel</button></div>
        </form>
      {/if}
    </article>
  {:else}
    <p class="none">No help requests from teams here yet. Stuck? Search in “Get unstuck” first — then post it from there.</p>
  {/each}
</div>

<h3><MessageSquareQuote size={13} /> Open questions you could answer
  <span class="src">Stack Overflow · real, still unsolved</span>
  <button class="btn sm icon ghost" onclick={() => h.loadQuestions(true)} aria-label="Read the open questions again" title="Read again"><RefreshCw size={12} /></button>
</h3>
<div class="list" data-testid="hub-open-questions">
  {#if !oq}
    <p class="none">Reading Stack Overflow…</p>
  {:else}
    {#each oq.errors ?? [] as e, i (i)}<p class="warnline"><CircleAlert size={12} /> {e.source} could not be read: {e.message}</p>{/each}
    {#if oq.tags?.length}
      <p class="lead">Questions in {oq.tags.map((t) => `[${t}]`).join(' and ')} with no accepted or upvoted answer yet{#if oq.why}{' '}— from {oq.why}{/if}.
        Answering one is a fast way to learn it — and someone is still stuck on it.</p>
      {#each oq.items ?? [] as x (x.id)}
        <article class="oq" data-testid="hub-open-question">
          <a class="title" href={safeUrl(x.url)} target="_blank" rel="noopener noreferrer">{x.title} <ExternalLink size={11} /></a>
          <div class="top">
            {#each x.tags ?? [] as t, i (i)}<span class="tag">{t}</span>{/each}
            <span class="grow"></span>
            <span class="when">asked {asked(x.asked)} · {x.answers ? `${x.answers} answer${x.answers === 1 ? '' : 's'}, none accepted` : 'no answers'} · {x.views} views{#if x.author}{' '}· by {x.author}{/if}</span>
          </div>
        </article>
      {:else}
        <p class="none">No unsolved questions from the last six months there.</p>
      {/each}
      {#if oq.items?.length}<p class="attr">Titles © their askers on Stack Overflow, CC BY-SA 4.0.</p>{/if}
    {:else}
      <p class="none">Put your skills on your card (People tab) or search a roadblock — real, still unsolved questions in that stack show up here.</p>
    {/if}
  {/if}
</div>

<h3><Lightbulb size={13} /> What teams here learned</h3>
<div class="search"><Search size={13} /><input class="input" bind:value={q} placeholder="Search what fixed it…" data-testid="hub-cards-search" /></div>
<div class="list" data-testid="hub-cards">
  {#each cards as c (c.id)}
    <article class="card-k" data-testid="hub-card-k">
      <div class="top"><span class="who">{c.author}</span><span class="when">{ago(c.created)}</span>
        <span class="grow"></span>
        <button class="btn sm ghost" onclick={() => h.helpful(c.id)} disabled={c.mine} title="It helped me too"><ThumbsUp size={12} /> {c.helpful ?? 0}</button>
        {#if c.mine}<button class="btn sm icon ghost" onclick={() => h.deleteCard(c.id)} aria-label="Delete"><Trash size={12} /></button>{/if}
      </div>
      <div class="title">{c.title}</div>
      {#if c.problem && c.problem !== c.title}<p class="prob">{c.problem}</p>{/if}
      <p class="fix">{c.fix}</p>
      {#if c.links?.length}<div class="links">{#each c.links as l, i (i)}<a href={safeUrl(l)} target="_blank" rel="noopener noreferrer">source {i + 1} <ExternalLink size={10} /></a>{/each}</div>{/if}
    </article>
  {:else}
    <p class="none">{q ? 'Nothing matches.' : 'Nothing shared yet. When something fixes your roadblock, share it — the next team will thank you.'}</p>
  {/each}
</div>

<style>
  h3 { display: flex; align-items: center; gap: 6px; margin: 4px 0 0; font-size: 12px; font-weight: 650; color: var(--text-2); }
  h3 :global(svg) { color: var(--accent); }
  .list { display: flex; flex-direction: column; gap: 8px; }
  .req, .card-k { padding: 10px 12px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1);
    display: flex; flex-direction: column; gap: 5px; }
  .req.mine { box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent) 40%, transparent), var(--rise-1); }
  .req.forme { box-shadow: 0 0 0 1px color-mix(in srgb, var(--ok) 45%, transparent), var(--rise-1); }
  .match { padding: 1px 7px; border-radius: 999px; font-size: 10.5px; font-weight: 650; color: var(--ok);
    background: color-mix(in srgb, var(--ok) 14%, transparent); }
  .top { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--muted); flex-wrap: wrap; }
  .st { padding: 1px 7px; border-radius: 999px; font-weight: 650; text-transform: uppercase; font-size: 10px; letter-spacing: .06em; }
  .st.open { color: var(--warn); background: color-mix(in srgb, var(--warn) 14%, transparent); }
  .st.claimed { color: var(--accent); background: color-mix(in srgb, var(--accent) 14%, transparent); }
  .st.solved { color: var(--ok); background: color-mix(in srgb, var(--ok) 14%, transparent); }
  .who { color: var(--text-2); font-weight: 600; }
  .when { color: var(--faint); }
  .grow { flex: 1; }
  .title { font-weight: 600; color: var(--text); font-size: 13px; }
  .prob, .fix { margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--text-2); white-space: pre-wrap; }
  .fix { color: var(--text); }
  .tags { display: flex; gap: 4px; flex-wrap: wrap; }
  .tag { padding: 1px 7px; border-radius: 999px; font-size: 11px; color: var(--muted); background: var(--well-bg); box-shadow: var(--sink); }
  .claimed { font-size: 11.5px; color: var(--ok); display: flex; align-items: center; gap: 4px; }
  .acts { display: flex; gap: 6px; flex-wrap: wrap; }
  .solve { display: flex; flex-direction: column; gap: 6px; padding-top: 4px; }
  .check { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
  .area { height: auto; padding: 8px 11px; resize: vertical; font: 12.5px/1.45 var(--font); }
  .search { display: flex; align-items: center; gap: 6px; color: var(--muted); }
  .search .input { flex: 1; height: 30px; }
  .links { display: flex; gap: 10px; font-size: 11.5px; }
  .links a { color: var(--muted); }
  .none { margin: 0; font-size: 12.5px; color: var(--muted); }
  .src { margin-left: 4px; padding: 1px 7px; border-radius: 999px; font-size: 10.5px; font-weight: 600; color: var(--muted);
    background: var(--well-bg); box-shadow: var(--sink); }
  h3 .btn { margin-left: auto; }
  .lead { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.45; }
  .oq { padding: 9px 12px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1);
    display: flex; flex-direction: column; gap: 5px; }
  .oq .title { color: var(--text); text-decoration: none; line-height: 1.35; }
  .oq .title:hover { text-decoration: underline; }
  .attr { margin: 0; font-size: 11px; color: var(--faint); }
  .warnline { display: flex; gap: 6px; align-items: center; margin: 0; font-size: 12px; color: var(--warn); }
</style>
