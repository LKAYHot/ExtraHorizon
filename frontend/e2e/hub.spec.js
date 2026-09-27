import { randomUUID } from 'node:crypto'
import { test, expect } from '@playwright/test'

// The hackathon hub on the labelled synthetic TEST fixtures (mock LLM, no network, a board in memory — no sample
// entries): stuck → verified public answers → share what fixed it / ask a person → real open questions → a card with
// GitHub-seen skills → teammates from public GitHub profiles → mentors from Stack Overflow's top answerers → a
// deadline picked in the app's own calendar → the road to shipping. Tutoring stays tutoring.
test('stuck → verified fixes → share / ask → people → ship', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByTestId('persona')).toBeVisible()
  await page.getByTestId('speaker-toggle').click() // never play her voice on the machine running the tests

  // a roadblock in the chat: the hub searches first, the panel shows what was verified, she explains it
  await page.getByTestId('hub-example').click()
  const first = page.getByTestId('assistant-message').first()
  await expect(first).toHaveAttribute('data-status', 'done', { timeout: 20_000 })
  await expect(first.getByTestId('hub-card')).toContainText('verified result')
  await expect(first.getByTestId('hub-card')).toContainText('test fixture')
  await expect(first.getByTestId('grounding-ok')).toBeVisible()
  const panel = page.getByTestId('hub-panel')
  await expect(panel).toBeVisible()
  await expect(page.getByTestId('hub-source-chip')).toHaveText('TEST FIXTURE')
  const s1 = page.locator('[data-testid="hub-item"][data-ref="S1"]')
  await expect(s1).toContainText('accepted')
  await expect(s1).toContainText('CORSMiddleware') // the answer's code
  await expect(s1).toContainText('CC BY-SA 4.0') // …with its author and licence
  await expect(page.locator('[data-testid="hub-item"][data-ref="S3"]')).toContainText("check it against today's versions")
  // an ID in her answer shows that result
  await first.locator('button.hid', { hasText: /^S2$/ }).first().click()
  await expect(page.locator('[data-testid="hub-item"][data-ref="S2"]')).toHaveClass(/sel/)
  // how it was checked
  await page.getByTestId('hub-audit-toggle').click()
  await expect(page.getByTestId('hub-audit')).toContainText('not about this error')

  // this fixed it → a card for the next team; still stuck → a help request
  await s1.getByTestId('hub-fixed').click()
  await page.getByTestId('hub-share-fix').fill('The exact dev-server origin in allow_origins.')
  await page.getByTestId('hub-share-post').click()
  await page.getByTestId('hub-still-stuck').click()
  await expect(page.getByTestId('hub-ask-problem')).toHaveValue(/Already tried: S1/)
  await page.getByTestId('hub-ask-post').click()
  await expect(page.getByTestId('hub-tab-board')).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByTestId('hub-cards')).toContainText('The exact dev-server origin in allow_origins.')
  await expect(page.locator('body')).not.toContainText('(sample)') // only what real people wrote
  // questions nobody has answered yet in the stack of that search (Stack Overflow, real in the live app)
  await expect(page.getByTestId('hub-open-questions')).toContainText('TEST — FastAPI background task never runs')
  await expect(page.getByTestId('hub-open-questions')).toContainText('from the stack of your last search')
  const mine = page.locator('[data-testid="hub-request"].mine').first()
  await expect(mine).toHaveAttribute('data-status', 'open')
  // a helper from another team takes it (their browser, through the same API) …
  const rid = await mine.getAttribute('data-rid')
  const helper = randomUUID()
  expect((await page.request.post('/api/hub/profile', { data: { session_id: helper, name: 'E2E Helper', skills: ['fastapi'] } })).ok()).toBeTruthy()
  expect((await page.request.post(`/api/hub/requests/${rid}/claim`, { data: { session_id: helper } })).ok()).toBeTruthy()

  // people: a card with GitHub (only with the box ticked), then teammates
  await page.getByTestId('hub-tab-people').click()
  await page.getByTestId('hub-p-new').click()
  await page.getByTestId('hub-p-name').fill('E2E Hacker')
  await page.getByTestId('hub-p-skills').fill('python, fastapi')
  await page.getByTestId('hub-p-looking').fill('frontend, design')
  await page.getByTestId('hub-p-github').fill('octo-test')
  await page.getByTestId('hub-p-consent').check()
  await page.getByTestId('hub-p-save').click()
  await expect(page.getByTestId('hub-my-card')).toContainText('seen in your public GitHub repos', { timeout: 10_000 })
  // … the board they got back shows who is coming, and the team that asked can give it back
  await page.getByTestId('hub-tab-board').click()
  const claimed = page.locator(`[data-testid="hub-request"][data-rid="${rid}"]`)
  await expect(claimed).toHaveAttribute('data-status', 'claimed')
  await expect(claimed).toContainText('E2E Helper is on it')
  await claimed.getByTestId('hub-release').click()
  await expect(claimed).toHaveAttribute('data-status', 'open')
  await page.getByTestId('hub-tab-people').click()
  await page.getByTestId('hub-find-team').click()
  const second = page.getByTestId('assistant-message').nth(1)
  await expect(second).toHaveAttribute('data-status', 'done', { timeout: 20_000 })
  await expect(second.getByTestId('hub-card')).toContainText('Teammates')
  // nobody on the board covers frontend: real public GitHub profiles in the event's city do (TEST fixtures here)
  const p1 = page.getByTestId('hub-matches').locator('[data-ref="P1"]')
  await expect(p1).toHaveAttribute('data-source', 'github')
  await expect(p1).toContainText('covers')
  await expect(p1).toContainText("haven't said they're looking for a team")
  await expect(page.getByTestId('hub-matches')).toContainText('Public GitHub profiles · Miami')
  await expect(page.getByTestId('hub-people-audit')).toContainText('an organisation, not a person')
  // a mentor: the board has none — Stack Overflow's top answerers for the stack
  await page.getByTestId('composer').fill('Is there a mentor who knows PyTorch?')
  await page.getByTestId('send').click()
  const mentorsMsg = page.getByTestId('assistant-message').nth(2)
  await expect(mentorsMsg).toHaveAttribute('data-status', 'done', { timeout: 20_000 })
  const m1 = page.getByTestId('hub-matches').locator('[data-ref="M1"]')
  await expect(m1).toHaveAttribute('data-source', 'stackoverflow')
  await expect(m1).toContainText('answered 2 this month')
  await expect(m1.getByRole('link', { name: /Ask a \[pytorch\] question/ })).toHaveAttribute('href', /questions\/ask\?tags=pytorch/)

  // the road to shipping: a deadline picked in the app's own calendar (tomorrow, 6:30 PM)
  await page.getByTestId('hub-tab-ship').click()
  await page.getByTestId('hub-dl-pick').click()
  await expect(page.getByTestId('dtp')).toBeVisible()
  const t = new Date(Date.now() + 86_400_000)
  const day = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`
  await page.locator(`[data-testid="dtp-day"][data-date="${day}"]`).click()
  await page.getByTestId('dtp-hour-6').click()
  await page.getByTestId('dtp-minute-30').click()
  await page.getByTestId('dtp-pm').click()
  await expect(page.getByTestId('dtp-chosen')).toContainText('6:30 PM')
  await page.getByTestId('dtp-set').click()
  await expect(page.getByTestId('hub-left')).toContainText('left')
  await expect(page.getByTestId('hub-dl-when')).toContainText('6:30 PM')
  await page.getByTestId('hub-ms-team').check()
  await expect(page.getByTestId('hub-milestones')).toBeVisible()
  await expect(page.getByTestId('hub-roadblock').first()).toBeVisible() // the CORS roadblock she searched

  // Russian question → the same search; tutoring stays tutoring
  await page.getByTestId('composer').fill("у меня ошибка ModuleNotFoundError: No module named 'cv2'")
  await page.getByTestId('send').click()
  const third = page.getByTestId('assistant-message').nth(3)
  await expect(third).toHaveAttribute('data-status', 'done', { timeout: 20_000 })
  await expect(page.locator('[data-testid="hub-item"][data-ref="S1"]')).toContainText('opencv-python')
  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  const fourth = page.getByTestId('assistant-message').nth(4)
  await expect(fourth).toHaveAttribute('data-status', 'done', { timeout: 20_000 })
  await expect(fourth.getByTestId('hub-card')).toHaveCount(0)
})
