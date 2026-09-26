import { expect, test } from '@playwright/test'

test('no face → unknown (not neutral), chat still works', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await expect(page.getByTestId('face-presence')).toContainText('No face in view', { timeout: 20_000 })
  await expect(page.getByTestId('signal-value')).toHaveText('—')
  await expect(page.getByTestId('signal-card')).toContainText('unknown — hold timer reset')

  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')
})

test('camera switched off mid-session → unknown, chat unaffected', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await page.getByRole('button', { name: 'Turn off' }).click()
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'off')
  await expect(page.getByTestId('vision-banner')).toContainText('chat still works')
  await expect(page.getByTestId('signal-card')).toContainText('Camera is off')
  await page.getByTestId('camera-on').click()
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
})
