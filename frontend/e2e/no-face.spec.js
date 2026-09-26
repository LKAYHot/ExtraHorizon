import { expect, test } from '@playwright/test'

test('no face → unknown (not neutral), chat still works', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (the camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await expect(page.getByTestId('face-presence')).toContainText('No face in view', { timeout: 20_000 })
  await expect(page.getByTestId('emotion-dominant')).toHaveText('Unknown')
  await expect(page.getByTestId('emotion-now')).toContainText('No face in view')

  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  const answer = page.getByTestId('assistant-message').first()
  await expect(answer).toHaveAttribute('data-status', 'done')
  await answer.getByTestId('ctx-toggle').click()
  await expect(answer.getByTestId('ctx-note')).toContainText('Nothing about your face was sent')
})

test('camera switched off mid-session → unknown, chat unaffected', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('camera-on').click() // explicit consent (the camera never starts by itself)
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
  await page.getByRole('button', { name: 'Turn off' }).click()
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'off')
  await expect(page.getByTestId('emotion-now')).toContainText('Camera is off')
  await page.getByTestId('camera-on').click()
  await expect(page.getByTestId('camera-status')).toHaveAttribute('data-status', 'active')
})
