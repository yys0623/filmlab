import { test } from 'node:test'
import assert from 'node:assert/strict'
import { unzipSync } from 'fflate'

test('incremental photo ZIP contains every file with its original bytes', async () => {
  const messages: any[] = []
  const worker = { postMessage: (value: unknown) => messages.push(value), onmessage: null as any }
  ;(globalThis as any).self = worker
  try {
    await import('../src/photoExport.worker.ts')
    await worker.onmessage({ data: { type: 'zip-start' } })
    await worker.onmessage({ data: { type: 'zip-add', name: 'one.jpg', bytes: Uint8Array.of(1, 2, 3) } })
    await worker.onmessage({ data: { type: 'zip-add', name: 'two.jpg', bytes: Uint8Array.of(4, 5) } })
    await worker.onmessage({ data: { type: 'zip-finish' } })
    const entries = unzipSync(new Uint8Array(await messages.at(-1).archive.arrayBuffer()))
    assert.deepEqual([...entries['one.jpg']], [1, 2, 3])
    assert.deepEqual([...entries['two.jpg']], [4, 5])
  } finally { delete (globalThis as any).self }
})
