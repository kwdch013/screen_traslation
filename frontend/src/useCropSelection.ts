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
	const [cropRevision, setCropRevision] = useState('0')
	const cropRef = useRef<CropRect | null>(null)
	const cropRevisionCounterRef = useRef(0)
	const cropRevisionRef = useRef('0')
	const sourceLabelRef = useRef('')
	const observedVideoSizeRef = useRef<{ width: number; height: number } | null>(null)
	const advanceCropRevision = useCallback(() => {
		cropRevisionCounterRef.current += 1
		const nextRevision = String(cropRevisionCounterRef.current)
		cropRevisionRef.current = nextRevision
		setCropRevision(nextRevision)
	}, [])

	const prepareForStream = useCallback((sourceLabel = '') => {
		// 新しい共有元の実解像度を確認するまでは、前の矩形を送信へ適用しない。
		cropRef.current = null
		sourceLabelRef.current = sourceLabel
		observedVideoSizeRef.current = null
		setCrop(null)
		setCropEnabled(true)
		advanceCropRevision()
	}, [advanceCropRevision])

	const disableSelection = useCallback(() => {
		setCropEnabled(false)
	}, [])

	const clearSelection = useCallback(() => {
		cropRef.current = null
		setCrop(null)
		clearStoredCrop(getBrowserStorage())
		advanceCropRevision()
	}, [advanceCropRevision])

	const restoreForVideo = useCallback(() => {
		const video = videoRef.current
		if (!video?.videoWidth || !video.videoHeight) return
		const videoSize = {
			width: video.videoWidth,
			height: video.videoHeight,
		}
		observedVideoSizeRef.current = videoSize
		const restored = loadStoredCrop(getBrowserStorage(), videoSize, sourceLabelRef.current)
		if (cropRectsEqual(cropRef.current, restored)) return
		cropRef.current = restored
		setCrop(restored)
		advanceCropRevision()
	}, [advanceCropRevision, videoRef])

	const handleVideoResize = useCallback((): boolean => {
		const video = videoRef.current
		if (!video?.videoWidth || !video.videoHeight) return false
		const currentSize = { width: video.videoWidth, height: video.videoHeight }
		const previousSize = observedVideoSizeRef.current
		observedVideoSizeRef.current = currentSize
		if (!previousSize) return false
		if (previousSize.width === currentSize.width && previousSize.height === currentSize.height) {
			return false
		}
		clearSelection()
		return true
	}, [clearSelection, videoRef])

	const setCropSelection = useCallback((next: CropRect | null) => {
		const video = videoRef.current
		if (!next) {
			clearSelection()
			return
		}
		if (!video?.videoWidth || !video.videoHeight) return
		const videoSize = { width: video.videoWidth, height: video.videoHeight }
		const bounded = clampCropRect(next, videoSize)
		if (!bounded) return
		cropRef.current = bounded
		setCrop(bounded)
		saveStoredCrop(getBrowserStorage(), bounded, videoSize, sourceLabelRef.current)
		advanceCropRevision()
	}, [advanceCropRevision, clearSelection, videoRef])

	return {
		crop,
		cropEnabled,
		cropRef,
		cropRevision,
		cropRevisionRef,
		disableSelection,
		handleVideoResize,
		prepareForStream,
		restoreForVideo,
		setCropSelection,
	}
}

function cropRectsEqual(first: CropRect | null, second: CropRect | null): boolean {
	if (first === second) return true
	if (!first || !second) return false
	return first.x === second.x
		&& first.y === second.y
		&& first.width === second.width
		&& first.height === second.height
}
