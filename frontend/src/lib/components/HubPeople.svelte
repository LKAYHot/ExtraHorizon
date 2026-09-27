<script>
  import { app } from '$lib/app.svelte.js'
  import { UserPlus, Users, GraduationCap, Pencil, Trash, Send, BadgeCheck, ShieldCheck, X, Search, Minus, Plus, FolderGit, Award, CircleAlert, Info } from '$lib/icons.js'
  import { ROLE_CHIPS } from '$lib/hub.svelte.js'
  import HubItem from './HubItem.svelte'

  const h = app.hub
  const me = $derived(h.me)
  const r = $derived(h.report && (h.report.kind === 'team' || h.report.kind === 'mentors') ? h.report : null)
  let editing = $state(false)
  let form = $state(null)
  let filter = $state('all') // all | hacker | mentor
  let showAll = $state(false)
  const city = $derived(r?.query?.location ?? app.health?.hub?.event_location ?? null)
  const onBoard = $derived((r?.items ?? []).filter((x) => (x.source ?? 'board') === 'board'))
  const onGithub = $derived((r?.items ?? []).filter((x) => x.source === 'github'))
  const boardMentors = $derived((r?.mentors ?? []).filter((x) => (x.source ?? 'board') === 'board'))
  const experts = $derived((r?.mentors ?? []).filter((x) => x.source === 'stackoverflow'))
  const searched = (src) => (r?.sources ?? []).includes(src)
  const AUDIT_LABEL = { board: "This event's board", github_people: 'GitHub profiles', stackoverflow_experts: "Stack Overflow's top answerers" }
  const audits = $derived((r?.audit ?? []).filter((a) => !a.error && AUDIT_LABEL[a.source]).map((a) => ({
    label: AUDIT_LABEL[a.source], received: a.received, kept: a.kept,
    why: Object.entries(a.excluded ?? {}).map(([k, n]) => `${n} ${k}`).join('; '),
  })))

  const list = (v) => (Array.isArray(v) ? v.join(', ') : v ?? '')
  function startEdit() {
    const p = me
    form = {
      kind: p?.kind ?? 'hacker', name: p?.name ?? '', contact: p?.contact ?? '', skills: list(p?.skills),
      looking_for: list(p?.looking_for), interests: list(p?.interests), idea: p?.idea ?? '', availability: p?.availability ?? '',
      team_name: p?.team?.name ?? '', team_size: p?.team?.size ?? 1, github: p?.github ?? '', github_consent: !!p?.github_consent,
    }
    editing = true
  }

  async function save(e) {
    e.preventDefault()
    if (!form.name.trim()) return
    const res = await h.saveProfile({
      kind: form.kind, name: form.name, contact: form.contact, skills: form.skills, looking_for: form.looking_for,
      interests: form.interests, idea: form.idea, availability: form.availability,
      team: { name: form.team_name, size: Number(form.team_size) || 1 }, github: form.github.trim(),
      github_consent: form.github_consent && !!form.github.trim(),
    })
    if (res) {
      editing = false
      if (form.github_consent && form.github.trim()) setTimeout(() => h.refreshBoard(), 2500) // the GitHub check runs in the background
    }
  }

  const people = $derived((h.board?.profiles ?? []).filter((p) => filter === 'all' || p.kind === filter))
  const verifiedSkills = $derived(me?.verified?.found ? Object.entries(me.verified.skills ?? {}) : [])
</script>

