import { defineConfig } from '@playwright/test'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// E2E smoke tests against the real backend (mock LLM + offline voice doubles — no API key,
// no internet needed) serving the production build. Browsers get a VIRTUAL camera (a clip of
// the MediaPipe test portrait) and, for the voice test, a VIRTUAL microphone (an offline
// Windows voice asking a question) — see e2e/global-setup.js — so the real capture →
// WebSocket → MediaPipe / expression model / Silero VAD paths run without anyone's face or voice.
const here = path.dirname(fileURLToPath(import.meta.url))
const cache = path.join(here, 'e2e', '.cache')
const PORT = Number(process.env.EH_E2E_PORT ?? 8799)
const channel = process.env.PW_CHANNEL ?? 'msedge' // an installed browser; no download needed

const fakeCam = (file) => [
  '--use-fake-ui-for-media-stream',
  '--use-fake-device-for-media-stream',
  ...(file ? [`--use-file-for-fake-video-capture=${path.join(cache, file)}`] : []),
]
const fakeMic = (file) => [`--use-file-for-fake-audio-capture=${path.join(cache, file)}%noloop`, '--autoplay-policy=no-user-gesture-required']

export default defineConfig({
  testDir: 'e2e',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [['list']],
  globalSetup: './e2e/global-setup.js',
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    channel,
    viewport: { width: 1440, height: 900 },
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'face', testMatch: /demo\.spec\.js/, use: { launchOptions: { args: fakeCam('face.y4m') } } },
    { name: 'voice', testMatch: /voice\.spec\.js/, use: { launchOptions: { args: [...fakeCam('face.y4m'), ...fakeMic('question.wav')] } } },
    { name: 'two-faces', testMatch: /two-faces\.spec\.js/, use: { launchOptions: { args: fakeCam('two_faces.y4m') } } },
    { name: 'no-face', testMatch: /no-face\.spec\.js/, use: { launchOptions: { args: fakeCam(null) } } },
    // no fake-ui flag → the permission prompt is refused → "permission denied" path
    { name: 'denied', testMatch: /denied\.spec\.js/, use: { launchOptions: { args: ['--use-fake-device-for-media-stream', '--deny-permission-prompts'] } } },
  ],
  webServer: {
    command: `uv run --directory ../backend python -m extrahorizon --port ${PORT} --mock-llm --mock-voice`,
    url: `http://127.0.0.1:${PORT}/api/health`,
    reuseExistingServer: false,
    timeout: 90_000,
    env: { EH_MOCK_LLM_DELAY_S: '0.01', EH_LOG_LEVEL: 'warning' },
  },
})
