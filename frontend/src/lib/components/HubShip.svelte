<script>
  import { app } from '$lib/app.svelte.js'
  import { minutes } from '$lib/hub.svelte.js'
  import { Rocket, CalendarClock, CalendarDays, ClockAlert, Check, Hourglass, PartyPopper, HandHelping, Send, Lightbulb } from '$lib/icons.js'
  import DateTimePicker from './DateTimePicker.svelte'

  const h = app.hub
  const st = $derived(h.ship)
  let now = $state(Date.now())
  let picking = $state(false) // the date-and-time picker is open

  $effect(() => {
    const t = setInterval(() => (now = Date.now()), 30_000)
    return () => clearInterval(t)
  })

  const left = $derived.by(() => {
    if (!st?.deadline) return null
    const ms = st.deadline * 1000 - now
    if (ms <= 0) return 'deadline passed'
    const m = Math.round(ms / 60000)
    return `${minutes(m)} left`
  })
  const pct = $derived(st ? Math.round((st.done / st.total) * 100) : 0)
  const expectedPct = $derived(st?.elapsed != null ? Math.round(st.elapsed * 100) : null)

  function preset(hours) {
    h.setDeadline(Math.round(Date.now() / 1000 + hours * 3600))
  }

  async function picked(d) {
    await h.setDeadline(Math.round(d.getTime() / 1000))
    picking = false
  }
</script>

