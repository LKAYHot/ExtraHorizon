<script>
  import { tick } from 'svelte'
  import { Check, ChevronDown } from '$lib/icons.js'

  /**
   * A styled select-only combobox (WAI-ARIA APG pattern): a button that opens a listbox.
   * Keyboard: ↓/↑/Enter/Space open; ↓ ↑ Home End PageUp PageDown move; Enter/Space choose;
   * Esc closes; Tab chooses and moves on; typing jumps to a matching option.
   * The list is moved to <body> with fixed positioning, so a scrolling sidebar never clips it,
   * and it opens upwards when there is no room below (e.g. next to the composer).
   */
  let {
    options = [], // [{ value, label, hint? }]
    value = '',
    onchange = () => {},
    label = '', // accessible name
    placeholder = 'Select…',
    compact = false,
    disabled = false,
    onopen = () => {}, // e.g. refresh the microphone list
    testid = undefined,
  } = $props()

  const uid = `sel-${Math.random().toString(36).slice(2, 9)}`
  let open = $state(false)
  let active = $state(-1)
  let button = $state(null)
  let list = $state(null)
  let pos = $state({ left: 0, top: 0, bottom: null, minWidth: 0, maxHeight: 280, up: false })
  let typed = ''
  let typedAt = 0

  const selectedIndex = $derived(options.findIndex((o) => o.value === value))
  const selected = $derived(selectedIndex >= 0 ? options[selectedIndex] : null)

  function portal(node) {
    document.body.appendChild(node)
    return { destroy: () => node.remove() }
  }

  function place() {
    if (!button) return
    const r = button.getBoundingClientRect()
    const vw = window.innerWidth
    const vh = window.innerHeight
    const below = vh - r.bottom - 10
    const above = r.top - 10
    const wanted = Math.min(300, options.length * 34 + 12)
    const up = below < wanted && above > below
    const maxHeight = Math.max(96, Math.min(300, up ? above : below))
    const minWidth = Math.min(vw - 16, r.width)
    // the list is as wide as its longest option (at least the button); keep it on screen
    const width = Math.max(minWidth, list?.offsetWidth ?? 0)
    const left = Math.max(8, Math.min(r.left, vw - width - 8))
    pos = up
      ? { left, top: null, bottom: vh - r.top + 6, minWidth, maxHeight, up }
      : { left, top: r.bottom + 6, bottom: null, minWidth, maxHeight, up }
  }

  async function show(at = selectedIndex) {
    if (disabled || open) return
    onopen()
    place()
    active = at >= 0 ? at : 0
    open = true
    await tick()
    place() // now that the list has its real width
    scrollActive()
  }

  function hide(refocus = true) {
    open = false
    if (refocus) button?.focus()
  }

  function choose(i, refocus = true) {
    const o = options[i]
    hide(refocus)
    if (o && o.value !== value) onchange(o.value)
  }

  function scrollActive() {
    list?.querySelector(`#${uid}-o${active}`)?.scrollIntoView({ block: 'nearest' })
  }

  function move(to) {
    if (!options.length) return
    active = Math.max(0, Math.min(options.length - 1, to))
    scrollActive()
  }

  function typeahead(ch) {
    const now = performance.now()
    typed = now - typedAt > 700 ? ch.toLowerCase() : typed + ch.toLowerCase()
    typedAt = now
    const n = options.length
    const from = open ? active : selectedIndex
    // a second letter keeps looking from the current match; a repeated first letter cycles
    const offset = typed.length > 1 ? 0 : 1
    for (let s = 0; s < n; s++) {
      const i = (Math.max(0, from) + offset + s) % n
      if (options[i].label.toLowerCase().startsWith(typed)) {
        if (open) move(i)
        else show(i)
        return
      }
    }
  }

  function onkeydown(e) {
    if (disabled) return
    const k = e.key
    if (!open) {
      if (k === 'ArrowDown' || k === 'ArrowUp' || k === 'Enter' || k === ' ') {
        e.preventDefault()
        show()
      } else if (k.length === 1 && k !== ' ' && !e.ctrlKey && !e.metaKey && !e.altKey) {
        typeahead(k)
      }
      return
    }
    switch (k) {
      case 'ArrowDown': e.preventDefault(); move(active + 1); break
      case 'ArrowUp': e.preventDefault(); move(active - 1); break
      case 'Home': e.preventDefault(); move(0); break
      case 'End': e.preventDefault(); move(options.length - 1); break
      case 'PageDown': e.preventDefault(); move(active + 8); break
      case 'PageUp': e.preventDefault(); move(active - 8); break
      case 'Enter':
      case ' ': e.preventDefault(); choose(active); break
      case 'Escape': e.preventDefault(); hide(); break
      case 'Tab': choose(active, false); break
      default:
        if (k.length === 1 && !e.ctrlKey && !e.metaKey && !e.altKey) {
          e.preventDefault()
          typeahead(k)
        }
    }
  }

  $effect(() => {
    if (!open) return
    const outside = (e) => {
      if (!button?.contains(e.target) && !list?.contains(e.target)) hide(false)
    }
    const replace = () => place()
    window.addEventListener('pointerdown', outside, true)
    window.addEventListener('resize', replace)
    window.addEventListener('scroll', replace, true)
    return () => {
      window.removeEventListener('pointerdown', outside, true)
      window.removeEventListener('resize', replace)
      window.removeEventListener('scroll', replace, true)
    }
  })
</script>

