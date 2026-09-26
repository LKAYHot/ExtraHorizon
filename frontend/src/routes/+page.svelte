<script>
  import { onMount } from 'svelte'
  import { app } from '$lib/app.svelte.js'
  import Sidebar from '$lib/components/Sidebar.svelte'
  import ChatPanel from '$lib/components/ChatPanel.svelte'
  import EmotionPanel from '$lib/components/EmotionPanel.svelte'
  import Toasts from '$lib/components/Toasts.svelte'

  onMount(() => {
    const onVis = () => {
      if (document.hidden) document.documentElement.dataset.hidden = '1'
      else delete document.documentElement.dataset.hidden
    }
    // Esc stops her (voice and the answer in flight), like speaking over her does
    const onKey = (e) => {
      if (e.key !== 'Escape' || e.defaultPrevented) return
      if (app.talkState === 'speaking' || app.talkState === 'thinking' || app.busy) app.stopAnswer()
    }
    document.addEventListener('visibilitychange', onVis)
    document.addEventListener('keydown', onKey)
    const stopSpot = spotlight()
    app.start()
    return () => {
      document.removeEventListener('visibilitychange', onVis)
      document.removeEventListener('keydown', onKey)
      stopSpot()
      app.shutdown()
    }
  })

  // cursor "spotlight" on .spot cards (one delegated listener, painted once per frame)
  function spotlight() {
    let el = null
    let x = 0
    let y = 0
    let raf = 0
    const paint = () => {
      raf = 0
      if (!el?.isConnected) return
      const r = el.getBoundingClientRect()
      el.style.setProperty('--mx', `${Math.round(x - r.left)}px`)
      el.style.setProperty('--my', `${Math.round(y - r.top)}px`)
    }
    const onMove = (e) => {
      if (e.pointerType === 'touch') return
      const t = e.target instanceof Element ? e.target.closest('.spot') : null
      if (!t) return
      el = t
      x = e.clientX
      y = e.clientY
      if (!raf) raf = requestAnimationFrame(paint)
    }
    document.addEventListener('pointermove', onMove, { passive: true })
    return () => {
      document.removeEventListener('pointermove', onMove)
      if (raf) cancelAnimationFrame(raf)
    }
  }
</script>

<div class="shell">
  <Sidebar />
  <ChatPanel />
  <EmotionPanel />
</div>
<Toasts />

<style>
  .shell {
    position: relative; z-index: 1;
    height: 100dvh;
    display: grid;
    grid-template-columns: var(--side-w) minmax(0, 1fr) var(--vision-w);
    min-width: 0;
  }
  @media (max-width: 1199px) {
    .shell { grid-template-columns: minmax(0, 1fr) var(--vision-w); grid-template-rows: auto minmax(0, 1fr); }
    .shell > :global(.sidebar) { grid-column: 1 / -1; }
  }
  @media (max-width: 859px) {
    :global(body) { overflow: auto; }
    .shell { height: auto; min-height: 100dvh; display: flex; flex-direction: column; }
  }
</style>
