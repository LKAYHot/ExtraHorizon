<script>
  import { app } from '$lib/app.svelte.js'
  import { Bug, BookOpen, Send, HandHelping, ChevronDown, ShieldCheck, Lightbulb, GraduationCap, Users, X } from '$lib/icons.js'
  import HubItem from './HubItem.svelte'

  const h = app.hub
  let mode = $state('unstuck') // unstuck | learn
  let text = $state('')
  let ask = $state(null) // a help-request draft (Still stuck? Ask a person)
  let share = $state(null) // a card draft (This fixed it)
  let showAudit = $state(false)

  const r = $derived(h.report && (h.report.kind === 'unstuck' || h.report.kind === 'learn') ? h.report : null)
  const EXAMPLES = {
    unstuck: [
      "Access to fetch at the API has been blocked by CORS policy: No 'Access-Control-Allow-Origin' header — Svelte calls FastAPI",
      "ModuleNotFoundError: No module named 'cv2'",
      'npm ERR! code ERESOLVE unable to resolve dependency tree',
    ],
    learn: ['Where can I learn WebSockets with FastAPI fast?', 'Any good tutorials for SvelteKit?'],
  }
  const SRC = { stackoverflow: 'Stack Overflow', github: 'GitHub', registries: 'npm / PyPI', devto: 'DEV Community' }

  async function submit(e) {
    e?.preventDefault()
    const t = text.trim()
    if (!t || app.busy) return
    const ok = await h.search(mode, t)
    if (ok) text = ''
  }

  function startAsk() {
    share = null
    ask = h.draftRequest()
  }

  async function postAsk(e) {
    e.preventDefault()
    if (!ask?.title?.trim()) return
    const res = await h.postRequest({ ...ask, tags: ask.tags })
    if (res) {
      ask = null
      h.tab = 'board'
    }
  }

  function startShare(ref) {
    ask = null
    share = h.draftCard(ref)
  }

  async function postShare(e) {
    e.preventDefault()
    if (!share?.title?.trim() || !share?.fix?.trim()) return
    const res = await h.addCard(share)
    if (res) share = null
  }
</script>

