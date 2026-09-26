import { expect, test } from '@playwright/test'

test('two faces → ambiguous: no expression is read and nothing about a face reaches the prompt', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (the camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await expect(page.getByTestId('face-presence')).toContainText('2 faces — ambiguous', { timeout: 20_000 })
  await expect(page.getByTestId('emotion-dominant')).toHaveAttribute('data-emotion', '')
  await expect(page.getByTestId('emotion-now')).toContainText('Several faces')
  await expect(page.getByTestId('prompt-card')).toContainText('Nothing about your face right now')
})
