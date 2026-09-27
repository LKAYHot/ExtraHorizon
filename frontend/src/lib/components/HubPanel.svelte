<script>
  import { app } from '$lib/app.svelte.js'
  import { HUB_TABS } from '$lib/hub.svelte.js'
  import { LifeBuoy, ScanFace, X, LoaderCircle, Check, CircleAlert } from '$lib/icons.js'
  import HubHelp from './HubHelp.svelte'
  import HubPeople from './HubPeople.svelte'
  import HubBoard from './HubBoard.svelte'
  import HubShip from './HubShip.svelte'

  const h = app.hub
  const open = $derived((h.board?.requests ?? []).filter((r) => r.status === 'open').length)
  const askNow = $derived((h.ship?.stuck ?? []).some((r) => r.ask_now))
  const offline = $derived(h.offline || !!h.report?.offline)
  const running = $derived(h.run.state === 'running')
  const STEP = {
    signature: 'Reading the error — only its signature is searched', topic: 'Reading the topic',
    stackoverflow: 'Stack Overflow', github: 'GitHub', registries: 'npm / PyPI registries', devto: 'DEV Community',
    board: "This event's board — peers and mentors",
  }
  const PEOPLE_STEP = { board: "This event's board", github: 'GitHub — public profiles', stackoverflow: 'Stack Overflow — top answerers' }
  const people = $derived(h.run.kind === 'team' || h.run.kind === 'mentors')
  const label = (step) => (people && PEOPLE_STEP[step]) || STEP[step] || step
  // the latest state of every step, in the order they started
  const steps = $derived.by(() => {
    const m = new Map()
    for (const s of h.run.steps) if (s.step && s.step !== 'wait') m.set(s.step, { ...(m.get(s.step) ?? {}), ...s })
    return [...m.values()]
  })
  const waiting = $derived(h.run.steps.at(-1)?.step === 'wait')

  // at an event the board changes by itself (other teams, mentors): keep it fresh while the hub is open
  $effect(() => {
    const t = setInterval(() => { if (!document.hidden) h.refreshBoard() }, 20_000)
    return () => clearInterval(t)
  })
</script>

