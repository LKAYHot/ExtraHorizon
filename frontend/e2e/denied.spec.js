import { expect, test } from '@playwright/test'

test('camera permission denied → clear status, chat still works', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', /denied|unavailable/)
  await expect(page.getByTestId('vision-banner')).toContainText('Vision unavailable — chat still works')
  await expect(page.getByTestId('signal-value')).toHaveText('—')

  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')
  await expect(page.getByTestId('explain-differently-disabled')).toBeVisible()
})
