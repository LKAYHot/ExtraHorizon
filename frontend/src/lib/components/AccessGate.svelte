<script>
  import { app } from '$lib/app.svelte.js'
  import { Cloud, Eye, EyeOff, KeyRound, LoaderCircle, Lock } from '$lib/icons.js'
  import Logo from './Logo.svelte'

  let key = $state('')
  let show = $state(false)
  let busy = $state(false)
  let error = $state('')
  let input = $state(null)

  const state = $derived(app.accessState)
  const days = 14

  $effect(() => {
    if (state === 'needed') input?.focus()
  })

  async function submit(e) {
    e.preventDefault()
    if (!key.trim() || busy) return
    busy = true
    error = ''
    try {
      await app.unlock(key.trim())
      key = ''
    } catch (err) {
      if (err.code === 'wrong_key') error = 'That key is not right.'
      else if (err.code === 'too_many_attempts') {
        const min = Math.max(1, Math.ceil((err.retryAfter ?? 600) / 60))
        error = `Too many wrong keys — try again in ${min} min.`
      } else if (err.code === 'remote_disabled') app.accessState = 'disabled'
      else error = 'The server did not answer — check the connection and try again.'
      input?.select()
    } finally {
      busy = false
    }
  }
</script>

<main class="gate" data-testid="access-gate">
  <section class="card raised panel">
    <div class="brand">
      <Logo size={40} />
      <div class="name">
        <span class="chrome-text sheen">ExtraHorizon</span>
        <small>Emotion-aware voice tutor</small>
      </div>
    </div>

    {#if state === 'checking' || state === 'offline'}
      <div class="wait" data-testid="access-wait">
        <LoaderCircle size={18} class="spin" />
        <span>{state === 'offline' ? 'The server is not reachable yet (it may be starting, or the tunnel is down) — retrying…' : 'Connecting…'}</span>
      </div>
    {:else if state === 'disabled'}
      <h1><Lock size={18} /> Remote access is off</h1>
      <p class="lead">This server only accepts its own computer: no access key is set on it
        (<code>EH_ACCESS_KEY</code>). Ask the presenter to start it with <code>scripts/demo-host.ps1</code>.</p>
    {:else}
      <h1><KeyRound size={18} /> Private demo</h1>
      <p class="lead">This tutor runs on the presenter's computer. Enter the access key to continue.</p>
      <form onsubmit={submit} novalidate>
        <label class="field">
          <span class="sr">Access key</span>
          <span class="box" class:bad={!!error}>
            <input bind:this={input} bind:value={key} type={show ? 'text' : 'password'} name="access-key"
                   autocomplete="current-password" spellcheck="false" placeholder="Access key"
                   aria-invalid={!!error} aria-describedby="access-error" data-testid="access-key" />
            <button type="button" class="eye" onclick={() => (show = !show)} aria-label={show ? 'Hide the key' : 'Show the key'}
                    aria-pressed={show}>
              {#if show}<EyeOff size={15} />{:else}<Eye size={15} />{/if}
            </button>
          </span>
        </label>
        <p id="access-error" class="error" role="alert" data-testid="access-error">{error}</p>
        <button class="btn primary go" type="submit" disabled={busy || !key.trim()} data-testid="access-submit">
          {#if busy}<LoaderCircle size={15} class="spin" />{/if} Continue
        </button>
      </form>
      <ul class="fine">
        <li>The key is remembered in a secure cookie on this browser for {days} days.</li>
        <li>Camera and microphone stay off until you turn them on.</li>
      </ul>
    {/if}

    {#if app.access?.transport === 'cloudflare'}
      <div class="via"><Cloud size={13} /> HTTPS · Cloudflare Tunnel to the presenter's computer</div>
    {/if}
  </section>
</main>

<style>
  .gate { position: relative; z-index: 1; min-height: 100dvh; display: grid; place-items: center; padding: 24px 16px; }
  .panel { width: min(420px, 100%); padding: 26px 26px 20px; border-radius: var(--radius-lg); display: flex; flex-direction: column; gap: 14px; }
  .brand { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
  .name { display: flex; flex-direction: column; line-height: 1.15; }
  .name span { font: 700 22px/1.1 var(--font-display); letter-spacing: -.02em; }
  .name small { color: var(--muted); font-size: 12px; }
  h1 { margin: 6px 0 0; display: flex; align-items: center; gap: 8px; font: 650 18px/1.2 var(--font-display); color: var(--text); }
  h1 :global(svg) { color: var(--accent); }
  .lead { margin: 0; color: var(--text-2); font-size: 13.5px; line-height: 1.5; }
  .lead code { font-family: var(--mono); font-size: 12px; color: var(--muted); }
  form { display: flex; flex-direction: column; gap: 8px; margin-top: 4px; }
  .field { display: block; }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
  .box {
    display: flex; align-items: center; height: 42px; padding: 0 6px 0 13px; gap: 6px;
    background: var(--sheen-well), var(--well); border: 1px solid var(--edge); border-radius: var(--radius-sm); box-shadow: var(--sink);
    transition: border-color var(--t2) var(--ease), box-shadow var(--t2) var(--ease);
  }
  .box:focus-within { border-color: color-mix(in srgb, var(--accent) 55%, transparent); box-shadow: var(--sink), 0 0 0 3px color-mix(in srgb, var(--accent) 16%, transparent); }
  .box.bad { border-color: color-mix(in srgb, var(--error) 60%, transparent); }
  .box input { flex: 1 1 auto; min-width: 0; height: 100%; border: 0; outline: none; background: transparent; color: var(--text); font: inherit; font-size: 14px; letter-spacing: .02em; }
  .box input::placeholder { color: var(--faint); letter-spacing: 0; }
  .eye { display: inline-flex; align-items: center; justify-content: center; width: 30px; height: 30px; border: 0; border-radius: 8px; background: transparent; color: var(--muted); cursor: pointer; }
  .eye:hover { background: var(--hover); color: var(--text-2); }
  .eye:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
  .error { margin: 0; min-height: 18px; color: var(--error); font-size: 12.5px; }
  .go { height: 40px; justify-content: center; gap: 8px; font-size: 14px; }
  .fine { margin: 2px 0 0; padding-left: 16px; display: flex; flex-direction: column; gap: 4px; color: var(--faint); font-size: 12px; line-height: 1.45; }
  .fine li::marker { color: var(--accent); }
  .wait { display: flex; align-items: center; gap: 10px; color: var(--text-2); font-size: 13.5px; line-height: 1.5; padding: 8px 0; }
  .via { display: flex; align-items: center; gap: 7px; padding-top: 12px; border-top: 1px solid var(--line); color: var(--muted); font-size: 11.5px; }
</style>