<div class="sel" class:compact>
  <button
    bind:this={button}
    type="button"
    class="trigger"
    class:open
    role="combobox"
    aria-haspopup="listbox"
    aria-expanded={open}
    aria-controls="{uid}-list"
    aria-activedescendant={open && active >= 0 ? `${uid}-o${active}` : undefined}
    aria-label={label || undefined}
    {disabled}
    data-testid={testid}
    data-value={value}
    onclick={() => (open ? hide() : show())}
    {onkeydown}
  >
    <span class="value" class:placeholder={!selected}>{selected ? selected.label : placeholder}</span>
    <span class="chev"><ChevronDown size={compact ? 12 : 14} /></span>
  </button>
</div>

{#if open}
  <!-- keyboard is handled by the combobox button (aria-activedescendant); the list only takes the mouse -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <ul
    use:portal
    bind:this={list}
    id="{uid}-list"
    class="list"
    class:up={pos.up}
    class:compact
    role="listbox"
    tabindex="-1"
    aria-label={label || undefined}
    style:left="{pos.left}px"
    style:top={pos.top == null ? null : `${pos.top}px`}
    style:bottom={pos.bottom == null ? null : `${pos.bottom}px`}
    style:min-width="{pos.minWidth}px"
    style:max-height="{pos.maxHeight}px"
    onpointerdown={(e) => e.preventDefault()}
  >
    {#each options as o, i (o.value)}
      <li
        id="{uid}-o{i}"
        class="opt"
        class:active={i === active}
        class:chosen={i === selectedIndex}
        role="option"
        aria-selected={i === selectedIndex}
        data-value={o.value}
        onpointermove={() => (active = i)}
        onclick={() => choose(i)}
      >
        {#if i === selectedIndex}<span class="tick"><Check size={14} /></span>{/if}
        <span class="label">{o.label}</span>
        {#if o.hint}<span class="hint">{o.hint}</span>{/if}
      </li>
    {:else}
      <li class="opt empty" role="option" aria-selected="false" aria-disabled="true">Nothing to choose</li>
    {/each}
  </ul>
{/if}

<style>
  .sel { display: flex; min-width: 0; }
  .trigger {
    display: flex; align-items: center; gap: 8px; width: 100%; min-width: 0; height: 34px; padding: 0 9px 0 11px;
    background: var(--sheen-well), var(--well); border: 1px solid var(--edge); border-radius: var(--radius-xs);
    box-shadow: var(--sink); color: var(--text); font: inherit; font-size: 13px; text-align: left; cursor: pointer;
    transition: border-color var(--t2) var(--ease), box-shadow var(--t2) var(--ease), background var(--t2) var(--ease);
  }
  .trigger:hover:not(:disabled) { border-color: var(--edge-2); }
  .trigger:focus-visible, .trigger.open {
    outline: none; border-color: color-mix(in srgb, var(--accent) 55%, transparent);
    box-shadow: var(--sink), 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent);
  }
  .trigger:disabled { opacity: .55; cursor: not-allowed; }
  .value { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .value.placeholder { color: var(--faint); }
  .chev { display: inline-flex; color: var(--muted); transition: transform var(--t2) var(--ease), color var(--t2) var(--ease); }
  .trigger:hover .chev, .trigger.open .chev { color: var(--text-2); }
  .trigger.open .chev { transform: rotate(180deg); }
  .compact .trigger { height: 26px; padding: 0 7px 0 9px; gap: 6px; font-size: 11.5px; border-radius: 7px; }

  .list {
    position: fixed; z-index: 1000; margin: 0; padding: 5px; list-style: none; overflow-y: auto; overscroll-behavior: contain;
    width: max-content; max-width: min(360px, calc(100vw - 16px)); box-sizing: border-box;
    background: var(--sheen), var(--raise); border: 1px solid var(--edge-2); border-radius: 12px;
    box-shadow: var(--rise-3), 0 0 0 1px rgb(0 0 10 / .45); color: var(--text-2); font-family: var(--font);
    transform-origin: top center; animation: pop var(--t2) var(--ease);
    scrollbar-width: thin; scrollbar-color: var(--line-3) transparent;
  }
  .list.up { transform-origin: bottom center; animation-name: pop-up; }
  .opt {
    position: relative; display: flex; align-items: center; gap: 8px; min-height: 32px; padding: 6px 10px 6px 30px;
    border-radius: 8px; font-size: 13px; line-height: 1.3; cursor: pointer; user-select: none;
    transition: background var(--t1) var(--ease), color var(--t1) var(--ease);
  }
  .list.compact .opt { min-height: 30px; font-size: 12.5px; }
  .opt .label { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .opt.active { background: var(--fill-3); color: var(--text); box-shadow: inset 0 0 0 1px var(--edge); }
  .opt.chosen { color: var(--text); font-weight: 600; }
  .opt .tick { position: absolute; left: 9px; top: 50%; transform: translateY(-50%); display: inline-flex; color: var(--accent); }
  .opt .hint { flex: 0 0 auto; color: var(--faint); font-size: 11px; font-weight: 500; }
  .opt.empty { color: var(--faint); cursor: default; padding-left: 12px; }

  @keyframes pop { from { opacity: 0; transform: translateY(-4px) scale(.98); } }
  @keyframes pop-up { from { opacity: 0; transform: translateY(4px) scale(.98); } }
  @media (prefers-reduced-motion: reduce) { .list, .list.up { animation: none; } }
</style>
