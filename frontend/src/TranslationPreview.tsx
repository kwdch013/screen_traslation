import { useCallback, useLayoutEffect, useState } from 'react'
import type { RefObject } from 'react'

import { CropOverlay } from './CropOverlay'
import type { CropRect } from './cropSelection'
import { calculateContainTransform, mapRegionToPreview, offsetRegion } from './overlayGeometry'
import type { ContainTransform } from './overlayGeometry'
import type { TranslationResult } from './translationEvents'

interface TranslationPreviewProps {
	videoRef: RefObject<HTMLVideoElement | null>
	result: TranslationResult | null
	crop: CropRect | null
	cropRevision: string
	cropEnabled: boolean
	onCropChange: (crop: CropRect | null) => void
	onVideoMetadata: () => void
	onVideoResize: () => void
}

export function TranslationPreview({
	videoRef,
	result,
	crop,
	cropRevision,
	cropEnabled,
	onCropChange,
	onVideoMetadata,
	onVideoResize,
}: TranslationPreviewProps) {
	const [transform, setTransform] = useState<ContainTransform | null>(null)
	const recalculate = useCallback(() => {
		const video = videoRef.current
		if (!video?.videoWidth || !video.videoHeight) {
			setTransform(null)
			return
		}
		setTransform(calculateContainTransform(
			{ width: video.videoWidth, height: video.videoHeight },
			{ width: video.clientWidth, height: video.clientHeight },
		))
	}, [videoRef])

	useLayoutEffect(() => {
		recalculate()
		const video = videoRef.current
		if (!video) return
		if (typeof ResizeObserver === 'undefined') {
			window.addEventListener('resize', recalculate)
			return () => window.removeEventListener('resize', recalculate)
		}
		const observer = new ResizeObserver(recalculate)
		observer.observe(video)
		return () => observer.disconnect()
	}, [recalculate, videoRef])

	const resultMatchesCurrentCrop = Boolean(
		result && result.crop_revision === cropRevision,
	)
	const positioned = resultMatchesCurrentCrop
		? result?.regions.filter((region) => region.positioning === 'available') ?? []
		: []
	const unpositioned = result?.regions.filter((region) => region.positioning === 'unavailable') ?? []

	return (
		<>
			<div className="preview-stage">
				<video
					ref={videoRef}
					autoPlay
					muted
					playsInline
					aria-label="共有画面のプレビュー"
					onLoadedMetadata={() => {
						onVideoMetadata()
						recalculate()
					}}
					onResize={() => {
						onVideoResize()
						recalculate()
					}}
				/>
				<div className="translation-overlay-layer" aria-hidden={positioned.length === 0}>
					{transform && positioned.map((region, index) => {
						const sourceRegion = crop ? offsetRegion(region, crop) : region
						const rect = mapRegionToPreview(sourceRegion, transform)
						return (
							<div
								key={`${result?.generation}-${result?.frame_id}-${index}`}
								className="translation-overlay"
								data-testid="translation-overlay"
								style={{
									left: rect.left,
									top: rect.top,
									width: rect.width,
									minHeight: rect.height,
								}}
							>
								{region.translated}
							</div>
						)
					})}
				</div>
				<CropOverlay
					videoRef={videoRef}
					transform={transform}
					crop={crop}
					enabled={cropEnabled}
					onChange={onCropChange}
				/>
			</div>
			<div className="crop-controls">
				<p>共有中のプレビューをドラッグすると、翻訳対象を1領域に限定できます。</p>
				<button type="button" className="secondary" onClick={() => onCropChange(null)} disabled={!crop}>
					選択範囲を解除
				</button>
			</div>
			{unpositioned.length > 0 && (
				<div className="unpositioned-translations" aria-label="位置情報のない翻訳">
					{unpositioned.map((region, index) => (
						<p key={`${result?.generation}-${result?.frame_id}-${index}`}>{region.translated}</p>
					))}
				</div>
			)}
		</>
	)
}
