<script>
  import { app } from '$lib/app.svelte.js'
  import { reasonText } from '$lib/format.js'
  import { MessageSquareQuote } from '$lib/icons.js'

  const ctx = $derived(app.context)
</script>

<section class="card prompt" data-testid="prompt-card">
  <div class="top">
    <div class="eyebrow"><MessageSquareQuote size={13} /> What {app.persona} is told</div>
    {#if ctx?.available && ctx.source === 'simulation'}<span class="chip sim">SIMULATED</span>{/if}
  </div>
  {#if ctx?.available}
    <p class="lead">With your next question, her prompt gets this note:</p>
    <blockquote data-testid="prompt-note">{ctx.note}</blockquote>
    <p class="fine">Words only — no numbers, no images. She treats it as what she sees on the call: it quietly steers her tone and pacing, she rarely mentions it, and she believes you if you say she read you wrong.</p>
  {:else}
    <p class="lead">Nothing about your face right now{ctx?.reason ? ` (${reasonText(ctx.reason).toLowerCase()})` : ''}.</p>
    <p class="fine">When one face is clearly in view (after a ~3 s calibration to your relaxed face), a short description of how it looks is added to her prompt.</p>
  {/if}
</section>

<style>
  .prompt { padding: 12px 14px; display: flex; flex-direction: column; gap: 6px; }
  .top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
  .lead { margin: 2px 0 0; font-size: 12.5px; color: var(--text-2); display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
  blockquote {
    margin: 0; padding: 9px 11px; border-radius: var(--radius-sm); background: var(--well-bg); box-shadow: var(--sink);
    font-family: var(--mono); font-size: 11.5px; line-height: 1.55; color: #d9e1ff; overflow-wrap: anywhere;
  }
  .fine { margin: 0; font-size: 11px; color: var(--faint); line-height: 1.45; }
</style>