<section class="mine" data-testid="hub-my-card">
  {#if editing && form}
    <form class="card form" onsubmit={save} data-testid="hub-profile-form">
      <div class="fh"><UserPlus size={13} /> {me ? 'Edit your card' : 'Put yourself on the board'}
        <button type="button" class="btn sm icon ghost" onclick={() => (editing = false)} aria-label="Cancel"><X size={13} /></button></div>
      <div class="seg" role="radiogroup" aria-label="I am">
        <button type="button" role="radio" aria-checked={form.kind === 'hacker'} class:sel={form.kind === 'hacker'} onclick={() => (form.kind = 'hacker')}>Hacker</button>
        <button type="button" role="radio" aria-checked={form.kind === 'mentor'} class:sel={form.kind === 'mentor'} onclick={() => (form.kind = 'mentor')}>Mentor</button>
      </div>
      <label>Name or nickname<input class="input" bind:value={form.name} maxlength="40" required data-testid="hub-p-name" /></label>
      <label>{form.kind === 'mentor' ? 'What you can help with' : 'Your skills'} <span class="hint">comma-separated</span>
        <input class="input" bind:value={form.skills} maxlength="300" placeholder="svelte, python, figma" data-testid="hub-p-skills" /></label>
      {#if form.kind === 'hacker'}
        <label>Looking for <span class="hint">roles or skills</span><input class="input" bind:value={form.looking_for} maxlength="200" placeholder="backend, design" data-testid="hub-p-looking" /></label>
        <label>Interests / tracks<input class="input" bind:value={form.interests} maxlength="200" placeholder="health, education" /></label>
        <label>Idea (optional)<input class="input" bind:value={form.idea} maxlength="240" /></label>
        <div class="two">
          <label>Team name<input class="input" bind:value={form.team_name} maxlength="40" placeholder="solo" /></label>
          <div class="field"><span class="fl" id="team-size-l">People now</span>
            <div class="stepper" role="group" aria-labelledby="team-size-l">
              <button type="button" class="step" onclick={() => (form.team_size = Math.max(1, Number(form.team_size) - 1))}
                      disabled={form.team_size <= 1} aria-label="One fewer"><Minus size={13} /></button>
              <span class="val num" aria-live="polite" data-testid="hub-p-size">{form.team_size}</span>
              <button type="button" class="step" onclick={() => (form.team_size = Math.min(6, Number(form.team_size) + 1))}
                      disabled={form.team_size >= 6} aria-label="One more"><Plus size={13} /></button>
            </div>
          </div>
        </div>
      {/if}
      <label>Availability<input class="input" bind:value={form.availability} maxlength="40" placeholder="all night / until 2 am" /></label>
      <label>How to reach you (optional)<input class="input" bind:value={form.contact} maxlength="80" placeholder="Discord name, table number…" /></label>
      <label>GitHub username (optional)<input class="input" bind:value={form.github} maxlength="39" placeholder="octocat" data-testid="hub-p-github" /></label>
      {#if form.github.trim()}
        <label class="check"><input type="checkbox" bind:checked={form.github_consent} data-testid="hub-p-consent" />
          Read the <b>public</b> repositories of this GitHub account to show which of my skills they use (GitHub's API;
          nothing else is read). Only type your own — the hub cannot check that an account is yours, and says so.</label>
      {/if}
      <p class="privacy"><ShieldCheck size={12} /> Your card is visible to everyone using this app at the event and is kept on
        this server until you delete it. When someone asks {app.persona} for teammates and your card fits, it goes to
        the language model (OpenAI) — without the “how to reach you” line. Don't put anything private on it.</p>
      <div class="row"><button class="btn primary sm" type="submit" disabled={h.busy || !form.name.trim()} data-testid="hub-p-save"><Send size={13} /> Save my card</button></div>
    </form>
  {:else if me}
    <div class="card me">
      <div class="fh"><Users size={13} /> Your card — {me.kind === 'mentor' ? 'mentor' : 'hacker'}
        <button class="btn sm icon ghost" onclick={startEdit} aria-label="Edit your card" title="Edit"><Pencil size={13} /></button>
        <button class="btn sm icon ghost" onclick={() => h.deleteProfile()} aria-label="Delete your card" title="Delete" data-testid="hub-p-delete"><Trash size={13} /></button></div>
      <div class="name">{me.name}</div>
      <div class="skills">{#each me.skills ?? [] as s, i (i)}<span class="skill">{s}</span>{/each}</div>
      {#if me.looking_for?.length}<div class="sub">looking for: {me.looking_for.join(', ')}</div>{/if}
      {#if verifiedSkills.length}
        <div class="sub seen"><BadgeCheck size={12} /> seen in your public GitHub repos: {verifiedSkills.map(([s, e]) => `${s} (${e.repos})`).join(', ')}</div>
      {:else if me.github_consent && !me.verified}
        <div class="sub">Checking your public GitHub repos…</div>
      {:else if me.verified && me.verified.found === false}
        <div class="sub warn">GitHub has no public account called {me.github}.</div>
      {:else if me.verified && me.verified.found == null && me.verified.error}
        <div class="sub warn">GitHub could not be checked right now ({me.verified.error}) — save the card again later.</div>
      {/if}
    </div>
  {:else}
    <div class="empty-card">
      <p>Put yourself on the board so teams and mentors can find you — or just ask {app.persona} to find people.</p>
      <button class="btn sm primary" onclick={startEdit} data-testid="hub-p-new"><UserPlus size={13} /> Create my card</button>
    </div>
  {/if}
</section>

<div class="acts">
  <button class="btn sm" onclick={() => h.findTeammates()} disabled={app.busy} data-testid="hub-find-team"><Search size={13} /> Find teammates</button>
  <button class="btn sm" onclick={() => h.findMentor()} disabled={app.busy} data-testid="hub-find-mentor"><GraduationCap size={13} /> Find a mentor</button>
</div>
<div class="roles" role="group" aria-label="Find a teammate for a role">
  <span class="rl">Need someone for</span>
  {#each ROLE_CHIPS as c (c.key)}
    <button class="rchip" onclick={() => h.findRole(c.key)} disabled={app.busy} data-testid="hub-role-{c.key}">{c.label}</button>
  {/each}
</div>
<p class="how"><Info size={12} /> {app.persona} looks on this event's board first, then at real public GitHub profiles{#if app.health?.hub?.event_location}{' '}in {app.health.hub.event_location}{/if}
  whose repositories use what you need; mentors also come from Stack Overflow's top answerers for your stack.</p>

{#if r}
  <h3>{r.kind === 'team' ? 'Teammates' : 'Mentors'}{#if r.query?.needs?.length}{' '}for <b>{r.query.needs.join(', ')}</b>{/if}</h3>
  {#each r.errors ?? [] as e, i (i)}<div class="warnline" role="status"><CircleAlert size={12} /> {e.source} could not be read: {e.message}</div>{/each}
  {#each r.hints ?? [] as t, i (i)}<div class="hint"><Info size={12} /> {t}</div>{/each}
  <div class="list" data-testid="hub-matches">
    {#if r.kind === 'team'}
      <div class="grp"><Users size={12} /> On this event's board</div>
      {#each onBoard as x (x.ref)}<HubItem {x} />{:else}<p class="none">Nobody on the board fits yet.</p>{/each}
      {#if searched('github_people') || onGithub.length}
        <div class="grp"><FolderGit size={12} /> Public GitHub profiles{#if city}{' '}· {city}{/if}{#if r.query?.languages?.length}{' '}· {r.query.languages.join(' / ')}{/if}</div>
        {#each onGithub as x (x.ref)}<HubItem {x} />{:else}<p class="none">No public profile fits.</p>{/each}
      {/if}
      {#if boardMentors.length}
        <div class="grp"><GraduationCap size={12} /> Mentors on this board</div>
        {#each boardMentors as x (x.ref)}<HubItem {x} />{/each}
      {/if}
    {:else}
      <div class="grp"><GraduationCap size={12} /> Mentors on this board</div>
      {#each boardMentors as x (x.ref)}<HubItem {x} />{:else}<p class="none">No mentor has put a card on the board yet.</p>{/each}
      {#if searched('stackoverflow_experts') || experts.length}
        <div class="grp"><Award size={12} /> Public experts · Stack Overflow{#if r.query?.tags?.length}{' '}· {r.query.tags.map((t) => `[${t}]`).join(' ')}{/if}</div>
        {#each experts as x (x.ref)}<HubItem {x} />{:else}<p class="none">No top answerer fits.</p>{/each}
      {/if}
    {/if}
  </div>
  {#if audits.length}
    <ul class="audit" data-testid="hub-people-audit">
      {#each audits as a, i (i)}
        <li>{a.label}: {a.received} read, {a.kept} kept{#if a.why}{' '}(left out: {a.why}){/if}</li>
      {/each}
    </ul>
  {/if}
{/if}

<button class="all-t" onclick={() => (showAll = !showAll)} aria-expanded={showAll} data-testid="hub-people-toggle">
  <Users size={12} /> Everyone on the board ({(h.board?.profiles ?? []).length})
</button>
{#if showAll}
  <div class="filters">
    {#each [['all', 'All'], ['hacker', 'Hackers'], ['mentor', 'Mentors']] as [k, label] (k)}
      <button class="btn sm" class:primary={filter === k} onclick={() => (filter = k)}>{label}</button>
    {/each}
  </div>
  <ul class="people">
    {#each people as p (p.id)}
      <li><b>{p.name}</b> <span class="k">{p.kind}</span> {(p.skills ?? []).slice(0, 5).join(', ')}
        {#if p.availability}<span class="k">· {p.availability}</span>{/if}</li>
    {:else}
      <li class="k">Nobody has put a card here yet — be the first.</li>
    {/each}
  </ul>
{/if}

<style>
  .mine { display: flex; flex-direction: column; }
  .form, .me { display: flex; flex-direction: column; gap: 7px; padding: 10px 12px; }
  .fh { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 600; color: var(--text-2); }
  .fh .btn:first-of-type { margin-left: auto; }
  label { display: flex; flex-direction: column; gap: 3px; font-size: 11.5px; color: var(--muted); }
  label .hint { color: var(--faint); font-weight: 400; }
  .check { flex-direction: row; align-items: flex-start; gap: 7px; color: var(--text-2); font-size: 12px; }
  .check b { color: var(--text); }
  .two { display: grid; grid-template-columns: 2fr 1fr; gap: 8px; }
  .seg { display: inline-flex; gap: 4px; padding: 2px; border-radius: 9px; background: var(--well-bg); box-shadow: var(--sink); align-self: flex-start; }
  .seg button { height: 26px; padding: 0 10px; border: 0; border-radius: 7px; background: transparent; color: var(--muted); font-size: 12px; font-weight: 600; cursor: pointer; }
  .seg button.sel { background: var(--sheen), var(--raise-hi); color: var(--text); box-shadow: var(--ring-2), var(--rise-1); }
  .privacy { display: flex; gap: 6px; margin: 0; font-size: 11.5px; color: var(--faint); line-height: 1.45; }
  .row, .acts, .filters { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .name { font-weight: 650; color: var(--text); }
  .skills { display: flex; flex-wrap: wrap; gap: 4px; }
  .skill { padding: 1px 7px; border-radius: 999px; font-size: 11.5px; color: var(--text-2); background: var(--well-bg); box-shadow: var(--sink); }
  .sub { font-size: 11.5px; color: var(--muted); display: flex; align-items: center; gap: 5px; }
  .sub.seen { color: var(--ok); }
  .sub.warn { color: var(--warn); }
  .empty-card { display: flex; flex-direction: column; gap: 8px; align-items: flex-start; font-size: 12.5px; color: var(--text-2); }
  .empty-card p { margin: 0; }
  h3 { margin: 6px 0 0; font-size: 12px; font-weight: 650; color: var(--text-2); }
  h3 b { color: var(--text); }
  .list { display: flex; flex-direction: column; gap: 8px; }
  .none { margin: 0; font-size: 12.5px; color: var(--muted); }
  .all-t { align-self: flex-start; display: inline-flex; align-items: center; gap: 5px; border: 0; background: none; color: var(--muted); font-size: 11.5px; cursor: pointer; padding: 4px 0; }
  .people { margin: 0; padding-left: 16px; font-size: 12px; color: var(--text-2); display: flex; flex-direction: column; gap: 3px; }
  .people .k { color: var(--faint); }
  .field { display: flex; flex-direction: column; gap: 3px; }
  .fl { font-size: 11.5px; color: var(--muted); }
  .stepper { display: inline-flex; align-items: center; justify-content: space-between; height: 34px; padding: 3px;
    border-radius: var(--radius-xs); background: var(--sheen-well), var(--well); border: 1px solid var(--edge); box-shadow: var(--sink); }
  .step { width: 28px; height: 26px; display: inline-grid; place-items: center; border: 0; border-radius: 6px; background: var(--sheen), var(--raise);
    color: var(--text-2); box-shadow: var(--rise-1); transition: background var(--t1) var(--ease), color var(--t1) var(--ease); }
  .step:hover:not(:disabled) { background: var(--sheen), var(--raise-hi); color: var(--text); }
  .step:disabled { opacity: .35; box-shadow: none; }
  .val { min-width: 24px; text-align: center; font-weight: 650; color: var(--text); }
  .roles { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .rl { font-size: 11.5px; color: var(--muted); margin-right: 2px; }
  .rchip { height: 26px; padding: 0 10px; border-radius: 999px; border: 1px solid var(--edge); background: var(--sheen), var(--raise);
    color: var(--text-2); font-size: 12px; font-weight: 580; box-shadow: var(--rise-1);
    transition: background var(--t2) var(--ease), color var(--t2) var(--ease), transform var(--t2) var(--ease), border-color var(--t2) var(--ease); }
  .rchip:hover:not(:disabled) { color: var(--text); border-color: color-mix(in srgb, var(--accent) 45%, transparent); transform: translateY(-1px); }
  .rchip:disabled { opacity: .45; }
  .how, .hint, .warnline { display: flex; gap: 6px; align-items: flex-start; margin: 0; font-size: 11.5px; line-height: 1.45; color: var(--faint); }
  .how :global(svg), .hint :global(svg) { flex: 0 0 auto; margin-top: 2px; color: var(--accent-2); }
  .hint { color: var(--muted); }
  .warnline { color: var(--warn); }
  .warnline :global(svg) { flex: 0 0 auto; margin-top: 2px; }
  .grp { display: flex; align-items: center; gap: 6px; margin-top: 4px; font-size: 11px; font-weight: 650; letter-spacing: .06em;
    text-transform: uppercase; color: var(--faint); }
  .grp :global(svg) { color: var(--accent); }
  .audit { margin: 0; padding-left: 16px; font-size: 11px; color: var(--faint); display: flex; flex-direction: column; gap: 2px; }
</style>
