<script>
  import { app } from '$lib/app.svelte.js'
  import { reasonText } from '$lib/format.js'
  import { COLOR, LABEL } from '$lib/emotions.js'
  import { Camera, CameraOff, LoaderCircle, ScanFace, Users, User, ShieldAlert, RefreshCw } from '$lib/icons.js'

  const v = app.vision
  let video = $state(null)

  $effect(() => {
    v.attachVideo(video)
    return () => v.attachVideo(null)
  })

  const STATUS = {
    off: ['Camera off', 'off'],
    initializing: ['Initializing…', 'warn'],
    active: ['Active', 'ok'],
    denied: ['Permission denied', 'error'],
    unavailable: ['Unavailable', 'error'],
    ended: ['Disconnected', 'error'],
  }
  const status = $derived(STATUS[v.camera] ?? ['Unknown', 'off'])
  const tick = $derived(v.camera === 'active' ? app.visionTick : null)
  const simDriving = $derived(app.sim.enabled)
  const e = $derived(app.emotion)
  const dom = $derived(!simDriving && e?.status === 'ok' ? e.dominant : null)
  const calibrating = $derived(!simDriving && e?.status === 'calibrating')

  // face boxes come in un-mirrored image coordinates; the preview is mirrored
  const boxes = $derived((tick?.boxes ?? []).map(([x, y, w, h]) => ({ x: 1 - x - w, y, w, h })))
  const boxTone = $derived(!tick ? '' : tick.quality === 'ok' ? 'ok' : 'bad')

  const presence = $derived.by(() => {
    if (v.camera !== 'active') return null
    if (v.backend.available === false) return { icon: ShieldAlert, text: 'Vision processing unavailable', tone: 'error' }
    if (!tick) return { icon: LoaderCircle, text: 'Waiting for the first analysed frame…', tone: 'warn', spin: true }
    if (tick.faces > 1) return { icon: Users, text: `${tick.faces} faces — ambiguous, not used`, tone: 'warn' }
    if (tick.faces === 0) return { icon: User, text: 'No face in view — expression unknown', tone: 'warn' }
    if (tick.quality !== 'ok') return { icon: ScanFace, text: `1 face · ${reasonText(tick.reason)} — expression unknown`, tone: 'warn' }
    if (calibrating)
      return { icon: ScanFace, text: `1 face · learning your relaxed face ${Math.round((v.calibration.progress ?? 0) * 100)}% — look at the screen, relax`, tone: 'accent' }
    return { icon: ScanFace, text: `1 face · tracking (calibrated to you)${tick.emotion_ms != null ? ` · ${Math.round(tick.emotion_ms)} ms` : ''}`, tone: 'ok' }
  })
</script>