{#if st}
  <section class="card dl" data-testid="hub-ship">
    <div class="fh"><CalendarClock size={14} /> Deadline
      {#if st.deadline}<span class="left num" class:urgent={st.hours_left != null && st.hours_left <= 3} data-testid="hub-left">{left}</span>{/if}
    </div>
    {#if st.deadline && !picking}
      <div class="sub" data-testid="hub-dl-when">{new Date(st.deadline * 1000).toLocaleString('en-US', { weekday: 'short', month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
        {#if st.pace}{' · '}<b class:behind={st.pace !== 'on track'}>{st.pace}</b>{/if}
        <button class="link" onclick={() => (picking = true)} data-testid="hub-dl-change">change</button>
        <button class="link" onclick={() => h.setDeadline(null)}>clear</button></div>
    {:else if !picking}
      <div class="presets">
        <span class="sub">When are submissions due?</span>
        {#each [6, 12, 24, 36] as hrs (hrs)}<button class="btn sm" onclick={() => preset(hrs)} data-testid="hub-dl-{hrs}">in {hrs} h</button>{/each}
        <button class="btn sm" onclick={() => (picking = true)} data-testid="hub-dl-pick"><CalendarDays size={13} /> Pick a date &amp; time</button>
      </div>
    {/if}
    {#if picking}
      <DateTimePicker initial={st.deadline ? new Date(st.deadline * 1000) : null} maxDays={30} onset={picked}
                      oncancel={() => (picking = false)} />
    {/if}
  </section>

  <section class="card ms">
    <div class="fh"><Rocket size={14} /> Road to shipping <span class="num cnt">{st.done} / {st.total}</span></div>
    <div class="bar" title="Done vs. where you'd be on an even pace">
      <i class="fill" style:width="{pct}%"></i>
      {#if expectedPct != null}<i class="exp" style:left="{expectedPct}%" title="An even pace would be here"></i>{/if}
    </div>
    <ol class="steps" data-testid="hub-milestones">
      {#each st.milestones as m (m.key)}
        <li class:done={m.done}>
          <label><input type="checkbox" checked={m.done} onchange={(e) => h.toggleMilestone(m.key, e.currentTarget.checked)} data-testid="hub-ms-{m.key}" />
            <span>{m.title}</span></label>
          {#if m.done && m.done_at}<span class="when">{new Date(m.done_at * 1000).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}</span>
          {:else if m.due_at && !m.done && m.due_at * 1000 < now}<span class="when late">due</span>{/if}
        </li>
      {/each}
    </ol>
  </section>

  {#if st.roadblocks?.length}
    <section class="card rb">
      <div class="fh"><ClockAlert size={14} /> Roadblocks</div>
      {#each [...st.roadblocks].reverse() as r (r.id)}
        {@const mins = r.status === 'open' ? Math.max(0, Math.round((now / 1000 - r.started) / 60)) : Math.round(((r.ended ?? r.started) - r.started) / 60)}
        <div class="rbi" class:open={r.status === 'open'} class:ask={r.status === 'open' && mins >= 30} data-testid="hub-roadblock">
          <span class="t">{r.title}</span>
          <span class="m num">{r.status === 'open' ? `stuck ${minutes(mins)}` : `${r.status} after ${minutes(mins)}`}</span>
          {#if r.status === 'open'}
            <span class="acts">
              <button class="btn sm" onclick={() => h.closeRoadblock(r.id, 'solved')}><Check size={12} /> Solved</button>
              <button class="btn sm ghost" onclick={() => { h.tab = 'help' }}><HandHelping size={12} /> Ask a person</button>
            </span>
          {/if}
        </div>
      {/each}
    </section>
  {/if}

  {#if st.nudges?.length}
    <section class="nudges" data-testid="hub-nudges">
      {#each st.nudges as n, i (i)}
        <div class="nudge">{#if n.startsWith('Everything is shipped')}<PartyPopper size={13} />{:else if n.startsWith('30-minute')}<Hourglass size={13} />{:else}<Lightbulb size={13} />{/if} {n}</div>
      {/each}
    </section>
  {/if}

  <button class="btn sm" onclick={() => h.askShip()} disabled={app.busy} data-testid="hub-ask-ship"><Send size={13} /> Ask {app.persona} how we're doing</button>
{:else}
  <p class="none">The ship plan loads with the session.</p>
{/if}

<style>
  .card { padding: 10px 12px; display: flex; flex-direction: column; gap: 7px; }
  .fh { display: flex; align-items: center; gap: 6px; font-size: 12.5px; font-weight: 650; color: var(--text-2); }
  .fh :global(svg) { color: var(--accent); }
  .left { margin-left: auto; font-size: 18px; font-weight: 700; color: var(--text); font-family: var(--font-display); }
  .left.urgent { color: var(--warn); }
  .cnt { margin-left: auto; color: var(--muted); }
  .sub { font-size: 12px; color: var(--muted); }
  .sub b { color: var(--ok); }
  .sub b.behind { color: var(--warn); }
  .link { border: 0; background: none; color: var(--accent); cursor: pointer; font-size: 12px; margin-left: 6px; }
  .presets { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .bar { position: relative; height: 8px; border-radius: 999px; background: var(--well-bg); box-shadow: var(--sink); overflow: visible; }
  .fill { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; background: var(--primary-bg); transition: width .5s ease; }
  .exp { position: absolute; top: -3px; bottom: -3px; width: 2px; border-radius: 2px; background: var(--warn); }
  .steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }
  .steps li { display: flex; align-items: center; gap: 8px; font-size: 12.5px; color: var(--text-2); }
  .steps li.done span { color: var(--muted); text-decoration: line-through; text-decoration-color: color-mix(in srgb, var(--ok) 60%, transparent); }
  .steps label { display: flex; align-items: center; gap: 7px; cursor: pointer; }
  .steps .when { margin-left: auto; font-size: 11px; color: var(--faint); }
  .steps .when.late { color: var(--warn); }
  .rbi { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 12px; color: var(--muted); padding: 5px 0; border-top: 1px solid var(--line); }
  .rbi.open { color: var(--text-2); }
  .rbi.ask .m { color: var(--warn); font-weight: 650; }
  .rbi .t { flex: 1 1 200px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rbi .acts { display: flex; gap: 4px; }
  .nudges { display: flex; flex-direction: column; gap: 6px; }
  .nudge { display: flex; gap: 7px; align-items: flex-start; font-size: 12.5px; color: var(--text); padding: 8px 10px; border-radius: 8px;
    background: color-mix(in srgb, var(--warn) 9%, var(--plane)); box-shadow: 0 0 0 1px color-mix(in srgb, var(--warn) 22%, transparent); }
  .nudge :global(svg) { color: var(--warn); flex: 0 0 auto; margin-top: 2px; }
  .none { margin: 0; font-size: 12.5px; color: var(--muted); }
  .btn.sm { align-self: flex-start; }
</style>
