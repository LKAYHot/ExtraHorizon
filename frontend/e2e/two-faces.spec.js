import { expect, test } from '@playwright/test'

test('two faces → ambiguous: the signal stays unknown and never adapts', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await expect(page.getByTestId('face-presence')).toContainText('2 faces — ambiguous', { timeout: 20_000 })
  await expect(page.getByTestId('signal-value')).toHaveText('—')
  await expect(page.getByTestId('signal-card')).toContainText('Several faces')
})
