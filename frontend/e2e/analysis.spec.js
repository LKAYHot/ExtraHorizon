import { expect, test } from '@playwright/test'

// The utility-coordination analysis, automated, on the labelled synthetic TEST fixtures
// (backend/tests/fixtures/coord via EH_COORD_OFFLINE_DIR — make_coord_fixtures.py documents the
// expected result), so no county service is contacted; the map's OpenStreetMap tiles are blocked
// too. The answer comes from the offline mock tutor, which repeats the fact sheet word for word.
test.beforeEach(async ({ page }) => {
  await page.route('https://tile.openstreetmap.org/**', (route) => route.abort())
})

test('ask → verified analysis → map, findings, schedules, sources → grounded answer → follow-up', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('speaker-toggle').click() // her voice stays off
  await page.getByTestId('coord-example').click()

  // the chat shows the run and then its result; the analysis replaces the camera panel
  const card = page.getByTestId('analysis-card')
  await expect(card).toContainText('7 overlaps between 4 plans · 7 verified projects', { timeout: 30_000 })
  await expect(card).toContainText('test fixture') // never passed off as the county's data
  const panel = page.getByTestId('analysis-panel')
  await expect(panel).toContainText('TEST FIXTURE')
  await expect(page.getByTestId('coord-map')).toBeVisible()
  await expect(page.getByTestId('coord-findings-count')).toHaveText('7')

  // her answer is checked against the verified fact sheet
  const answer = page.getByTestId('assistant-message').first()
  await expect(answer).toHaveAttribute('data-status', 'done')
  await expect(answer).toContainText('F1')
  await expect(answer.getByTestId('grounding-ok')).toContainText('match the verified data')

  // it opens on the strongest finding (the one she names first) and its pair of plans:
  // WASD's sewer and water plans cross (F1)
  await expect(page.getByTestId('coord-pair')).toContainText('WASD · Sewer ↔ WASD · Water')
  const findings = page.getByTestId('coord-finding')
  await expect(findings).toHaveCount(2)
  const f1 = page.locator('[data-testid="coord-finding"][data-id="F1"]')
  await expect(f1).toHaveClass(/sel/)
  await expect(f1).toContainText('intersect')
  await expect(f1).toContainText('together 121 days')
  await expect(f1.getByRole('link', { name: 'county list' })).toBeVisible() // on the county's own list
  await f1.getByRole('button', { name: 'Show on map' }).click()
  await expect(f1).toHaveClass(/sel/)
  await expect(f1).toContainText('shared excavation')
  await f1.getByTestId('coord-recheck').click() // read both records again from the source
  await expect(f1.getByTestId('coord-recheck-result')).toContainText('unchanged at the source')

  // another pair: the utility plan first (blue), the road work second (orange)
  await page.getByTestId('coord-pair').click()
  await page.getByRole('option', { name: /WASD · Water ↔ FDOT · Roadway/ }).click()
  await expect(findings).toHaveCount(2)
  await expect(page.locator('[data-testid="coord-finding"].sel')).toHaveCount(0) // F1 is not in this pair
  await expect(findings.first()).toContainText('not in county list')
  await expect(page.getByTestId('coord-filter-near')).toContainText('2')

  // schedules: one row per finding, both bars and the time they overlap
  await page.getByTestId('coord-tab-timeline').click()
  await expect(page.getByTestId('coord-timeline').locator('g.row')).toHaveCount(2)

  // sources and checks: every layer with its verification, labelled as test data
  await page.getByTestId('coord-tab-sources').click()
  const sources = page.getByTestId('coord-sources')
  await expect(sources).toContainText('OFFLINE TEST FIXTURE')
  await expect(sources.locator('tbody tr')).toHaveCount(14)
  await expect(sources).toContainText('placeholder or impossible dates')
  // stricter rules, recomputed on the same verified data: "close" = within 10 m
  await sources.locator('input[type=number]').first().fill('10')
  await page.getByTestId('coord-apply').click()
  await expect(page.getByTestId('coord-findings-count')).toHaveText('5')

  // a follow-up is answered from the analysis on screen — no new run
  await page.getByTestId('composer').fill('Why does F1 matter?')
  await page.getByTestId('send').click()
  const second = page.getByTestId('assistant-message').nth(1)
  await expect(second).toHaveAttribute('data-status', 'done')
  await expect(page.getByTestId('analysis-card')).toHaveCount(1)
  await expect(second.getByTestId('grounding-ok')).toBeVisible()

  // the map follows the conversation: a finding number spoken as words ("F пять" = F5; the stricter rules
  // left five findings) moves it at once …
  await page.getByTestId('composer').fill('а что на F пять?')
  await page.getByTestId('send').click()
  const third = page.getByTestId('assistant-message').nth(2)
  await expect(third).toHaveAttribute('data-status', 'done')
  await expect(page.locator('[data-testid="coord-finding"][data-id="F5"]')).toHaveClass(/sel/)
  await expect(page.getByTestId('coord-pair')).toContainText('WASD · Sewer ↔ DTPW · Roadway')
  // … a finding ID in her answer is a button that shows it
  await second.locator('button.fid', { hasText: /^F1$/ }).first().click()
  await expect(page.locator('[data-testid="coord-finding"][data-id="F1"]')).toHaveClass(/sel/)
  // … and what she looks up (her tool: any finding, by the words of a name) is spotlighted on the map
  await page.getByTestId('composer').fill('What overlaps with the county road resurfacing?')
  await page.getByTestId('send').click()
  const fourth = page.getByTestId('assistant-message').nth(3)
  await expect(fourth).toHaveAttribute('data-status', 'done')
  await expect(fourth.getByTestId('tool-tags')).toContainText('looked up')
  await expect(fourth).toContainText('TR-301')
  await expect(page.getByTestId('coord-spot')).toContainText('2 findings')
  await expect(page.getByTestId('coord-pair')).toContainText('All pairs of plans')
  await expect(findings).toHaveCount(2)
  await page.getByTestId('coord-spot-clear').click()
  await expect(page.getByTestId('coord-spot')).toHaveCount(0)
  // the map stays in view while the list scrolls under it: the last card of all pairs, and the map is still seen
  const last = findings.last()
  await last.locator('button.fid').click()
  await expect(last).toHaveClass(/sel/)
  await expect(last).toBeInViewport()
  await expect(page.getByTestId('coord-map')).toBeInViewport({ ratio: 0.95 })

  // back to the camera panel and again; a new session forgets the analysis
  await page.getByTestId('coord-hide').click()
  await expect(panel).toHaveCount(0)
  await expect(page.getByTestId('camera-status')).toBeVisible()
  await expect(page.getByTestId('privacy-coord')).toContainText('OpenStreetMap') // the data flows are disclosed
  await page.getByTestId('coord-toggle').click()
  await expect(page.getByTestId('coord-findings-count')).toHaveText('5')
  // closing the analysis: ordinary questions are ordinary tutoring again (no fact sheet, no grounding tag)
  await page.getByTestId('coord-close').click()
  await expect(panel).toHaveCount(0)
  await page.getByTestId('composer').fill('Explain recursion to me.')
  await page.getByTestId('send').click()
  const fifth = page.getByTestId('assistant-message').nth(4)
  await expect(fifth).toHaveAttribute('data-status', 'done')
  await expect(fifth.getByTestId('grounding-ok')).toHaveCount(0)
  await expect(fifth.getByTestId('analysis-card')).toHaveCount(0)
  await page.getByTestId('reset').click()
  await expect(page.getByTestId('assistant-message')).toHaveCount(0)
  await page.getByTestId('coord-toggle').click()
  await expect(page.getByTestId('coord-intro')).toBeVisible()
})

test('the analysis runs from the panel too, and a question in Russian starts it', async ({ page }) => {
  await page.goto('/')
  await page.getByTestId('speaker-toggle').click()
  await page.getByTestId('coord-toggle').click()
  await expect(page.getByTestId('coord-intro')).toContainText('physically close')
  await page.getByTestId('coord-run').click()
  await expect(page.getByTestId('coord-findings-count')).toHaveText('7', { timeout: 30_000 })
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')

  await page.getByTestId('reset').click()
  await page.getByTestId('composer').fill('Сравни планы строительства коммунальных служб и найди пересечения')
  await page.getByTestId('send').click()
  await expect(page.getByTestId('analysis-card')).toContainText('7 overlaps', { timeout: 30_000 })
  await expect(page.getByTestId('assistant-message').first()).toHaveAttribute('data-status', 'done')
})