<aside class="panel hub" aria-label="Hackathon hub" data-testid="hub-panel">
  <header class="head">
    <div class="title"><LifeBuoy size={16} /> <h2>Hackathon hub</h2>
      <span class="chip" class:warn={offline} data-testid="hub-source-chip">{offline ? 'TEST FIXTURE' : 'public sources + this event'}</span>
    </div>
    <div class="actions">
      <button class="btn sm icon ghost" onclick={() => (app.view = 'tutor')} title="Back to the camera panel (the hub stays open)"
              aria-label="Back to the camera panel" data-testid="hub-hide"><ScanFace size={14} /></button>
      {#if h.report}
        <button class="btn sm icon ghost" onclick={() => h.close()} title="Close these results (a new roadblock or a request for teammates still searches)"
                aria-label="Close these results" data-testid="hub-close"><X size={14} /></button>
      {/if}
    </div>
  </header>

  <div class="tabs" role="tablist">
    {#each HUB_TABS as t (t.key)}
      <button role="tab" aria-selected={h.tab === t.key} class:sel={h.tab === t.key} onclick={() => (h.tab = t.key)}
              data-testid="hub-tab-{t.key}">
        {t.label}
        {#if t.key === 'board' && open}<span class="badge num">{open}</span>{/if}
        {#if t.key === 'ship' && askNow}<span class="badge warn" title="Stuck for 30 minutes — ask a person">!</span>{/if}
      </button>
    {/each}
  </div>

  <div class="scroll">
    {#if running}
      <section class="build" data-testid="hub-build" aria-live="polite">
        <div class="build-h"><LoaderCircle size={13} class="spin" /> {app.persona} is checking {people ? "this event's board and public profiles" : 'the public sources'}…</div>
        <ol>
          {#each steps as s (s.step)}
            <li class:done={s.phase === 'done' || s.state === 'done'} class:failed={s.phase === 'failed'}>
              {#if s.phase === 'failed'}<CircleAlert size={12} />{:else if s.phase === 'done'}<Check size={12} />{:else}<LoaderCircle size={12} class="spin" />{/if}
              <span class="st">{label(s.step)}</span>
              {#if s.phase === 'done' && s.received != null}<span class="n num">{s.received} read · {s.kept} kept</span>{/if}
              {#if s.phase === 'done' && s.query}<span class="n q">“{s.query}”</span>{/if}
              {#if s.phase === 'failed'}<span class="n warn">{s.message}</span>{/if}
            </li>
          {/each}
          {#if waiting}<li class="wait"><LoaderCircle size={12} class="spin" /> <span class="st">A source is slow — still waiting</span></li>{/if}
        </ol>
      </section>
    {/if}
    {#if h.run.state === 'error'}
      <section class="card err" role="alert"><CircleAlert size={15} /> {h.run.error}</section>
    {/if}

    {#if h.tab === 'help'}<HubHelp />{:else if h.tab === 'people'}<HubPeople />{:else if h.tab === 'board'}<HubBoard />{:else}<HubShip />{/if}
  </div>
</aside>

<style>
  .hub { display: flex; flex-direction: column; min-width: 0; min-height: 0; border-left: 1px solid var(--line);
    background: linear-gradient(180deg, rgb(10 16 34 / .5), rgb(8 13 28 / .35)); }
  .head { display: flex; align-items: center; justify-content: space-between; gap: 8px; padding: 12px 16px 10px; border-bottom: 1px solid var(--line); }
  .title { display: flex; align-items: center; gap: 8px; min-width: 0; }
  .title :global(svg) { color: var(--accent); }
  h2 { font-size: 15px; font-weight: 650; margin: 0; white-space: nowrap; }
  .actions { display: flex; gap: 6px; }
  .tabs { display: flex; gap: 4px; padding: 10px 16px 0; }
  .tabs button { position: relative; display: inline-flex; align-items: center; gap: 6px; height: 30px; padding: 0 11px; border: 0;
    border-radius: 8px 8px 0 0; background: transparent; color: var(--muted); font-size: 12.5px; font-weight: 600; cursor: pointer;
    border-bottom: 2px solid transparent; }
  .tabs button:hover { color: var(--text-2); }
  .tabs button.sel { color: var(--text); border-bottom-color: var(--accent); background: linear-gradient(180deg, transparent, color-mix(in srgb, var(--accent) 8%, transparent)); }
  .badge { min-width: 17px; height: 17px; padding: 0 5px; border-radius: 999px; display: inline-grid; place-items: center; font-size: 10.5px;
    background: color-mix(in srgb, var(--accent) 22%, var(--raise)); color: var(--text); }
  .badge.warn { background: color-mix(in srgb, var(--warn) 30%, var(--raise)); color: var(--warn); font-weight: 750; }
  .scroll { flex: 1; min-height: 0; overflow-y: auto; padding: 12px 16px 18px; display: flex; flex-direction: column; gap: 10px;
    border-top: 1px solid var(--line); }
  .build { padding: 10px 12px; border-radius: var(--radius-sm); background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1);
    animation: rise .3s ease-out both; }
  .build-h { display: flex; align-items: center; gap: 7px; font-size: 12.5px; color: var(--text-2); font-weight: 600; margin-bottom: 6px; }
  .build ol { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 4px; }
  .build li { display: flex; align-items: center; gap: 7px; font-size: 12px; color: var(--muted); animation: rise .25s ease-out both; }
  .build li.done { color: var(--text-2); }
  .build li.done :global(svg) { color: var(--ok); }
  .build li.failed :global(svg), .warn { color: var(--warn); }
  .build .n { margin-left: auto; color: var(--faint); font-size: 11.5px; }
  .build .n.q { max-width: 55%; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .err { display: flex; gap: 8px; align-items: center; padding: 10px 12px; color: var(--warn); font-size: 12.5px;
    background: color-mix(in srgb, var(--warn) 10%, transparent); }
  :global(.hub .spin) { animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes rise { from { opacity: 0; transform: translateY(4px); } }
  @media (prefers-reduced-motion: reduce) { .build, .build li { animation: none; } :global(.hub .spin) { animation: none; } }
</style>
