<script>
  import { app } from '$lib/app.svelte.js'
  import { TALK_LABEL } from '$lib/format.js'

  let { size = 40 } = $props()
  const st = $derived(app.talkState)
  const lvl = $derived(st === 'hearing' ? app.voice.level : 0)
</script>

<div class="orb {st}" style:--s="{size}px" style:--lvl={lvl} role="img" aria-label="{app.persona}: {TALK_LABEL[st]}" data-testid="talk-orb" data-state={st}>
  <span class="halo"></span>
  <span class="ring"></span>
  <span class="core">
    {#if st === 'speaking'}
      <span class="eq"><i></i><i></i><i></i><i></i></span>
    {:else if st === 'thinking'}
      <span class="dots"><i></i><i></i><i></i></span>
    {/if}
  </span>
</div>

<style>
  .orb { position: relative; width: var(--s); height: var(--s); flex: 0 0 auto; display: grid; place-items: center; }
  .halo, .ring, .core { position: absolute; border-radius: 50%; }
  .halo { inset: -6px; background: radial-gradient(circle, rgb(122 152 255 / .35), transparent 65%); opacity: 0; transition: opacity var(--t3) var(--ease); }
  .ring { inset: 0; box-shadow: inset 0 0 0 2px rgb(170 190 255 / .18); transition: transform 90ms linear, box-shadow var(--t3) var(--ease); }
  .core {
    inset: 5px; display: grid; place-items: center; overflow: hidden;
    background: radial-gradient(circle at 35% 30%, #c7d4ff, #7a98ff 45%, #6a4fd8 100%);
    box-shadow: inset 0 1px 0 rgb(255 255 255 / .45), 0 6px 16px -6px rgb(110 130 255 / .6);
    filter: saturate(.55) brightness(.7); transition: filter var(--t3) var(--ease);
  }
  .listening .core, .hearing .core, .thinking .core, .speaking .core { filter: none; }
  .listening .ring { box-shadow: inset 0 0 0 2px rgb(122 152 255 / .45); animation: breathe 2.6s var(--ease-io) infinite; }
  .hearing .ring { box-shadow: inset 0 0 0 2px rgb(143 224 191 / .85); transform: scale(calc(1 + var(--lvl) * .32)); }
  .hearing .halo { opacity: calc(.35 + var(--lvl) * .65); background: radial-gradient(circle, rgb(95 203 159 / .35), transparent 65%); }
  .thinking .ring { box-shadow: inset 0 0 0 2px rgb(165 139 255 / .6); animation: breathe 1.4s var(--ease-io) infinite; }
  .speaking .halo { opacity: 1; animation: glow 1.1s var(--ease-io) infinite alternate; }
  .speaking .ring { box-shadow: inset 0 0 0 2px rgb(170 190 255 / .75); }

  .eq { display: flex; align-items: center; gap: 2px; height: 45%; }
  .eq i { width: 3px; height: 100%; border-radius: 2px; background: #f4f6ff; transform-origin: 50% 50%; animation: eq .9s var(--ease-io) infinite; }
  .eq i:nth-child(2) { animation-delay: -.3s; }
  .eq i:nth-child(3) { animation-delay: -.6s; }
  .eq i:nth-child(4) { animation-delay: -.15s; }
  .dots { display: flex; gap: 3px; }
  .dots i { width: 4px; height: 4px; border-radius: 50%; background: #f4f6ff; animation: eh-typing 1.2s var(--ease-io) infinite; }
  .dots i:nth-child(2) { animation-delay: .15s; }
  .dots i:nth-child(3) { animation-delay: .3s; }

  @keyframes breathe { 0%, 100% { transform: scale(1); opacity: 1; } 50% { transform: scale(1.08); opacity: .7; } }
  @keyframes glow { from { transform: scale(.94); opacity: .55; } to { transform: scale(1.06); opacity: 1; } }
  @keyframes eq { 0%, 100% { transform: scaleY(.3); } 50% { transform: scaleY(1); } }
</style>
