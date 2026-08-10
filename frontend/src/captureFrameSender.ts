import { clampCropRect } from './cropSelection'
import type { CropRect } from './cropSelection'

interface ActiveFrameSend {
  controller: AbortController
  generation: number
}

export class CaptureFrameSender {
  private active: ActiveFrameSend | null = null
  private generation = 0

  reset(): void {
    this.generation += 1
    this.active?.controller.abort()
    this.active = null
  }

  async send(
    video: HTMLVideoElement | null,
    canvas: HTMLCanvasElement,
    token: string | undefined,
    onForbidden: () => void,
    crop?: CropRect | null,
  ): Promise<void> {
    const generation = this.generation
    if (
      this.active?.generation === generation ||
      !video ||
      !token ||
      !video.videoWidth ||
      !video.videoHeight
    ) {
      return
    }
    const controller = new AbortController()
    this.active = { controller, generation }
    try {
      const boundedCrop = crop
        ? clampCropRect(crop, { width: video.videoWidth, height: video.videoHeight })
        : null
      canvas.width = boundedCrop?.width ?? video.videoWidth
      canvas.height = boundedCrop?.height ?? video.videoHeight
      const context = canvas.getContext('2d')
      if (!context) return
      if (boundedCrop) {
        context.drawImage(
          video,
          boundedCrop.x,
          boundedCrop.y,
          boundedCrop.width,
          boundedCrop.height,
          0,
          0,
          boundedCrop.width,
          boundedCrop.height,
        )
      } else {
        context.drawImage(video, 0, 0, canvas.width, canvas.height)
      }
      const blob = await canvasToJpeg(canvas)
      if (!blob || controller.signal.aborted || this.generation !== generation) return
      const response = await fetch('/frame', {
        method: 'POST',
        headers: {
          'Content-Type': 'image/jpeg',
          'X-Capture-Token': token,
        },
        body: blob,
        signal: controller.signal,
      })
      if (response.status === 403 && this.generation === generation) {
        onForbidden()
      }
    } catch {
      // 一時的な送信失敗は次のフレームで回復できるため、共有自体は維持する。
    } finally {
      if (this.active?.controller === controller) {
        this.active = null
      }
    }
  }
}

function canvasToJpeg(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.8))
}
