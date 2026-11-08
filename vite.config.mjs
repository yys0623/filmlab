import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'

// The source archive omits the runtime catalog and its large asset library.
// Use the public deployment until an unpacked local catalog is supplied.
const hasLocalCatalog = existsSync(fileURLToPath(new URL('./public/catalog.json', import.meta.url)))
const runtimePaths = [
  '/catalog.json', '/samples/', '/luts/', '/camera-adapters/', '/supplied-fuji/',
  '/print-timing/', '/source/', '/gallery/', '/manual/', '/fonts/', '/licenses/',
  '/favicon.svg',
]

export default defineConfig({
  server: {
    proxy: hasLocalCatalog ? {} : Object.fromEntries(runtimePaths.map(path => [path, {
      target: 'https://sosang.film-lab-jc.workers.dev',
      changeOrigin: true,
    }])),
  },
})
