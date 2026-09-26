<script>
  import { app } from '$lib/app.svelte.js'
  import { Mic } from '$lib/icons.js'
  import Select from './Select.svelte'

  let { compact = false } = $props()
  const v = app.voice
  const current = $derived(v.devices.find((d) => d.deviceId === v.deviceId))
  const options = $derived([
    { value: '', label: 'System default' },
    ...v.devices.map((d) => ({ value: d.deviceId, label: d.label })),
  ])
</script>

<div class="picker" class:compact title={v.deviceLabel ? `In use: ${v.deviceLabel}` : 'Microphone'}>
  {#if compact}<span class="icon"><Mic size={12} /></span>{:else}<span class="lbl">Microphone</span>{/if}
  <Select {options} value={current ? v.deviceId : ''} onchange={(id) => v.setDevice(id)} onopen={() => v.refreshDevices()}
          label="Microphone" {compact} testid="mic-device" />
</div>

<style>
  .picker { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: var(--muted); min-width: 0; }
  .picker.compact { flex-direction: row; align-items: center; gap: 6px; max-width: 240px; }
  .icon { display: inline-flex; flex: 0 0 auto; }
  .picker.compact :global(.sel) { flex: 1 1 auto; }
</style>
