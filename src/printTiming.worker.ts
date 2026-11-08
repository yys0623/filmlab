import { bakeTimingCube, serializeCube, type TimingPack } from './printTiming'
import type { Cube } from './lut'

self.onmessage = (event: MessageEvent<{ id: number; pack: TimingPack; adapter?: Cube; m: number; y: number; output?: { tag: 'STD' | 'VLOG'; title: string; comment: string } }>) => {
  const { id, pack, adapter, m, y, output } = event.data
  try {
    const cube = bakeTimingCube(pack, m, y, adapter)
    if (output) self.postMessage({ id, text: serializeCube(cube, output.tag, output.title, output.comment) })
    else self.postMessage({ id, cube }, { transfer: [cube.table.buffer] })
  } catch (error) {
    self.postMessage({ id, error: error instanceof Error ? error.message : '인화 필터 데이터를 처리하지 못했습니다.' })
  }
}
