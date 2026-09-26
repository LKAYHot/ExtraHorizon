<script>
  import { untrack } from 'svelte'
  import { fmtNum } from '$lib/coord.js'

  // A number that counts up to its value (the analysis being built); instant with reduced motion.
  let { value = 0, duration = 900 } = $props()
  let shown = $state(0)
  const reduced = typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

  $effect(() => {
    const to = Number(value) || 0
    if (reduced) {
      shown = to
      return
    }
    const from = untrack(() => shown) // not a dependency: the tween writes it
    const t0 = performance.now()
    let raf = 0
    const step = (now) => {
      const k = Math.min(1, (now - t0) / duration)
      shown = Math.round(from + (to - from) * (1 - Math.pow(1 - k, 3)))
      if (k < 1) raf = requestAnimationFrame(step)
    }
    raf = requestAnimationFrame(step)
    return () => cancelAnimationFrame(raf)
  })
</script>

{fmtNum(shown)}