<section class="card spot cam" data-testid="camera-card">
  <div class="top">
    <div class="eyebrow"><Camera size={13} /> Camera</div>
    <span class="status tone-{status[1]}" data-testid="camera-status" data-status={v.camera}>
      <span class="dot" class:pulse={v.camera === 'active'}></span>{status[0]}
    </span>
  </div>

  <div class="frame" class:live={v.camera === 'active'} class:gate={!v.consented && v.camera !== 'active'}>
    <!-- svelte-ignore a11y_media_has_caption -->
    <video bind:this={video} autoplay playsinline muted></video>
    {#if v.camera === 'active'}
      <svg class="overlay" viewBox="0 0 1 1" preserveAspectRatio="none" aria-hidden="true">
        {#each boxes as b, i (i)}
          <rect class="box {boxTone}" class:cal={calibrating} x={b.x} y={b.y} width={b.w} height={b.h} rx=".02" vector-effect="non-scaling-stroke"
                style:stroke={dom && boxTone === 'ok' && !calibrating ? COLOR[dom] : null} />
        {/each}
      </svg>
      {#if (dom || calibrating) && boxes.length === 1 && tick?.quality === 'ok'}
        {@const b = boxes[0]}
        {@const below = b.y < 0.12}
        <div class="face-label" class:below style:left="{Math.min(0.86, Math.max(0.14, b.x + b.w / 2)) * 100}%"
             style:top="{(below ? Math.min(0.92, b.y + b.h) : b.y) * 100}%" data-testid="face-label">
          {#if calibrating}<LoaderCircle size={11} class="spin" />Calibrating…{:else}<i style:background={COLOR[dom]}></i>{LABEL[dom]}{/if}
        </div>
      {/if}
      {#if simDriving}<div class="simtag">camera shown · expression from SIMULATION</div>{/if}
    {:else if !v.consented}
      <div class="consent" data-testid="camera-consent">
        <Camera size={22} />
        <p class="lead">Turn on the camera so {app.persona} can read the room.</p>
        <ul>
          <li>Frames go {app.local ? "over localhost to this computer's ExtraHorizon process" : `to the ExtraHorizon backend at ${location.host}`}, where Google's <strong>MediaPipe</strong> finds your face and an {app.local ? 'on-device ' : ''}<strong>expression model</strong> estimates it — frames are discarded, never stored, never sent to OpenAI.</li>
          <li>It first learns <em>your</em> relaxed face (~3 s — look at the screen), so your resting face reads as neutral.</li>
          <li>Only a short, words-only description (“looks mostly happy…”) is added to her prompt when you ask something.</li>
          <li>MediaPipe itself sends Google anonymous <strong>usage metrics</strong> (e.g. frame counts, latency, OS/Python version) while the camera is on — per Google, never images or video.</li>
        </ul>
        <button class="btn primary sm" onclick={() => v.enableCamera()} data-testid="camera-on"><Camera size={13} /> Turn on camera</button>
        <span class="skip">Chat and voice work without it.</span>
      </div>
    {:else}
      <div class="placeholder">
        {#if v.camera === 'initializing'}
          <LoaderCircle size={26} class="spin" />
          <p>Waiting for camera permission…</p>
        {:else}
          <CameraOff size={26} />
          <p>{v.cameraMessage || (v.camera === 'off' ? 'The camera is off. Chat and voice work without it.' : 'Camera unavailable.')}</p>
        {/if}
      </div>
    {/if}
  </div>

  {#if presence}
    {@const Icon = presence.icon}
    <div class="presence tone-{presence.tone}" data-testid="face-presence">
      <Icon size={14} class={presence.spin ? 'spin' : ''} /><span>{presence.text}</span>
    </div>
  {/if}

  <div class="actions">
    {#if v.camera === 'active' || v.camera === 'initializing'}
      <button class="btn sm" onclick={() => v.stopCamera()}><CameraOff size={13} /> Turn off</button>
      <button class="btn sm ghost" onclick={() => v.recalibrate()} disabled={v.camera !== 'active'} data-testid="recalibrate"
              title="Learn your relaxed face again (~3 s): look at the screen with a relaxed face"><RefreshCw size={13} /> Recalibrate</button>
    {:else if v.consented}
      <button class="btn sm" onclick={() => v.startCamera()} data-testid="camera-on"><Camera size={13} /> {v.camera === 'off' ? 'Turn on camera' : 'Retry camera'}</button>
    {/if}
    <span class="grow"></span>
    {#if v.camera === 'active' && v.fps}
      <span class="perf faint num" title="Frames analysed per second · round trip to the local backend">{v.fps} fps · {v.latencyMs ?? '—'} ms</span>
    {/if}
  </div>
</section>

<style>
  .cam { padding: 12px; display: flex; flex-direction: column; gap: 10px; }
  .top { display: flex; align-items: center; justify-content: space-between; }
  .status { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: var(--text-2); }
  .frame {
    position: relative; aspect-ratio: 4 / 3; border-radius: 12px; overflow: hidden;
    background: radial-gradient(ellipse at 50% 35%, #111b36, #070c19); box-shadow: var(--sink);
  }
  .frame.live { box-shadow: 0 0 0 1px rgb(122 152 255 / .25), var(--rise-1); }
  video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; transform: scaleX(-1); }
  .frame:not(.live) video { opacity: 0; }
  .overlay { position: absolute; inset: 0; width: 100%; height: 100%; pointer-events: none; }
  .box { fill: none; stroke-width: 2px; stroke: #7a98ff; transition: stroke var(--t3) var(--ease); }
  .box.ok { stroke: #8fe0bf; }
  .box.bad { stroke: var(--warn); stroke-dasharray: 6 4; }
  .box.cal { stroke: #a58bff; stroke-dasharray: 6 4; }
  .face-label {
    position: absolute; transform: translate(-50%, calc(-100% - 6px)); pointer-events: none;
    display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px 3px 7px; border-radius: 999px;
    font-size: 12px; font-weight: 650; color: #f4f6ff; white-space: nowrap;
    background: rgb(8 12 26 / .82); box-shadow: 0 0 0 1px rgb(170 190 255 / .2), 0 6px 16px -6px rgb(0 0 10 / .8);
    transition: left .2s linear, top .2s linear;
  }
  .face-label.below { transform: translate(-50%, 6px); }
  .face-label i { width: 9px; height: 9px; border-radius: 3px; }
  .simtag {
    position: absolute; left: 8px; bottom: 8px; padding: 3px 8px; border-radius: 6px; font-size: 10.5px; font-weight: 700; letter-spacing: .04em;
    color: #ffe2b8; background: rgb(40 24 6 / .78); box-shadow: 0 0 0 1px rgb(232 184 95 / .5);
  }
  /* before consent the frame grows with the disclosure instead of clipping it to 4:3 */
  .frame.gate { aspect-ratio: auto; }
  .consent {
    position: relative; display: flex; flex-direction: column; align-items: center; justify-content: center;
    gap: 8px; padding: 16px 14px; text-align: center; color: var(--muted);
  }
  .consent > :global(svg) { color: var(--accent); flex: 0 0 auto; }
  .consent .lead { margin: 0; font-size: 12.5px; color: var(--text-2); font-weight: 600; }
  .consent ul { margin: 0; padding-left: 16px; text-align: left; font-size: 11px; line-height: 1.45; display: flex; flex-direction: column; gap: 3px; }
  .consent strong { color: var(--text-2); font-weight: 600; }
  .consent .skip { font-size: 11px; color: var(--faint); }
  .placeholder { position: absolute; inset: 0; display: grid; place-content: center; justify-items: center; gap: 8px; padding: 18px; text-align: center; color: var(--muted); }
  .placeholder p { margin: 0; font-size: 12.5px; max-width: 260px; line-height: 1.45; }
  .presence { display: flex; align-items: flex-start; gap: 8px; font-size: 12.5px; color: var(--text-2); line-height: 1.4; }
  .presence :global(svg) { flex: 0 0 auto; margin-top: 1px; color: var(--tone); }
  .actions { display: flex; align-items: center; gap: 6px; }
  .perf { font-size: 11px; }
</style>
