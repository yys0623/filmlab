import { Zip, ZipPassThrough } from 'fflate'
import { addJpegDescription } from './jpegMetadata.ts'

let zip: Zip | undefined
let chunks: Uint8Array<ArrayBuffer>[] = []
self.onmessage = async (event: MessageEvent<{ type: 'metadata'; jpeg: Blob; original: File; description: string } | { type: 'zip-start' } | { type: 'zip-add'; name: string; bytes: Uint8Array<ArrayBuffer> } | { type: 'zip-finish' }>) => {
  try {
    if (event.data.type === 'metadata') {
      const { jpeg, original, description } = event.data
      self.postMessage({ blob: await addJpegDescription(jpeg, original, description) })
    } else if (event.data.type === 'zip-start') {
      chunks = []
      zip = new Zip((error, chunk) => { if (error) throw error; chunks.push(chunk) })
      self.postMessage({ ok: true })
    } else if (event.data.type === 'zip-add') {
      if (!zip) throw new Error('ZIP 파일을 시작하지 못했습니다.')
      const entry = new ZipPassThrough(event.data.name)
      zip.add(entry)
      entry.push(event.data.bytes, true)
      self.postMessage({ ok: true })
    } else {
      if (!zip) throw new Error('ZIP 파일을 시작하지 못했습니다.')
      zip.end()
      const archive = new Blob(chunks, { type: 'application/zip' })
      zip = undefined; chunks = []
      self.postMessage({ archive })
    }
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : '사진을 다운로드하지 못했습니다.' })
  }
}
