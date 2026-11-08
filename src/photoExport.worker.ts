import { zipSync } from 'fflate'
import { addJpegDescription } from './jpegMetadata'

self.onmessage = async (event: MessageEvent<{ type: 'metadata'; jpeg: Blob; original: File; description: string } | { type: 'zip'; entries: Record<string, Uint8Array> }>) => {
  try {
    if (event.data.type === 'metadata') {
      const { jpeg, original, description } = event.data
      self.postMessage({ blob: await addJpegDescription(jpeg, original, description) })
    } else {
      const archive = zipSync(event.data.entries, { level: 0 })
      self.postMessage({ archive }, { transfer: [archive.buffer] })
    }
  } catch (error) {
    self.postMessage({ error: error instanceof Error ? error.message : '사진을 다운로드하지 못했습니다.' })
  }
}
