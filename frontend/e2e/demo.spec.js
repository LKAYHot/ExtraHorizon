import { expect, test } from '@playwright/test'

// The 60–90 s demo, automated: question → streamed answer → event → adapted answer → reset.
// The camera is a virtual device showing a real face (processed by the real local
// MediaPipe pipeline). The CONFUSION rise is driven by the labelled Demo simulation
// mode — allowed only in tests / labelled mode, and asserted to be labelled.
test('question → answer → event → explain differently → why it adapted → reset', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (camera never starts by itself)

  // camera → local vision → face presence (real frames, real MediaPipe)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await expect(page.getByTestId('face-presence')).toContainText(/1 face/, { timeout: 20_000 })
  await expect(page.getByTestId('face-presence')).toContainText(/tracking|calibrating/)
  await expect(page.getByTestId('signal-value')).not.toHaveText('—', { timeout: 20_000 }) // calibrated → real reading

  // 1) ask — the answer streams in
  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  const answer = page.getByTestId('assistant-message').first()
  await expect(answer).toHaveAttribute('data-status', 'done')
  await expect(answer).toContainText('Recursion')
  await expect(page.getByTestId('explain-differently-disabled')).toBeVisible() // inactive before any event

  // 2) sustained signal (labelled simulation) → ONE event, offered under the answer
  await page.getByText('Demo simulation mode').click()
  await page.getByTestId('sim-toggle').check()
  await expect(page.getByTestId('sim-badge')).toBeVisible()
  await page.getByTestId('sim-high').click()
  const offer = page.getByTestId('explain-differently')
  await expect(offer).toBeVisible({ timeout: 8_000 })
  await expect(page.getByTestId('offer')).toContainText('Possible confusion detected')
  await expect(page.getByTestId('offer')).toContainText('SIMULATED')
  await page.getByTestId('sim-low').click()

  // 3) explain differently → a visibly different, adapted answer in the same chat
  await offer.click()
  await expect(page.getByTestId('user-action')).toHaveText(/Explain differently/)
  const adapted = page.getByTestId('assistant-message').nth(1)
  await expect(adapted).toHaveAttribute('data-status', 'done')
  await expect(adapted.getByTestId('adapted-badge')).toContainText('Analogy')
  const why = adapted.getByTestId('why-adapted')
  await expect(why).toContainText('manual Demo simulation — not live recognition')
  await expect(why).toContainText('EMA α 0.2')
  await expect(why).toContainText('Analogy → example → short steps')
  await why.getByText('Show exact text').click()
  const note = await why.getByTestId('instruction-text').innerText()
  expect(note).toContain('possible sign of confusion')
  expect(note).not.toMatch(/\d/) // no numbers → no false precision sent to the model
  // the decrease is shown only once it is actually measured (signal was set low above)
  await expect(why).toContainText(/stayed below 0\.45/, { timeout: 12_000 })

  // 4) reset clears chat, events, cooldown and timeline
  await page.getByTestId('reset').click()
  await expect(page.getByTestId('assistant-message')).toHaveCount(0)
  await expect(page.getByText('What do you want to understand?')).toBeVisible()
  await expect(page.getByTestId('event-card')).toHaveCount(0)
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

test('optional auto-adapt: visible countdown, then the adapted answer without a click', async ({ page }) => {
  await page.goto('/')
  await page.locator('label.toggle', { hasText: 'Auto-adapt' }).locator('input').check()
  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')
  await page.getByText('Demo simulation mode').click()
  await page.getByTestId('sim-toggle').check()
  await page.getByTestId('sim-high').click()
  await expect(page.getByTestId('offer')).toContainText(/Auto-adapting in \ds/, { timeout: 8_000 })
  await page.getByTestId('sim-low').click()
  const adapted = page.getByTestId('assistant-message').nth(1)
  await expect(adapted).toHaveAttribute('data-status', 'done', { timeout: 15_000 })
  await expect(adapted.getByTestId('adapted-badge')).toBeVisible()
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
