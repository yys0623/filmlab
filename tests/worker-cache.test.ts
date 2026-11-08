import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'

test('worker reuses verified LUTs and bounds its cache', async () => {
  const originalFetch = globalThis.fetch
  const responses: any[] = []
  const worker = { postMessage: (message: unknown) => responses.push(message), onmessage: null as any }
  ;(globalThis as any).self = worker
  let fetches = 0
  const text = '#LUMIXPHOTOSTYLE STD\nLUT_3D_SIZE 33\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n' + '0 0 0\n'.repeat(33 ** 3)
  const bytes = new TextEncoder().encode(text)
  const sha256 = createHash('sha256').update(bytes).digest('hex')
  globalThis.fetch = async () => { fetches++; return new Response(bytes) }
  try {
    await import('../src/lut.worker.ts')
    const run = async (id: number, name: string) => worker.onmessage({ data: {
      id, pixels: new Uint8ClampedArray([30, 40, 50, 255]),
      asset: { path: `/${name}`, name, bytes: bytes.length, sha256 },
    } })
    await run(1, 'a'); await run(2, 'a')
    assert.equal(fetches, 1)
    assert.deepEqual([...responses[1].pixels], [0, 0, 0, 255])
    for (const [id, name] of [[3, 'b'], [4, 'c'], [5, 'd'], [6, 'e']] as const) await run(id, name)
    await run(7, 'a')
    assert.equal(fetches, 6, 'least recently used LUT is fetched again after eviction')
    let release!: (response: Response) => void
    globalThis.fetch = async input => {
      if (String(input) === '/slow') return new Promise<Response>(resolve => { release = resolve })
      if (String(input) === '/failure') return new Response('', { status: 503 })
      return new Response(bytes)
    }
    const pending = run(8, 'slow')
    await run(9, 'a')
    release(new Response(bytes))
    await pending
    assert.equal(responses.some(message => message.id === 8), false, 'stale result is discarded')
    assert.equal(responses.at(-1).id, 9)
    await run(10, 'failure')
    assert.ok(responses.at(-1).error)
    globalThis.fetch = async () => new Response(bytes)
    await run(11, 'failure')
    assert.ok(responses.at(-1).pixels, 'failed fetch is retried')
    const large = worker.onmessage({ data: { id: 12, pixels: new Uint8ClampedArray(1024 * 1024), asset: { path: '/failure', name: 'failure', bytes: bytes.length, sha256 } } })
    await new Promise(resolve => setTimeout(resolve, 0))
    await run(13, 'failure')
    await large
    assert.equal(responses.some(message => message.id === 12), false, 'processing yields to newer requests')
    assert.equal(responses.at(-1).id, 13)
  } finally {
    globalThis.fetch = originalFetch
    delete (globalThis as any).self
  }
})
