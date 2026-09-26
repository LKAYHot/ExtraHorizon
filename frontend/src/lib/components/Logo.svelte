<script>
  let { size = 30 } = $props()
</script>

<svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
  <defs>
    <linearGradient id="eh-logo-g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#b3c7ff" />
      <stop offset=".5" stop-color="#7a98ff" />
      <stop offset="1" stop-color="#a58bff" />
    </linearGradient>
  </defs>
  <rect width="32" height="32" rx="9" fill="#0b1326" />
  <rect x=".5" y=".5" width="31" height="31" rx="8.5" fill="none" stroke="rgb(170 190 255 / .18)" />
  <circle cx="16" cy="16" r="9.5" fill="none" stroke="url(#eh-logo-g)" stroke-width="2.6" />
  <path d="M4.5 19.5c6-2.6 16.5-2.6 23 0" fill="none" stroke="url(#eh-logo-g)" stroke-width="2.6" stroke-linecap="round" />
  <circle cx="16" cy="12.5" r="2.4" fill="#eef2ff" />
</svg>
