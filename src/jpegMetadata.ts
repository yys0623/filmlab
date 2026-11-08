import piexif from 'piexifjs'

function binary(bytes: Uint8Array): string {
  const parts: string[] = []
  for (let i = 0; i < bytes.length; i += 0x8000) parts.push(String.fromCharCode(...bytes.subarray(i, i + 0x8000)))
  return parts.join('')
}

/** Find an EXIF APP1 segment without converting the compressed image to a string. */
function jpegExif(bytes: Uint8Array): string | undefined {
  let at = 2
  while (at + 4 <= bytes.length && bytes[at] === 0xff) {
    const marker = bytes[at + 1]
    if (marker === 0xda || marker === 0xd9) break
    const length = (bytes[at + 2] << 8) | bytes[at + 3]
    if (length < 2 || at + 2 + length > bytes.length) throw new Error('사진의 EXIF 정보를 읽지 못했습니다.')
    if (marker === 0xe1 && length >= 8 && binary(bytes.subarray(at + 4, at + 10)) === 'Exif\0\0') return binary(bytes.subarray(at + 4, at + 2 + length))
    at += 2 + length
  }
}

/** Read EXIF chunks without decoding or retaining the image data. */
function embeddedExif(bytes: Uint8Array): string | undefined {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  const tag = (at: number) => String.fromCharCode(...bytes.subarray(at, at + 4))
  if (bytes.length >= 8 && bytes[0] === 0x89 && tag(1) === 'PNG\r') {
    for (let at = 8; at + 12 <= bytes.length;) {
      const length = view.getUint32(at)
      if (length > bytes.length - at - 12) throw new Error('사진의 EXIF 정보를 읽지 못했습니다.')
      if (tag(at + 4) === 'eXIf') {
        const data = binary(bytes.subarray(at + 8, at + 8 + length))
        return data.startsWith('Exif\0\0') ? data : `Exif\0\0${data}`
      }
      at += length + 12
    }
  } else if (bytes.length >= 12 && tag(0) === 'RIFF' && tag(8) === 'WEBP') {
    for (let at = 12; at + 8 <= bytes.length;) {
      const length = view.getUint32(at + 4, true)
      if (length > bytes.length - at - 8) throw new Error('사진의 EXIF 정보를 읽지 못했습니다.')
      if (tag(at) === 'EXIF') {
        const data = binary(bytes.subarray(at + 8, at + 8 + length))
        return data.startsWith('Exif\0\0') ? data : `Exif\0\0${data}`
      }
      at += 8 + length + (length % 2)
    }
  }
}

/** Preserve supported source EXIF and add the look description. */
export async function addJpegDescription(jpeg: Blob, original: File, description: string): Promise<Blob> {
  const originalBytes = new Uint8Array(await original.arrayBuffer())
  const isJpeg = originalBytes[0] === 0xff && originalBytes[1] === 0xd8
  const sourceExif = isJpeg ? jpegExif(originalBytes) : embeddedExif(originalBytes)
  const exif = sourceExif ? piexif.load(sourceExif) : {}
  const image = exif['0th'] ?? (exif['0th'] = {})
  const previous = image[piexif.ImageIFD.ImageDescription]
  const text = description.replace(/[^\x20-\x7e]/g, '?')
  image[piexif.ImageIFD.ImageDescription] = typeof previous === 'string' && previous ? `${previous}; ${text}` : text
  // The browser has already applied orientation and generated a new image.
  image[piexif.ImageIFD.Orientation] = 1
  delete image[piexif.ImageIFD.ImageWidth]
  delete image[piexif.ImageIFD.ImageLength]
  // Canvas exports sRGB pixels; source profiles and interoperability data may
  // describe a different color space and must not accompany the new image.
  delete image[piexif.ImageIFD.InterColorProfile]
  const photoExif = exif.Exif ?? (exif.Exif = {})
  photoExif[piexif.ExifIFD.ColorSpace] = 1
  delete photoExif[piexif.ExifIFD.PixelXDimension]
  delete photoExif[piexif.ExifIFD.PixelYDimension]
  delete exif.Interop
  delete exif['1st']
  delete exif.thumbnail
  const data = piexif.dump(exif)
  if (data.length + 2 > 0xffff) throw new Error('사진의 EXIF 정보가 너무 큽니다.')
  const segment = new Uint8Array(data.length + 4)
  segment.set([0xff, 0xe1, (data.length + 2) >> 8, (data.length + 2) & 255])
  for (let i = 0; i < data.length; i++) segment[i + 4] = data.charCodeAt(i)
  return new Blob([jpeg.slice(0, 2), segment, jpeg.slice(2)], { type: 'image/jpeg' })
}
