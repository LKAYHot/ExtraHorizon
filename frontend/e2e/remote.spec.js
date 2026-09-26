import { expect, test } from '@playwright/test'

// The presenter's PC behind Cloudflare Tunnel: this project's browser sends the headers Cloudflare
// adds (see playwright.config.js), so the server treats it as a remote browser — the access key is
// required, the privacy texts name the tunnel and the camera gets the lighter remote profile.
const KEY = process.env.EH_E2E_ACCESS_KEY ?? 'e2e-access-key-not-a-secret'

test('remote browser: access key gate → the app over the tunnel → remembered after a reload', async ({ page }) => {
  await page.goto('/')
  const gate = page.getByTestId('access-gate')
  await expect(gate).toBeVisible()
  await expect(gate).toContainText('Private demo')
  await expect(gate).toContainText('Cloudflare Tunnel')
  await expect(page.getByTestId('persona')).toHaveCount(0) // nothing of the app before the key

  await page.getByTestId('access-key').fill('not-the-key')
  await page.getByTestId('access-submit').click()
  await expect(page.getByTestId('access-error')).toHaveText('That key is not right.')

  await page.getByTestId('access-key').fill(KEY)
  await page.getByTestId('access-submit').click()
  await expect(page.getByTestId('persona')).toBeVisible()
  await expect(page.getByTestId('privacy-tunnel')).toContainText('Cloudflare')
  await expect(page.locator('.sidebar')).toContainText("presenter's PC · Cloudflare Tunnel")

  // the camera works through the guarded socket and uses the remote profile (≤ 8 fps)
  await page.getByTestId('camera-on').click()
  await expect(page.locator('[data-testid="emotion-dominant"][data-emotion="neutral"]')).toBeVisible({ timeout: 30_000 })
  await page.waitForTimeout(2500)
  const fps = Number((await page.locator('.perf').textContent()).match(/(\d+)\s*fps/)[1])
  expect(fps).toBeLessThanOrEqual(9)

  // a typed question works (mock tutor)
  const box = page.locator('textarea').first()
  await box.fill('Explain recursion to me.')
  await box.press('Enter')
  await expect(page.getByTestId('assistant-message').last()).toHaveAttribute('data-status', 'done', { timeout: 20_000 })

  // the key is remembered (HttpOnly cookie) — no gate after a reload
  await page.reload()
  await expect(page.getByTestId('persona')).toBeVisible()
  await expect(page.getByTestId('access-gate')).toHaveCount(0)
})
