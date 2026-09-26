import { expect, test } from '@playwright/test'

// The demo, automated. The camera is a virtual device showing a real face, processed by the
// real local pipeline (MediaPipe + the on-device expression model); the answer comes from the
// labelled offline mock tutor and is "spoken" by the offline mock voice.
test('camera → expression → question → answer with voice cues and the expression note → reset', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (the camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  // the learner's relaxed face is learned first (calibration), then the estimate is read against it:
  // the virtual camera's steady face is this person's neutral (the raw model calls it "happy")
  await expect(page.getByTestId('face-presence')).toContainText('1 face · tracking (calibrated to you)', { timeout: 20_000 })
  await expect(page.getByTestId('emotion-dominant')).toHaveAttribute('data-emotion', 'neutral', { timeout: 20_000 })
  // recalibration on request
  await page.getByTestId('recalibrate').click()
  await expect(page.getByTestId('emotion-dominant')).toHaveText('Calibrating…', { timeout: 5_000 })
  await expect(page.getByTestId('emotion-dominant')).toHaveAttribute('data-emotion', 'neutral', { timeout: 20_000 })
  await expect(page.getByTestId('face-label')).toBeVisible()
  const note = page.getByTestId('prompt-note')
  await expect(note).toContainText("What you see on the learner's webcam")
  expect(await note.innerText()).not.toMatch(/\d/) // words only — no false precision sent to the model

  // ask → the answer streams in; her voice cues show as stage directions, never as raw [tags]
  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  const answer = page.getByTestId('assistant-message').first()
  await expect(answer).toHaveAttribute('data-status', 'done')
  await expect(answer).toContainText('Recursion')
  await expect(answer.locator('.cue').first()).toBeVisible()
  await expect(answer).not.toContainText('[huffy')
  // the exact expression note that went into her prompt for this answer
  await answer.getByTestId('ctx-toggle').click()
  await expect(answer.getByTestId('ctx-note-text')).toContainText('webcam')

  // the timeline has a table view (every value reachable without hovering)
  await page.getByRole('button', { name: 'Toggle table view' }).click()
  await expect(page.getByTestId('emotion-timeline').locator('tbody tr').first()).toBeVisible()

  // labelled Demo simulation drives the same engine and note
  await page.getByText('Demo simulation mode').click()
  await page.getByTestId('sim-toggle').check()
  await page.getByTestId('sim-sadness').click()
  await expect(page.getByTestId('sim-badge')).toBeVisible()
  await expect(page.getByTestId('emotion-dominant')).toHaveAttribute('data-emotion', 'sadness', { timeout: 8_000 })
  await expect(note).toContainText('sad')

  // new session clears everything
  await page.getByTestId('reset').click()
  await expect(page.getByTestId('assistant-message')).toHaveCount(0)
  await expect(page.getByText('What do you want to understand?')).toBeVisible()
})

test('the camera never starts before consent; consent is remembered', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('camera-consent')).toContainText('usage metrics')
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'off')
  await page.getByTestId('camera-on').click()
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await page.reload()
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active') // remembered
  // and frames really flow after the reload (regression: camera ready before the server hello)
  await expect(page.getByTestId('face-presence')).toContainText(/1 face/, { timeout: 20_000 })
})

test('refresh keeps the conversation of this tab', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')
  await page.reload()
  await expect(page.getByTestId('user-message')).toHaveText('Explain recursion to me.')
  await expect(page.getByTestId('assistant-message').first()).toContainText('Recursion')
})

test('a duplicated tab gets its own session instead of sharing one', async ({ page, context }) => {
  await page.goto('/')
  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')
  const sid = await page.evaluate(() => sessionStorage.getItem('eh.session'))
  // "Duplicate tab" copies sessionStorage — emulate it for a second page of the same browser
  const dup = await context.newPage()
  await dup.addInitScript((id) => sessionStorage.setItem('eh.session', id), sid)
  await dup.goto('/')
  await expect(dup.getByText('What do you want to understand?')).toBeVisible()
  await dup.waitForTimeout(500)
  expect(await dup.evaluate(() => sessionStorage.getItem('eh.session'))).not.toBe(sid)
  await expect(dup.getByTestId('user-message')).toHaveCount(0) // not the first tab's conversation
  await expect(page.getByTestId('user-message')).toHaveText('Explain recursion to me.') // first tab untouched
})
