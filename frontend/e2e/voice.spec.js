import { existsSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { expect, test } from '@playwright/test'

// Hands-free voice, end to end in a real browser: the virtual microphone (an offline Windows
// voice saying a question) → AudioWorklet PCM16 → /api/live → real Silero VAD → speech-to-text
// (offline scripted double) → filler + turn → mock LLM → mock voice → WebAudio playback.
const here = path.dirname(fileURLToPath(import.meta.url))
test.skip(!existsSync(path.join(here, '.cache', 'question.wav')), 'virtual microphone clip unavailable (needs Windows SAPI)')

test('speak → she hears you, answers aloud, and the Stop button silences her', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('mic-toggle').click() // first use: the microphone disclosure
  await expect(page.getByTestId('mic-consent')).toContainText('OpenAI')
  await page.getByTestId('mic-on').click()
  await expect(page.getByTestId('mic-toggle')).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('voice-state')).toContainText('Listening')

  // the clip starts speaking after 1.5 s of silence — the backend's voice detection hears it
  await expect(page.getByTestId('talk-orb')).toHaveAttribute('data-state', 'hearing', { timeout: 15_000 })
  await expect(page.getByTestId('user-message').first()).toHaveText('Explain recursion to me.', { timeout: 15_000 })
  await expect(page.getByTestId('spoken-tag').first()).toBeVisible()
  const answer = page.getByTestId('assistant-message').first()
  await expect(answer).toContainText('Recursion', { timeout: 15_000 })

  // her voice plays (the offline mock voice is a tone) …
  await expect(page.getByTestId('talk-orb')).toHaveAttribute('data-state', 'speaking', { timeout: 15_000 })
  await expect(answer.locator('.tag.talk')).toBeVisible()
  // … until the Stop button (or talking over her) silences her at once
  await page.getByTestId('stop').click()
  await expect(page.getByTestId('talk-orb')).not.toHaveAttribute('data-state', 'speaking', { timeout: 5_000 })

  await page.getByTestId('mic-toggle').click()
  await expect(page.getByTestId('mic-toggle')).toHaveAttribute('aria-pressed', 'false')
})
