import { useState } from 'react'
import type { PointerEvent, RefObject } from 'react'

import { previewSelectionToCrop } from './cropSelection'
import type { CropRect } from './cropSelection'
import { mapRegionToPreview } from './overlayGeometry'
import type { ContainTransform, PreviewRect, RegionRect } from './overlayGeometry'

interface CropOverlayProps {
	videoRef: RefObject<HTMLVideoElement | null>
	transform: ContainTransform | null
	crop: CropRect | null
	enabled: boolean
	onChange: (crop: CropRect | null) => void
}

interface DragState {
	pointerId: number
	startX: number
	startY: number
	currentX: number
	currentY: number
}

export function CropOverlay({ videoRef, transform, crop, enabled, onChange }: CropOverlayProps) {
	const [drag, setDrag] = useState<DragState | null>(null)

	const startDrag = (event: PointerEvent<HTMLDivElement>) => {
		const point = eventPoint(event, videoRef)
		if (!enabled || !transform || !point) return
		event.preventDefault()
		event.currentTarget.setPointerCapture?.(event.pointerId)
		setDrag({
			pointerId: event.pointerId,
			startX: point.x,
			startY: point.y,
			currentX: point.x,
			currentY: point.y,
		})
	}

	const moveDrag = (event: PointerEvent<HTMLDivElement>) => {
		if (!drag || event.pointerId !== drag.pointerId) return
		const point = eventPoint(event, videoRef)
		if (!point) return
		setDrag({ ...drag, currentX: point.x, currentY: point.y })
	}

	const finishDrag = (event: PointerEvent<HTMLDivElement>) => {
		if (!drag || event.pointerId !== drag.pointerId) return
		const point = eventPoint(event, videoRef)
		setDrag(null)
		const video = videoRef.current
		if (!point || !video || !transform) return
		onChange(previewSelectionToCrop(
			normalizeDrag({ ...drag, currentX: point.x, currentY: point.y }),
			transform,
			{ width: video.videoWidth, height: video.videoHeight },
		))
	}

	const selectedRect = transform && crop ? mapRegionToPreview(crop, transform) : null
	const dragSelection = drag ? normalizeDrag(drag) : null
	const dragRect = dragSelection ? {
		left: dragSelection.x,
		top: dragSelection.y,
		width: dragSelection.width,
		height: dragSelection.height,
	} : null
	return (
		<div
			className={`crop-selection-layer${enabled ? ' is-enabled' : ''}`}
			aria-label="翻訳対象領域を選択"
			aria-disabled={!enabled}
			onPointerDown={startDrag}
			onPointerMove={moveDrag}
			onPointerUp={finishDrag}
			onPointerCancel={() => setDrag(null)}
		>
			{selectedRect && <SelectionRect rect={selectedRect} testId="crop-selection" />}
			{dragRect && <SelectionRect rect={dragRect} testId="crop-selection-draft" />}
		</div>
	)
}

function SelectionRect({ rect, testId }: { rect: PreviewRect; testId: string }) {
	return (
		<div
			className="crop-selection-rect"
			data-testid={testId}
			style={{ left: rect.left, top: rect.top, width: rect.width, height: rect.height }}
		/>
	)
}

function eventPoint(
	event: PointerEvent<HTMLDivElement>,
	videoRef: RefObject<HTMLVideoElement | null>,
): { x: number; y: number } | null {
	const video = videoRef.current
	if (!video) return null
	const bounds = video.getBoundingClientRect()
	return {
		x: event.clientX - bounds.left - video.clientLeft,
		y: event.clientY - bounds.top - video.clientTop,
	}
}

function normalizeDrag(drag: DragState): RegionRect {
	const left = Math.min(drag.startX, drag.currentX)
	const top = Math.min(drag.startY, drag.currentY)
	return {
		x: left,
		y: top,
		width: Math.abs(drag.currentX - drag.startX),
		height: Math.abs(drag.currentY - drag.startY),
	}
}
