<script>
  import { onMount, tick, untrack } from 'svelte'
  import { ChevronLeft, ChevronRight, Clock, Check } from '$lib/icons.js'
  import { WEEKDAYS, WEEKDAY_NAMES, MONTHS, HOURS, MINUTES, monthGrid, sameDay, isoDay, dayAllowed, to12, combine,
    startOfDay, addDays, addMonths, shiftMonth, deadlineProblem, suggestDeadline, stepMinutes, formatDeadline,
    fromNow } from '$lib/datetime.js'

  /**
   * A date-and-time picker in the app's own style (the browser's native one ignores the design and the UI's
   * language). Inline: a month calendar (today → ``maxDays`` ahead), hour and minute columns, AM/PM.
   * Keyboard: arrows move the day, Page Up/Down the month, Home/End the week, Enter picks, Esc cancels.
   */
  let { initial = null, maxDays = 30, onset, oncancel, setLabel = 'Set deadline' } = $props()

  const opened = new Date()
  // where the picker starts (the props' values when it opens — it does not follow them afterwards)
  const first = untrack(() => (initial && !deadlineProblem(initial, opened, maxDays) ? initial : suggestDeadline(opened)))
  const t12 = to12(first.getHours())
  let day = $state(startOfDay(first))
  let hour = $state(t12.hour)
  let minute = $state(stepMinutes(first.getMinutes()))
  let pm = $state(t12.pm)
  let view = $state(new Date(first.getFullYear(), first.getMonth(), 1))
  let focusDay = $state(startOfDay(first))
  let tickNow = $state(Date.now())
  let gridEl = $state(null)
  let hourCol = $state(null)
  let minCol = $state(null)

  const lastDay = $derived(addDays(startOfDay(opened), maxDays))
  const grid = $derived(monthGrid(view.getFullYear(), view.getMonth()))
  const weeks = $derived([0, 1, 2, 3, 4, 5].map((w) => grid.slice(w * 7, w * 7 + 7)))
  const chosen = $derived(combine(day, hour, minute, pm))
  const problem = $derived(deadlineProblem(chosen, new Date(tickNow), maxDays))
  const canPrev = $derived(addMonths(view, -1) >= new Date(opened.getFullYear(), opened.getMonth(), 1))
  const canNext = $derived(addMonths(view, 1) <= new Date(lastDay.getFullYear(), lastDay.getMonth(), 1))

  onMount(() => {
    const iv = setInterval(() => (tickNow = Date.now()), 30_000)
    tick().then(() => {
      gridEl?.querySelector(`[data-date="${isoDay(focusDay)}"]`)?.focus({ preventScroll: true })
      center(hourCol)
      center(minCol)
    })
    return () => clearInterval(iv)
  })

  /** Scroll a time column so its selected option sits in the middle (without scrolling the page). */
  function center(col) {
    const sel = col?.querySelector('[aria-selected="true"]')
    if (col && sel) col.scrollTop = sel.offsetTop - col.clientHeight / 2 + sel.clientHeight / 2
  }

  function pick(d) {
    if (!dayAllowed(d, opened, maxDays)) return
    day = startOfDay(d)
    focusDay = day
    if (d.getMonth() !== view.getMonth()) view = new Date(d.getFullYear(), d.getMonth(), 1)
  }

  function moveFocus(d) {
    if (!dayAllowed(d, opened, maxDays)) return
    focusDay = startOfDay(d)
    if (d.getMonth() !== view.getMonth() || d.getFullYear() !== view.getFullYear()) view = new Date(d.getFullYear(), d.getMonth(), 1)
    tick().then(() => gridEl?.querySelector(`[data-date="${isoDay(focusDay)}"]`)?.focus())
  }

  function onGridKey(e) {
    const step = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7 }[e.key]
    let next = null
    if (step) next = addDays(focusDay, step)
    else if (e.key === 'PageUp') next = shiftMonth(focusDay, -1)
    else if (e.key === 'PageDown') next = shiftMonth(focusDay, 1)
    else if (e.key === 'Home') next = addDays(focusDay, -focusDay.getDay())
    else if (e.key === 'End') next = addDays(focusDay, 6 - focusDay.getDay())
    if (!next) return
    e.preventDefault()
    moveFocus(next)
  }

  function month(n) {
    view = addMonths(view, n)
    const inView = grid.find((c) => c.inMonth && dayAllowed(c.date, opened, maxDays))
    if (inView && (focusDay.getMonth() !== view.getMonth())) focusDay = startOfDay(inView.date)
  }

  /** Arrow keys inside a time column (one tab stop per column). */
  function onListKey(e, values, current, set, col) {
    const i = values.indexOf(current)
    const j = e.key === 'ArrowDown' ? i + 1 : e.key === 'ArrowUp' ? i - 1 : e.key === 'Home' ? 0 : e.key === 'End' ? values.length - 1 : null
    if (j == null) return
    e.preventDefault()
    const v = values[(j + values.length) % values.length]
    set(v)
    tick().then(() => {
      const el = col?.querySelector('[aria-selected="true"]')
      el?.focus({ preventScroll: true })
      center(col)
    })
  }

  function onKey(e) {
    if (e.key === 'Escape') {
      e.preventDefault()
      e.stopPropagation()
      oncancel?.()
    }
  }

  function submit() {
    if (!deadlineProblem(chosen, new Date(), maxDays)) onset?.(chosen)
  }
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="dtp" role="group" aria-label="Pick a date and a time" onkeydown={onKey} data-testid="dtp">
  <div class="cal">
    <div class="head">
      <button type="button" class="nav" onclick={() => month(-1)} disabled={!canPrev} aria-label="Previous month" data-testid="dtp-prev"><ChevronLeft size={15} /></button>
      <div class="title" aria-live="polite">{MONTHS[view.getMonth()]} <span class="yr num">{view.getFullYear()}</span></div>
      <button type="button" class="nav" onclick={() => month(1)} disabled={!canNext} aria-label="Next month" data-testid="dtp-next"><ChevronRight size={15} /></button>
    </div>
    <div class="grid" role="grid" aria-label="{MONTHS[view.getMonth()]} {view.getFullYear()}" bind:this={gridEl} onkeydown={onGridKey} tabindex="-1">
      <div class="row wd" role="row">
        {#each WEEKDAYS as w, i (w)}<span role="columnheader" class="wdn" title={WEEKDAY_NAMES[i]}>{w}</span>{/each}
      </div>
      {#each weeks as week, wi (wi)}
        <div class="row" role="row">
          {#each week as c (isoDay(c.date))}
            {@const ok = dayAllowed(c.date, opened, maxDays)}
            {@const sel = sameDay(c.date, day)}
            <button type="button" role="gridcell" class="day" class:out={!c.inMonth} class:today={sameDay(c.date, opened)} class:sel
                    aria-selected={sel} aria-disabled={!ok} disabled={!ok} tabindex={sameDay(c.date, focusDay) ? 0 : -1}
                    aria-label={c.date.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}
                    onclick={() => pick(c.date)} data-testid="dtp-day" data-date={isoDay(c.date)}>{c.date.getDate()}</button>
          {/each}
        </div>
      {/each}
    </div>
  </div>

  <div class="time">
    <div class="tl"><Clock size={12} /> Time</div>
    <div class="cols">
      <div class="col" role="listbox" aria-label="Hour" tabindex="-1" bind:this={hourCol} data-testid="dtp-hours"
           onkeydown={(e) => onListKey(e, HOURS, hour, (v) => (hour = v), hourCol)}>
        {#each HOURS as h (h)}
          <button type="button" role="option" aria-selected={h === hour} class:sel={h === hour} tabindex={h === hour ? 0 : -1}
                  onclick={() => (hour = h)} data-testid="dtp-hour-{h}">{h}</button>
        {/each}
      </div>
      <div class="col" role="listbox" aria-label="Minutes" tabindex="-1" bind:this={minCol} data-testid="dtp-minutes"
           onkeydown={(e) => onListKey(e, MINUTES, minute, (v) => (minute = v), minCol)}>
        {#each MINUTES as m (m)}
          <button type="button" role="option" aria-selected={m === minute} class:sel={m === minute} tabindex={m === minute ? 0 : -1}
                  onclick={() => (minute = m)} data-testid="dtp-minute-{m}">{String(m).padStart(2, '0')}</button>
        {/each}
      </div>
      <div class="ampm" role="radiogroup" aria-label="AM or PM">
        <button type="button" role="radio" aria-checked={!pm} class:sel={!pm} onclick={() => (pm = false)} data-testid="dtp-am">AM</button>
        <button type="button" role="radio" aria-checked={pm} class:sel={pm} onclick={() => (pm = true)} data-testid="dtp-pm">PM</button>
      </div>
    </div>
  </div>

  <div class="foot">
    {#if problem}
      <span class="msg warn" role="status">{problem}</span>
    {:else}
      <span class="msg" role="status"><b data-testid="dtp-chosen">{formatDeadline(chosen)}</b> <span class="rel">{fromNow(chosen, new Date(tickNow))}</span></span>
    {/if}
    <span class="grow"></span>
    <button type="button" class="btn sm ghost" onclick={() => oncancel?.()}>Cancel</button>
    <button type="button" class="btn sm primary" onclick={submit} disabled={!!problem} data-testid="dtp-set"><Check size={13} /> {setLabel}</button>
  </div>
</div>

<style>
  .dtp { display: grid; grid-template-columns: minmax(250px, 1fr) auto; gap: 12px 16px; padding: 12px; border-radius: 12px;
    background: var(--sheen), var(--plane-hi); box-shadow: var(--ring-2), var(--rise-2); animation: pop-in .22s var(--ease) both; }
  @keyframes pop-in { from { opacity: 0; transform: translateY(-4px) scale(.985); } }

  .head { display: flex; align-items: center; gap: 6px; margin-bottom: 6px; }
  .title { flex: 1; text-align: center; font: 650 13.5px/1 var(--font-display); color: var(--text); letter-spacing: -.01em; }
  .title .yr { color: var(--muted); font-weight: 600; }
  .nav { width: 28px; height: 28px; display: inline-grid; place-items: center; border-radius: 8px; border: 1px solid transparent;
    background: transparent; color: var(--muted); transition: background var(--t2) var(--ease), color var(--t2) var(--ease); }
  .nav:hover:not(:disabled) { background: var(--sheen), var(--raise); border-color: var(--edge); color: var(--text); }
  .nav:disabled { opacity: .3; }

  .grid { display: flex; flex-direction: column; gap: 2px; outline: none; }
  .row { display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; }
  .wdn { display: grid; place-items: center; height: 22px; font-size: 10.5px; font-weight: 650; letter-spacing: .06em;
    text-transform: uppercase; color: var(--faint); }
  .day { height: 32px; border-radius: 8px; border: 1px solid transparent; background: transparent; color: var(--text-2);
    font: 550 12.5px/1 var(--font); font-variant-numeric: tabular-nums; position: relative;
    transition: background var(--t1) var(--ease), color var(--t1) var(--ease), box-shadow var(--t1) var(--ease); }
  .day:hover:not(:disabled):not(.sel) { background: var(--hover); color: var(--text); border-color: var(--edge); }
  .day.out { color: var(--faint); }
  .day.today:not(.sel) { box-shadow: inset 0 0 0 1px color-mix(in srgb, var(--accent) 55%, transparent); color: var(--text); }
  .day.today::after { content: ''; position: absolute; left: 50%; bottom: 4px; width: 4px; height: 4px; margin-left: -2px;
    border-radius: 50%; background: var(--accent); }
  .day.sel { background: var(--primary-bg); color: var(--primary-ink); font-weight: 700; box-shadow: var(--primary-rise); }
  .day.sel.today::after { background: var(--primary-ink); }
  .day:disabled { opacity: .28; cursor: default; }
  .day:focus-visible { outline: 2px solid color-mix(in srgb, var(--accent) 85%, transparent); outline-offset: 1px; }

  .time { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
  .tl { display: flex; align-items: center; gap: 5px; height: 28px; font-size: 11.5px; font-weight: 650; color: var(--muted); }
  .tl :global(svg) { color: var(--accent); }
  .cols { display: flex; gap: 6px; align-items: flex-start; }
  .col { width: 50px; height: 222px; overflow-y: auto; scrollbar-width: none; display: flex; flex-direction: column; gap: 2px;
    padding: 4px; border-radius: 10px; background: var(--well-bg); box-shadow: var(--sink); scroll-behavior: smooth;
    -webkit-mask-image: linear-gradient(180deg, transparent 0, #000 16px, #000 calc(100% - 16px), transparent 100%);
    mask-image: linear-gradient(180deg, transparent 0, #000 16px, #000 calc(100% - 16px), transparent 100%); }
  .col::-webkit-scrollbar { display: none; }
  .col button, .ampm button { flex: 0 0 auto; height: 28px; border-radius: 7px; border: 0; background: transparent; color: var(--text-2);
    font: 600 12.5px/1 var(--font); font-variant-numeric: tabular-nums; transition: background var(--t1) var(--ease), color var(--t1) var(--ease); }
  .col button:hover:not(.sel), .ampm button:hover:not(.sel) { background: var(--hover); color: var(--text); }
  .col button.sel, .ampm button.sel { background: var(--primary-bg); color: var(--primary-ink); box-shadow: var(--primary-rise); }
  .ampm { display: flex; flex-direction: column; gap: 3px; padding: 4px; border-radius: 10px; background: var(--well-bg); box-shadow: var(--sink); }
  .ampm button { width: 44px; }

  .foot { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding-top: 10px;
    border-top: 1px solid var(--line); }
  .msg { font-size: 12.5px; color: var(--text-2); }
  .msg b { color: var(--text); font-weight: 650; }
  .msg .rel { color: var(--muted); margin-left: 4px; }
  .msg.warn { color: var(--warn); }
  .grow { flex: 1; }

  @media (max-width: 560px) {
    .dtp { grid-template-columns: 1fr; }
    .cols { justify-content: flex-start; }
    .col { height: 150px; }
  }
  @media (prefers-reduced-motion: reduce) { .dtp { animation: none; } .col { scroll-behavior: auto; } }
</style>
