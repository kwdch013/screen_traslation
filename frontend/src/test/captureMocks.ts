import { vi } from 'vitest'

export function jsonResponse(body: object, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

export function createStream() {
  const stop = vi.fn()
  const addEventListener = vi.fn()
  const track = { addEventListener, stop }
  return {
    addEventListener,
    stop,
    stream: {
      getTracks: () => [track],
      getVideoTracks: () => [track],
    } as unknown as MediaStream,
  }
}

export function installCaptureElementMocks(): {
  drawImage: ReturnType<typeof vi.fn>
  encodedSizes: { width: number; height: number }[]
} {
  const drawImage = vi.fn()
  const encodedSizes: { width: number; height: number }[] = []
  Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
    configurable: true,
    value: vi.fn(() => ({ drawImage })),
  })
  Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', {
    configurable: true,
    value: vi.fn(function (this: HTMLCanvasElement, callback: BlobCallback) {
      encodedSizes.push({ width: this.width, height: this.height })
      callback(new Blob(['jpeg'], { type: 'image/jpeg' }))
    }),
  })
  Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', {
    configurable: true,
    value: 1280,
  })
  Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', {
    configurable: true,
    value: 720,
  })
  return { drawImage, encodedSizes }
}
