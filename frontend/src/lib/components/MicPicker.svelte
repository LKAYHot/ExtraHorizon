<script>
  import { app } from '$lib/app.svelte.js'
  import { Mic } from '$lib/icons.js'

  let { compact = false } = $props()
  const v = app.voice
  const current = $derived(v.devices.find((d) => d.deviceId === v.deviceId))
</script>

<label class="picker" class:compact title={v.deviceLabel ? `In use: ${v.deviceLabel}` : 'Microphone'}>
  {#if compact}<Mic size={12} />{:else}<span>Microphone</span>{/if}
  <select class="select" value={current ? v.deviceId : ''} onfocus={() => v.refreshDevices()}
          onchange={(e) => v.setDevice(e.currentTarget.value)} aria-label="Microphone" data-testid="mic-device">
    <option value="">System default</option>
    {#each v.devices as d (d.deviceId)}
      <option value={d.deviceId}>{d.label}</option>
    {/each}
  </select>
</label>

<style>
  .picker { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--muted); min-width: 0; }
  .picker.compact { flex-direction: row; align-items: center; gap: 6px; }
  .picker.compact .select { height: 26px; padding: 0 8px; font-size: 11.5px; max-width: 220px; }
  .select { min-width: 0; text-overflow: ellipsis; }
</style>
