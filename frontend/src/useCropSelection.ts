import { useCallback, useRef, useState } from 'react'
import type { RefObject } from 'react'

import {
	clampCropRect,
	clearStoredCrop,
	getBrowserStorage,
	loadStoredCrop,
	saveStoredCrop,
} from './cropSelection'
import type { CropRect } from './cropSelection'

export function useCropSelection(videoRef: RefObject<HTMLVideoElement | null>) {
	const [crop, setCrop] = useState<CropRect | null>(null)
	const [cropEnabled, setCropEnabled] = useState(false)
	const cropRef = useRef<CropRect | null>(null)

	const prepareForStream = useCallback(() => {
		// 新しい共有元の実解像度を確認するまでは、前の矩形を送信へ適用しない。
		cropRef.current = null
		setCrop(null)
		setCropEnabled(true)
	}, [])

	const disableSelection = useCallback(() => {
		setCropEnabled(false)
	}, [])

	const restoreForVideo = useCallback(() => {
		const video = videoRef.current
		if (!video?.videoWidth || !video.videoHeight) return
		const restored = loadStoredCrop(getBrowserStorage(), {
			width: video.videoWidth,
			height: video.videoHeight,
		})
		cropRef.current = restored
		setCrop(restored)
	}, [videoRef])

	const setCropSelection = useCallback((next: CropRect | null) => {
		const video = videoRef.current
		if (!next) {
			cropRef.current = null
			setCrop(null)
			clearStoredCrop(getBrowserStorage())
			return
		}
		if (!video?.videoWidth || !video.videoHeight) return
		const videoSize = { width: video.videoWidth, height: video.videoHeight }
		const bounded = clampCropRect(next, videoSize)
		if (!bounded) return
		cropRef.current = bounded
		setCrop(bounded)
		saveStoredCrop(getBrowserStorage(), bounded, videoSize)
	}, [videoRef])

	return {
		crop,
		cropEnabled,
		cropRef,
		disableSelection,
		prepareForStream,
		restoreForVideo,
		setCropSelection,
	}
}
