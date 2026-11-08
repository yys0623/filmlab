import { test, expect } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('film-lab-locale', 'en'))
  await page.goto('/')
  await expect(page.locator('.preview .result-image img')).toBeVisible({ timeout: 45000 })
})

test('retries a failed print timing fetch', async ({ page }) => {
  let requests = 0
  await page.route('**/print-timing/*.bin', async route => {
    requests++
    if (requests === 1) await route.fulfill({ status: 503, body: 'unavailable' })
    else await route.continue()
  })
  await page.locator('.timing-panel input[type=range]').first().fill('5')
  await expect(page.locator('.preview .retry-button')).toBeVisible({ timeout: 30000 })
  await page.locator('.preview .retry-button').click()
  await expect.poll(() => requests).toBeGreaterThanOrEqual(2)
  await expect(page.locator('.preview .result-image img')).toBeVisible({ timeout: 45000 })
  await expect(page.locator('.preview .retry-button')).toHaveCount(0)
})

test('mobile mini preview retains its previous frame while a new LUT loads', async ({ page }) => {
  let release
  const gate = new Promise(resolve => { release = resolve })
  let started
  const requestStarted = new Promise(resolve => { started = resolve })
  await page.route('**/luts/**', async route => { started(); await gate; await route.continue() })
  await page.locator('.film-option').nth(1).click()
  await requestStarted
  await page.locator('.timing-panel').scrollIntoViewIfNeeded()
  const image = page.locator('.mini-preview img')
  try {
    await expect(image).toBeVisible()
    await expect.poll(() => image.evaluate(img => img.complete && img.naturalWidth > 0)).toBe(true)
    const oldUrl = await image.getAttribute('src')
    expect(await page.evaluate(async url => (await fetch(url)).ok, oldUrl)).toBe(true)
  } finally { release() }
  await expect(page.locator('.preview .result-image img')).toBeAttached({ timeout: 45000 })
})

test('changing looks discards an in-flight result and renders the latest selection', async ({ page }) => {
  let release, started
  const gate = new Promise(resolve => { release = resolve })
  const requestStarted = new Promise(resolve => { started = resolve })
  let first = true
  await page.route('**/luts/**', async route => {
    if (first) { first = false; started(); await gate }
    await route.continue().catch(() => {})
  })
  try {
    await page.locator('.film-option').nth(1).click()
    await requestStarted
    await page.locator('.film-option').nth(2).click()
    await expect(page.locator('.film-option').nth(2)).toHaveClass(/selected/)
    await expect(page.locator('.preview .result-image img')).toBeVisible({ timeout: 45000 })
  } finally { release() }
})

test('pins a look and compares it with another look on the same photo', async ({ page }) => {
  const controls = page.locator('.look-compare-controls')
  await controls.getByRole('button', { name: 'Pin current look as A' }).click()
  await expect(page.locator('.preview .image-tag.before')).toContainText('A ·', { timeout: 45000 })
  const pinnedLabel = await page.locator('.preview .image-tag.before').textContent()
  await page.locator('.film-option').nth(1).click()
  await expect(page.locator('.preview .image-tag.after')).toHaveText('B · Current look', { timeout: 45000 })
  await expect(page.locator('.preview .image-tag.before')).toHaveText(pinnedLabel)
  await page.locator('.comparison-range').fill('25')
  await expect(page.locator('.comparison-range')).toHaveAttribute('aria-valuetext', 'Look A 25%, look B 75%')
  await page.locator('.sample-option').nth(1).click()
  await expect(page.locator('.preview .image-tag.before')).toContainText('A ·', { timeout: 45000 })
  await controls.getByRole('button', { name: 'Clear A' }).click()
  await expect(controls.getByRole('button', { name: 'Pin current look as A' })).toBeVisible()
  await expect(page.locator('.preview .image-tag.after')).toHaveText('LUT applied · 100%', { timeout: 45000 })
})
