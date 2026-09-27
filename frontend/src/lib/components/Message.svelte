<script>
  import { app } from '$lib/app.svelte.js'
  import { renderMarkdown } from '$lib/markdown.js'
  import { hideOpenCue } from '$lib/cues.js'
  import { COLOR, LABEL } from '$lib/emotions.js'
  import { RefreshCw, CircleAlert, Mic, ScanFace, ChevronDown, Hand, AudioLines, Construction, Check, LoaderCircle, MapIcon, Search, LifeBuoy, Users, BookOpen, Rocket } from '$lib/icons.js'
  import { refsOf } from '$lib/hub.svelte.js'
  import Logo from './Logo.svelte'

  let { m, isLast = false } = $props()

  const streaming = $derived(m.status === 'pending' || m.status === 'streaming')
  const html = $derived(m.role === 'assistant'
    ? renderMarkdown(streaming ? hideOpenCue(m.text) : m.text, {
      // "F12" in an older answer is the old F12: buttons only while the panel shows the report it was about
      fids: !!m.analysis?.report_id && m.analysis.report_id === app.coordReport?.id,
      // …and "S2" only while the hub shows the search this answer was about
      hids: m.hub?.report_id && m.hub.report_id === app.hub.report?.id ? new Set(refsOf(app.hub.report)) : null }) : '')
  const tools = $derived(m.role === 'assistant' ? (m.analysis?.tools ?? m.hub?.tools ?? []) : [])
  // a finding ID in her answer shows that finding on the map; a hub ID shows that result
  function onBodyClick(e) {
    const b = e.target?.closest?.('[data-fid]')
    if (b) app.selectFinding(b.dataset.fid)
    const h = e.target?.closest?.('[data-hid]')
    if (h) app.hub.select(h.dataset.hid)
  }
  const TOOL_LABEL = { find_findings: 'looked up', get_project: 'looked up project', show_on_map: 'showed on the map',
                       recheck_finding: 're-checked live', get_hub_item: 'looked up', search_public_help: 'searched public sources for',
                       find_people: 'looked on the board for', learning_resources: 'looked for resources on' }
  const hub = $derived(m.role === 'assistant' ? m.hub : null)
  const hubLive = $derived(hub?.live)
  const HUB_RUNNING = { unstuck: 'Searching Stack Overflow, GitHub and the package registries — and this event’s board…',
                        learn: 'Looking for starters, articles and top questions…', team: 'Looking at the board for teammates…',
                        mentors: 'Looking at the board for mentors…' }
  const HUB_TITLE = { unstuck: 'Get unstuck', learn: 'Learn', team: 'Teammates', mentors: 'Mentors', ship: 'Ship status' }
  const speaking = $derived(
    m.role === 'assistant' && m.turn_no != null && app.voice.playing && app.voice.playingKind === 'answer' && app.voice.playingTurn === m.turn_no,
  )
  const ctx = $derived(m.emotion_context)
  const an = $derived(m.role === 'assistant' ? m.analysis : null)
  const live = $derived(an?.live)
  const check = $derived(an?.check ?? hub?.check)
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
      {#if an?.mode === 'run'}
        {@const running = live ? live.state === 'running' || live.state === 'progress' : streaming}
        <div class="an-card" data-testid="analysis-card" data-state={running ? 'running' : (live?.state ?? 'done')}>
          <Construction size={14} />
          <div class="an-text">
            {#if running}
              <span class="an-t"><LoaderCircle size={12} class="spin" /> Reading Miami-Dade's open data and verifying every record…</span>
            {:else if live?.state === 'error'}
              <span class="an-t warn">Analysis failed: {live.message}</span>
            {:else if live?.state === 'cancelled'}
              <span class="an-t">The analysis was stopped before it finished.</span>
            {:else if live?.state === 'ready'}
              <span class="an-t">Utility coordination — {live.findings.toLocaleString('en-US')} overlaps between {live.plans} plans ·
                {live.projects.toLocaleString('en-US')} verified projects{#if live.offline}{' · '}<b class="warn">test fixture</b>{/if}</span>
            {:else}
              <span class="an-t">Utility-coordination analysis</span>
            {/if}
          </div>
          {#if !running && live?.state !== 'error' && live?.state !== 'cancelled' && app.coordReport}
            <button class="btn sm" onclick={() => app.openAnalysis()}><MapIcon size={12} /> Map</button>
          {/if}
        </div>
      {/if}
      {#if hub?.mode === 'run'}
        {@const running = hub.kind !== 'ship' && (hubLive ? hubLive.state === 'running' || hubLive.state === 'progress' : streaming)}
        <div class="an-card hub" data-testid="hub-card" data-state={running ? 'running' : (hubLive?.state ?? 'done')}>
          {#if hub.kind === 'team' || hub.kind === 'mentors'}<Users size={14} />{:else if hub.kind === 'learn'}<BookOpen size={14} />{:else if hub.kind === 'ship'}<Rocket size={14} />{:else}<LifeBuoy size={14} />{/if}
          <div class="an-text">
            {#if running}
              <span class="an-t"><LoaderCircle size={12} class="spin" /> {HUB_RUNNING[hub.kind] ?? 'Searching…'}</span>
            {:else if hubLive?.state === 'error'}
              <span class="an-t warn">Search failed: {hubLive.message}</span>
            {:else if hubLive?.state === 'cancelled'}
              <span class="an-t">The search was stopped before it finished.</span>
            {:else if hubLive?.state === 'ready' && hub.kind !== 'ship'}
              {@const n = hub.kind === 'mentors' ? hubLive.mentors : hubLive.items}
              <span class="an-t">{HUB_TITLE[hub.kind]} — {n} {hub.kind === 'team' ? 'match' : hub.kind === 'mentors' ? 'mentor' : 'verified result'}{n === 1 ? '' : (hub.kind === 'team' ? 'es' : 's')}{#if hubLive.peers}{' · '}{hubLive.peers} from peers here{/if}{#if hubLive.mentors && hub.kind !== 'mentors'}{' · '}{hubLive.mentors} mentor{hubLive.mentors === 1 ? '' : 's'}{/if}{#if hubLive.errors}{' · '}<b class="warn">{hubLive.errors} source{hubLive.errors === 1 ? '' : 's'} unreachable</b>{/if}{#if hubLive.offline}{' · '}<b class="warn">test fixture</b>{/if}</span>
            {:else}
              <span class="an-t">Hackathon hub · {HUB_TITLE[hub.kind] ?? ''}</span>
            {/if}
          </div>
          {#if !running && hubLive?.state !== 'error' && hubLive?.state !== 'cancelled'}
            <button class="btn sm" onclick={() => { app.view = 'hub'; if (hub.kind === 'ship') app.hub.tab = 'ship' }} data-testid="hub-open"><LifeBuoy size={12} /> Hub</button>
          {/if}
        </div>
      {/if}
      {#if tools.length}
        <div class="tools" data-testid="tool-tags">
          {#each tools as t, i (i)}
            <span class="tag tool" class:recheck={t.name === 'recheck_finding'} title="{TOOL_LABEL[t.name] ?? t.name}: {t.summary}">
              {#if t.name === 'recheck_finding'}<RefreshCw size={11} />{:else if t.name === 'show_on_map'}<MapIcon size={11} />{:else}<Search size={11} />{/if}
              {TOOL_LABEL[t.name] ?? t.name}{#if t.summary}{' '}<b>{t.summary}</b>{/if}</span>
          {/each}
        </div>
      {/if}
      {#if m.text}
        <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
        <div class="md" class:streaming onclick={onBodyClick}>{@html html}</div>
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
          {#if check}
            {#if check.ok}
              <span class="tag grounded" data-testid="grounding-ok" title="Every number, version, date and ID in this answer was found in the verified data">
                <Check size={11} /> {check.checked} figures match the verified data</span>
            {:else}
              <span class="tag ungrounded" data-testid="grounding-bad" title="Not found in the verified data — treat these with caution">
                <CircleAlert size={11} /> not in the verified data: {check.unknown.join(', ')}</span>
            {/if}
          {/if}
          {#if speaking}<span class="tag talk" data-testid="speaking-tag"><AudioLines size={11} /> speaking</span>{/if}
          <span class="faint">{m.model ?? ''}{#if m.ttft_ms != null}{' · '}first token {(m.ttft_ms / 1000).toFixed(2)} s{/if}</span>
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
  .an-card { display: flex; align-items: center; gap: 9px; padding: 8px 10px; margin-bottom: 8px; border-radius: var(--radius-sm);
    background: var(--plane-bg); box-shadow: var(--ring), var(--rise-1); color: var(--text-2); font-size: 12px; }
  .an-card > :global(svg) { color: var(--accent); flex: 0 0 auto; }
  .an-text { flex: 1; min-width: 0; }
  .an-t { display: inline-flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  .an-t.warn, .an-t .warn { color: var(--warn); }
  .tag.grounded { color: var(--ok); }
  .tag.ungrounded { color: var(--warn); }
  .tools { display: flex; flex-wrap: wrap; gap: 4px 6px; margin-bottom: 6px; }
  .tag.tool { color: var(--text-2); animation: tool-in .35s ease-out both; }
  .tag.tool b { color: var(--text); font-weight: 600; }
  .tag.tool.recheck { color: var(--ok); }
  @keyframes tool-in { from { opacity: 0; transform: translateY(3px); } }
  .md :global(button.fid) {
    display: inline; font: inherit; font-weight: 650; color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent);
    border: 0; border-radius: 5px; padding: 0 4px; margin: 0 1px; cursor: pointer; line-height: inherit;
  }
  .md :global(button.fid:hover) { background: color-mix(in srgb, var(--accent) 24%, transparent); text-decoration: underline; }
  .md :global(button.fid:focus-visible) { outline: 2px solid var(--accent); outline-offset: 1px; }
  @media (prefers-reduced-motion: reduce) { .tag.tool { animation: none; } }
</style>
