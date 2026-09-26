import { expect, test } from '@playwright/test'

test('camera permission denied → clear status, chat still works', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (the camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', /denied|unavailable/)
  await expect(page.getByTestId('vision-banner')).toContainText('chat and voice still work')
  await expect(page.getByTestId('emotion-dominant')).toHaveText('Unknown')

  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')
})

test('microphone permission denied → clear message, typing still works', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('mic-toggle').click()
  await page.getByTestId('mic-on').click()
  await expect(page.getByTestId('mic-error')).toContainText(/denied|blocked|could not start|No microphone/i)
  await expect(page.getByTestId('mic-toggle')).toHaveAttribute('aria-pressed', 'false')
})
