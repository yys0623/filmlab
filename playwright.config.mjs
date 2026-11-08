import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 60000,
  use: { baseURL: 'http://127.0.0.1:5187', browserName: 'chromium', viewport: { width: 390, height: 844 } },
  webServer: { command: 'yarn dev --port 5187 --strictPort', url: 'http://127.0.0.1:5187', reuseExistingServer: false, timeout: 30000 },
})
