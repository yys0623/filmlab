import { test } from 'node:test'
import assert from 'node:assert/strict'
import piexif from 'piexifjs'
import { addJpegDescription } from '../src/jpegMetadata.ts'

const jpeg = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD3+iiigD//2Q==', 'base64')
const metadata = piexif.dump({ '0th': { [piexif.ImageIFD.Make]: 'Test Camera', [piexif.ImageIFD.Orientation]: 6, [piexif.ImageIFD.InterColorProfile]: 'source profile' }, Exif: { [piexif.ExifIFD.DateTimeOriginal]: '2020:01:01 10:00:00', [piexif.ExifIFD.ColorSpace]: 65535 }, Interop: { [piexif.InteropIFD.InteroperabilityIndex]: 'R03' } })
const exif = Buffer.from(metadata, 'latin1')
function png() {
  const data = exif.subarray(6), header = Buffer.alloc(8), crc = Buffer.alloc(4)
  header.writeUInt32BE(data.length); header.write('eXIf', 4)
  return Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]), header, data, crc])
}
function webp() {
  const header = Buffer.alloc(20); header.write('RIFF'); header.writeUInt32LE(12 + exif.length + exif.length % 2, 4); header.write('WEBP', 8); header.write('EXIF', 12); header.writeUInt32LE(exif.length, 16)
  return Buffer.concat([header, exif, Buffer.alloc(exif.length % 2)])
}
for (const [name, data] of [['JPEG', Buffer.from(piexif.insert(metadata, jpeg.toString('latin1')), 'latin1')], ['PNG', png()], ['WebP', webp()]] as const) {
  test(`${name} EXIF survives JPEG export with corrected orientation`, async () => {
    const result = await addJpegDescription(new Blob([jpeg]), new File([data], 'photo'), 'Film: Test; Paper: Test')
    const read = piexif.load(Buffer.from(await result.arrayBuffer()).toString('latin1'))
    assert.equal(read['0th']![piexif.ImageIFD.Make], 'Test Camera')
    assert.equal(read['0th']![piexif.ImageIFD.Orientation], 1)
    assert.equal(read['0th']![piexif.ImageIFD.ImageDescription], 'Film: Test; Paper: Test')
    assert.equal(read.Exif![piexif.ExifIFD.DateTimeOriginal], '2020:01:01 10:00:00')
    assert.equal(read.Exif![piexif.ExifIFD.ColorSpace], 1)
    assert.equal(read['0th']![piexif.ImageIFD.InterColorProfile], undefined)
    assert.deepEqual(read.Interop, {})
  })
}