<form class="ask" onsubmit={submit} data-testid="hub-search">
  <div class="seg" role="radiogroup" aria-label="What do you need">
    <button type="button" role="radio" aria-checked={mode === 'unstuck'} class:sel={mode === 'unstuck'} onclick={() => (mode = 'unstuck')}
            data-testid="hub-mode-unstuck"><Bug size={13} /> I'm stuck on an error</button>
    <button type="button" role="radio" aria-checked={mode === 'learn'} class:sel={mode === 'learn'} onclick={() => (mode = 'learn')}
            data-testid="hub-mode-learn"><BookOpen size={13} /> I want to learn something</button>
  </div>
  <textarea class="input area" rows="3" bind:value={text} maxlength="3500" data-testid="hub-text"
            placeholder={mode === 'unstuck' ? 'Paste the error (or the end of the traceback) and say what you were doing…' : 'What do you want to learn tonight?'}
            onkeydown={(e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) submit(e) }}></textarea>
  <div class="row">
    <button class="btn primary sm" type="submit" disabled={!text.trim() || app.busy} data-testid="hub-ask"><Send size={13} /> Ask {app.persona}</button>
    <span class="note"><ShieldCheck size={12} /> {mode === 'unstuck'
      ? 'Only the error’s signature is searched — your paths, hosts, ports and keys are removed first.'
      : 'Searches GitHub, DEV Community and Stack Overflow for current, popular material.'}</span>
  </div>
  {#if !r}
    <div class="ex">
      {#each EXAMPLES[mode] as ex (ex)}
        <button type="button" class="btn sm ghost" onclick={() => (text = ex)}>{ex.length > 70 ? ex.slice(0, 68) + '…' : ex}</button>
      {/each}
    </div>
  {/if}
</form>

{#if r}
  <section class="summary" data-testid="hub-summary">
    <div class="q">{r.kind === 'unstuck' ? 'Roadblock' : 'Topic'}: <b>{r.query?.text}</b></div>
    <div class="chips">
      {#each r.query?.signature?.tags ?? r.query?.tags ?? [] as t, i (i)}<span class="chip">{t}</span>{/each}
      <span class="chip">{r.items.length} verified {r.kind === 'unstuck' ? 'source' : 'resource'}{r.items.length === 1 ? '' : 's'}</span>
      {#if r.offline}<span class="chip warn">test fixture</span>{/if}
    </div>
  </section>

  {#each r.errors ?? [] as e, i (i)}
    <div class="warnline">{e.source} could not be read ({e.message}) — the results are from the other sources.</div>
  {/each}

  <div class="list" data-testid="hub-results">
    {#each r.items as x (x.ref)}<HubItem {x} onshare={r.kind === 'unstuck' ? startShare : null} />{/each}
    {#if !r.items.length}<p class="empty">No public source had a verified answer. Ask a person — below.</p>{/if}
  </div>

  {#each r.hints ?? [] as hint, i (i)}<div class="hint"><Lightbulb size={12} /> {hint}</div>{/each}

  {#if r.peers?.length}
    <h3><Lightbulb size={13} /> From teams here</h3>
    <div class="list">{#each r.peers as x (x.ref)}<HubItem {x} />{/each}</div>
  {/if}
  {#if r.mentors?.length}
    <h3><GraduationCap size={13} /> Mentors who can help</h3>
    <div class="list">{#each r.mentors as x (x.ref)}<HubItem {x} />{/each}</div>
  {/if}
  {#if r.similar?.length}
    <div class="similar"><Users size={13} /> {r.similar.length} other team{r.similar.length === 1 ? ' is' : 's are'} stuck on this too:
      {r.similar.map((s) => s.title).join(' · ')} — ask a mentor together.</div>
  {/if}

  {#if r.kind === 'unstuck'}
    <div class="acts">
      <button class="btn sm" onclick={startAsk} data-testid="hub-still-stuck"><HandHelping size={13} /> Still stuck? Ask a person</button>
      <span class="note">30-minute rule: stuck that long — ask a mentor or a peer.</span>
    </div>
  {/if}

  {#if ask}
    <form class="card form" onsubmit={postAsk} data-testid="hub-ask-form">
      <div class="fh"><HandHelping size={13} /> Post on the help board <button type="button" class="btn sm icon ghost" onclick={() => (ask = null)} aria-label="Cancel"><X size={13} /></button></div>
      <input class="input" bind:value={ask.title} maxlength="120" placeholder="Short title" data-testid="hub-ask-title" />
      <textarea class="input area" rows="5" bind:value={ask.problem} maxlength="1500" data-testid="hub-ask-problem"></textarea>
      <div class="row"><button class="btn primary sm" type="submit" disabled={h.busy || !ask.title.trim()} data-testid="hub-ask-post"><Send size={13} /> Post</button>
        <span class="note">Everyone using this app at the event can see it (with your card's name, if you made one) until you withdraw it.</span></div>
    </form>
  {/if}
  {#if share}
    <form class="card form" onsubmit={postShare} data-testid="hub-share-form">
      <div class="fh"><Lightbulb size={13} /> Share what fixed it — the next team stuck on this will find it <button type="button" class="btn sm icon ghost" onclick={() => (share = null)} aria-label="Cancel"><X size={13} /></button></div>
      <input class="input" bind:value={share.title} maxlength="120" placeholder="What was the problem" />
      <textarea class="input area" rows="4" bind:value={share.fix} maxlength="800" placeholder="What fixed it, in your words" data-testid="hub-share-fix"></textarea>
      <div class="row"><button class="btn primary sm" type="submit" disabled={h.busy || !share.fix.trim()} data-testid="hub-share-post"><Send size={13} /> Share</button></div>
    </form>
  {/if}

  <button class="audit-t" onclick={() => (showAudit = !showAudit)} aria-expanded={showAudit} data-testid="hub-audit-toggle">
    <ShieldCheck size={12} /> How this was checked <ChevronDown size={12} />
  </button>
  {#if showAudit}
    <ul class="audit" data-testid="hub-audit">
      {#each r.audit ?? [] as a, i (i)}
        <li><b>{SRC[a.source] ?? a.source}</b> — {a.error ? `could not be read: ${a.error}` : `${a.received} read, ${a.kept} kept`}
          {#each Object.entries(a.excluded ?? {}) as [why, n], j (j)}<span class="ex-r">· {n} {why}</span>{/each}</li>
      {/each}
      <li class="rule">Kept: answers that match the error and are accepted (or have 3+ votes), issues closed as fixed or
        actively discussed, the registries' own data. Old answers are flagged; nothing is paraphrased as a fact.</li>
    </ul>
  {/if}
{:else if h.run.state !== 'running'}
  <section class="intro" data-testid="hub-intro">
    <p><b>Stuck?</b> Paste the error. {app.persona} reads Stack Overflow, GitHub issues and the npm / PyPI registries,
      keeps only verified answers, and explains the fix — with who here solved it before and which mentor can help.</p>
    <p><b>Learning something new?</b> She finds current starters, articles and top questions.</p>
    <p>You can also just say it out loud: “I’m getting a CORS error from FastAPI.”</p>
  </section>
{/if}

<style>
  .ask { display: flex; flex-direction: column; gap: 8px; }
  .seg { display: inline-flex; gap: 4px; padding: 2px; border-radius: 9px; background: var(--well-bg); box-shadow: var(--sink); align-self: flex-start; }
  .seg button { display: inline-flex; align-items: center; gap: 5px; height: 28px; padding: 0 10px; border: 0; border-radius: 7px; background: transparent;
    color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer; }
  .seg button.sel { background: var(--sheen), var(--raise-hi); color: var(--text); box-shadow: var(--ring-2), var(--rise-1); }
  .area { height: auto; min-height: 64px; padding: 8px 11px; resize: vertical; font: 12.5px/1.45 var(--font); }
  .row { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .note { display: inline-flex; align-items: center; gap: 5px; font-size: 11.5px; color: var(--faint); }
  .ex { display: flex; flex-wrap: wrap; gap: 4px; }
  .ex .btn { max-width: 100%; overflow: hidden; text-overflow: ellipsis; }
  .summary { display: flex; flex-direction: column; gap: 6px; padding-top: 4px; }
  .q { font-size: 12.5px; color: var(--muted); }
  .q b { color: var(--text); font-weight: 600; }
  .chips { display: flex; flex-wrap: wrap; gap: 5px; }
  .list { display: flex; flex-direction: column; gap: 8px; }
  h3 { display: flex; align-items: center; gap: 6px; margin: 6px 0 0; font-size: 12px; font-weight: 650; color: var(--text-2); letter-spacing: .02em; }
  h3 :global(svg) { color: var(--accent); }
  .hint, .similar, .warnline { display: flex; gap: 6px; align-items: flex-start; font-size: 12px; color: var(--text-2); padding: 7px 10px;
    border-radius: 8px; background: color-mix(in srgb, var(--accent) 8%, var(--plane)); }
  .warnline { color: var(--warn); background: color-mix(in srgb, var(--warn) 9%, transparent); }
  .empty { margin: 0; font-size: 12.5px; color: var(--muted); }
  .acts { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
  .form { display: flex; flex-direction: column; gap: 7px; padding: 10px 12px; }
  .fh { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; color: var(--text-2); }
  .fh .btn { margin-left: auto; }
  .audit-t { align-self: flex-start; display: inline-flex; align-items: center; gap: 5px; border: 0; background: none; color: var(--muted);
    font-size: 11.5px; cursor: pointer; padding: 2px 0; }
  .audit { margin: 0; padding-left: 16px; font-size: 11.5px; color: var(--muted); display: flex; flex-direction: column; gap: 3px; }
  .audit b { color: var(--text-2); }
  .ex-r { margin-left: 4px; color: var(--faint); }
  .rule { list-style: none; margin-left: -16px; color: var(--faint); }
  .intro { font-size: 12.5px; color: var(--text-2); line-height: 1.55; padding: 4px 2px; }
  .intro p { margin: 0 0 8px; }
  .intro b { color: var(--text); }
</style>
