<script>
  import { tick } from 'svelte'
  import { app } from '$lib/app.svelte.js'
  import { PERSON_SOURCE, SOURCE_KIND, safeUrl } from '$lib/hub.svelte.js'
  import { ExternalLink, Check, BadgeCheck, Package, FolderGit, BookOpen, MessageSquareQuote, Users, GraduationCap, Lightbulb, ThumbsUp, Bug, MapPin, Award, Info } from '$lib/icons.js'

  /** One result: a public source (S/L), what a team here learned (K), a person (P) or a mentor (M) — on this
   *  event's board, a public GitHub profile or a Stack Overflow top answerer. */
  let { x, onshare = null } = $props()

  const h = app.hub
  const ref = $derived(x.ref)
  const letter = $derived(ref?.[0])
  const sel = $derived(h.selected === ref)
  const person = $derived(letter === 'P' || letter === 'M')
  const peer = $derived(letter === 'K')
  const from = $derived(person ? (x.source ?? 'board') : null) // board | github | stackoverflow
  const askUrl = $derived(from === 'stackoverflow' && x.tag ? `https://stackoverflow.com/questions/ask?tags=${encodeURIComponent(x.tag)}` : null)
  const verified = $derived(new Set(Object.keys(x.verified?.found ? x.verified.skills ?? {} : {})))
  let node = $state(null)

  $effect(() => {
    if (!sel || !node) return
    tick().then(() => node?.scrollIntoView({ block: 'nearest', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' }))
  })

  function ago(ms) {
    if (!ms) return ''
    const m = Math.max(0, Math.round((Date.now() - ms) / 60000))
    return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`
  }
</script>

<article class="item" class:sel class:public={from === 'github' || from === 'stackoverflow'} bind:this={node}
         data-testid="hub-item" data-ref={ref} data-source={from ?? x.type}>
  <div class="top">
    <button class="ref" onclick={() => h.select(ref)} title="Show {ref}">{ref}</button>
    <span class="src">
      {#if x.type === 'stackoverflow' || x.type === 'so_question'}<MessageSquareQuote size={12} />
      {:else if x.type === 'github_issue'}<Bug size={12} />
      {:else if x.type === 'package'}<Package size={12} />
      {:else if x.type === 'repo'}<FolderGit size={12} />
      {:else if x.type === 'article'}<BookOpen size={12} />
      {:else if peer}<Lightbulb size={12} />
      {:else if from === 'github'}<FolderGit size={12} />
      {:else if from === 'stackoverflow'}<Award size={12} />
      {:else if letter === 'M'}<GraduationCap size={12} />
      {:else}<Users size={12} />{/if}
      {#if peer}From a team here{:else if person}{from === 'board' ? (letter === 'M' ? 'Mentor on this board' : 'Hacker on this board') : PERSON_SOURCE[from]}{:else}{x.source ?? SOURCE_KIND[x.type]}{/if}
    </span>
    {#if from === 'github' && x.hireable}<span class="flag good" title="They marked themselves available for hire on GitHub">open to work</span>{/if}
    {#if from === 'stackoverflow'}<span class="flag" class:good={x.active_this_month}>{x.active_this_month ? `answered ${x.month_answers} this month` : 'not active this month'}</span>{/if}
    {#if x.accepted}<span class="flag good"><Check size={11} /> accepted</span>{/if}
    {#if x.votes != null}<span class="flag num">{x.votes.toLocaleString('en-US')} votes</span>{/if}
    {#if x.type === 'github_issue'}<span class="flag" class:good={x.flags?.includes('closed as fixed')}>{x.flags?.[0]}</span>{/if}
    {#if x.stars != null}<span class="flag num">★ {x.stars.toLocaleString('en-US')}</span>{/if}
    {#if x.reactions != null && x.type === 'article'}<span class="flag num">{x.reactions} reactions · {x.minutes} min</span>{/if}
    {#if x.type === 'package'}<span class="flag" class:bad={!x.exists} class:good={x.exists}>{x.exists ? `v${x.version}` : 'not found'}</span>{/if}
    {#if peer && x.helpful}<span class="flag num"><ThumbsUp size={11} /> {x.helpful}</span>{/if}
    <span class="grow"></span>
    {#if x.date}<span class="date num">{x.date}</span>{:else if peer}<span class="date">{ago(x.created)}</span>{/if}
  </div>

  {#if person && from === 'github'}
    <div class="name"><a href={safeUrl(x.profile_url)} target="_blank" rel="noopener noreferrer">{x.name}</a>
      <span class="login">@{x.login}</span></div>
    <div class="meta">
      {#if x.location}<span class="loc"><MapPin size={11} /> {x.location}</span>{/if}
      <span class="num">last push {x.last_push}</span>
      <span class="num">{x.own_repos} public repos</span>
      {#if x.since}<span class="num">on GitHub since {x.since}</span>{/if}
    </div>
    {#if x.covers?.length}<div class="covers">covers <b>{x.covers.join(', ')}</b></div>{/if}
    {#if x.evidence?.length}<ul class="facts">{#each x.evidence as e, i (i)}<li>{e}</li>{/each}</ul>{/if}
    {#if x.signals?.length}<div class="skills">{#each x.signals as s, i (i)}<span class="skill">bio mentions {s}</span>{/each}</div>{/if}
    <p class="lead"><Info size={12} /> A real public profile — not on this board, and they haven't said they're looking for a
      team. One polite message through their GitHub profile at most.</p>
  {:else if person && from === 'stackoverflow'}
    <div class="name"><a href={safeUrl(x.profile_url)} target="_blank" rel="noopener noreferrer">{x.name}</a></div>
    <div class="meta">
      <span class="tag">[{x.tag}]</span>
      <span class="num">{x.answers?.toLocaleString('en-US')} answers on the tag</span>
      <span class="num">score {x.score?.toLocaleString('en-US')}</span>
      <span class="num">reputation {x.reputation?.toLocaleString('en-US')}</span>
    </div>
    <p class="lead"><Info size={12} /> A public expert, not a mentor at this event — they answer questions tagged [{x.tag}] on
      Stack Overflow.{#if askUrl}{' '}<a href={askUrl} target="_blank" rel="noopener noreferrer">Ask a [{x.tag}] question <ExternalLink size={10} /></a>{/if}</p>
  {:else if person}
    <div class="name">{x.name}</div>
    {#if x.covers?.length}<div class="covers">covers <b>{x.covers.join(', ')}</b></div>{/if}
    <div class="skills">
      {#each x.skills ?? [] as s, i (i)}
        <span class="skill" class:seen={verified.has(s)} title={verified.has(s) ? 'Seen in their public GitHub repos (not a rating of skill)' : 'Written on their card'}>
          {#if verified.has(s)}<BadgeCheck size={11} />{/if}{s}</span>
      {/each}
    </div>
    {#if x.evidence?.length}<div class="evidence" title="The public repos of the GitHub username on their card — that the account is theirs is not verified">Seen on GitHub: {x.evidence.join(' · ')}</div>{/if}
    <div class="meta">
      {#if x.shared_interests?.length}<span>shared interests: {x.shared_interests.join(', ')}</span>{/if}
      {#if x.availability}<span>{x.availability}</span>{/if}
      {#if letter === 'P'}<span>{(x.team?.size ?? 1) > 1 ? `team ${x.team?.name || ''} of ${x.team.size}` : 'solo'}</span>{/if}
    </div>
    {#if x.idea}<p class="idea">“{x.idea}”</p>{/if}
    {#if x.contact}<div class="contact"><span class="k">Reach them:</span> {x.contact}</div>{/if}
  {:else if peer}
    <div class="name">{x.title}</div>
    <p class="fix">{x.fix}</p>
    <div class="attr">shared by {x.author}{#if x.links?.length}{' · '}{#each x.links as l, i (i)}<a href={safeUrl(l)} target="_blank" rel="noopener noreferrer">link {i + 1} <ExternalLink size={10} /></a>{' '}{/each}{/if}</div>
  {:else}
    <a class="title" href={safeUrl(x.answer_url || x.url)} target="_blank" rel="noopener noreferrer">{x.title} <ExternalLink size={11} /></a>
    {#if x.type === 'package'}
      <ul class="facts">{#each x.facts ?? [] as f, i (i)}<li>{f}</li>{/each}</ul>
    {/if}
    {#if x.summary && x.type !== 'package'}<p class="sum">{x.summary}</p>{/if}
    {#if x.excerpt?.text}<p class="ex">{x.excerpt.text}</p>{/if}
    {#if x.excerpt?.code}<pre class="code"><code>{x.excerpt.code}</code></pre>{/if}
    {#if x.flags?.some((f) => f.includes('check it against'))}<div class="old">{x.flags.find((f) => f.includes('check it against'))}</div>{/if}
    {#if x.attribution?.author && x.type === 'stackoverflow'}
      <div class="attr">answer by {#if safeUrl(x.attribution.author_url)}<a href={safeUrl(x.attribution.author_url)} target="_blank" rel="noopener noreferrer">{x.attribution.author}</a>{:else}{x.attribution.author}{/if} · {x.attribution.license}</div>
    {/if}
    {#if x.matched?.length}<div class="matched">matches: {x.matched.join(', ')}</div>{/if}
    {#if onshare && (x.type === 'stackoverflow' || x.type === 'github_issue' || x.type === 'package')}
      <div class="acts"><button class="btn sm" onclick={() => onshare(ref)} data-testid="hub-fixed"><Check size={12} /> This fixed it — share it</button></div>
    {/if}
  {/if}
</article>

<style>
  .item { padding: 10px 12px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1);
    display: flex; flex-direction: column; gap: 6px; animation: rise .3s ease-out both; scroll-margin: 12px; }
  .item.sel { box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--accent) 70%, transparent), var(--rise-2); }
  .item.public { box-shadow: var(--ring), var(--rise-1), inset 3px 0 0 color-mix(in srgb, var(--accent-2) 55%, transparent); }
  .item.public.sel { box-shadow: 0 0 0 1.5px color-mix(in srgb, var(--accent) 70%, transparent), var(--rise-2), inset 3px 0 0 color-mix(in srgb, var(--accent-2) 55%, transparent); }
  .top { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; font-size: 11.5px; color: var(--muted); }
  .ref { height: 22px; padding: 0 7px; border-radius: 6px; border: 0; cursor: pointer; font: 700 11.5px/1 var(--font); color: var(--accent-ink);
    background: var(--primary-bg); box-shadow: var(--primary-rise); }
  .src { display: inline-flex; align-items: center; gap: 4px; color: var(--text-2); font-weight: 600; }
  .flag { display: inline-flex; align-items: center; gap: 3px; padding: 1px 6px; border-radius: 999px; background: var(--well-bg); box-shadow: var(--sink); }
  .flag.good { color: var(--ok); }
  .flag.bad { color: var(--error); }

  .grow { flex: 1; }
  .date { color: var(--faint); }
  .title { color: var(--text); font-weight: 600; font-size: 13px; text-decoration: none; line-height: 1.35; }
  .title:hover { text-decoration: underline; }
  .name { color: var(--text); font-weight: 650; font-size: 13.5px; }
  .name a { color: var(--text); text-decoration: none; }
  .name a:hover { text-decoration: underline; }
  .login { margin-left: 6px; font-weight: 500; font-size: 12px; color: var(--muted); }
  .loc { display: inline-flex; align-items: center; gap: 3px; }
  .tag { color: var(--text-2); font-family: var(--mono); font-size: 11.5px; }
  .lead { display: flex; gap: 6px; align-items: flex-start; margin: 0; font-size: 11.5px; line-height: 1.45; color: var(--faint); }
  .lead :global(svg) { flex: 0 0 auto; margin-top: 2px; color: var(--accent-2); }
  .lead a { color: var(--accent); }
  .ex, .sum, .fix, .idea { margin: 0; font-size: 12.5px; line-height: 1.5; color: var(--text-2); }
  .idea { font-style: italic; color: var(--muted); }
  .code { margin: 0; padding: 8px 10px; border-radius: 8px; background: var(--well-bg); box-shadow: var(--sink); overflow-x: auto;
    font: 12px/1.45 ui-monospace, 'Cascadia Code', Consolas, monospace; color: #dfe6ff; white-space: pre; }
  .facts { margin: 0; padding-left: 16px; font-size: 12.5px; color: var(--text-2); display: flex; flex-direction: column; gap: 2px; }
  .old { font-size: 11.5px; color: var(--warn); }
  .attr, .matched, .evidence, .meta, .contact, .covers { font-size: 11.5px; color: var(--faint); }
  .attr a { color: var(--muted); }
  .covers b { color: var(--text-2); }
  .meta { display: flex; gap: 10px; flex-wrap: wrap; }
  .contact .k { color: var(--muted); }
  .contact { color: var(--text-2); }
  .skills { display: flex; flex-wrap: wrap; gap: 4px; }
  .skill { display: inline-flex; align-items: center; gap: 3px; padding: 1px 7px; border-radius: 999px; font-size: 11.5px; color: var(--text-2);
    background: var(--well-bg); box-shadow: var(--sink); }
  .skill.seen { color: var(--ok); box-shadow: 0 0 0 1px color-mix(in srgb, var(--ok) 35%, transparent); }
  .acts { display: flex; gap: 6px; }
  @keyframes rise { from { opacity: 0; transform: translateY(4px); } }
  @media (prefers-reduced-motion: reduce) { .item { animation: none; } }
</style>
