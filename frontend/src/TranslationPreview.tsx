import { useCallback, useLayoutEffect, useState } from 'react'
import type { RefObject } from 'react'

import { calculateContainTransform, mapRegionToPreview } from './overlayGeometry'
import type { ContainTransform } from './overlayGeometry'
import type { TranslationResult } from './translationEvents'

interface TranslationPreviewProps {
	videoRef: RefObject<HTMLVideoElement | null>
	result: TranslationResult | null
}

export function TranslationPreview({ videoRef, result }: TranslationPreviewProps) {
	const [transform, setTransform] = useState<ContainTransform | null>(null)
	const recalculate = useCallback(() => {
		const video = videoRef.current
		if (!video || !result) {
			setTransform(null)
			return
		}
		setTransform(calculateContainTransform(
			{ width: result.frame_width, height: result.frame_height },
			{ width: video.clientWidth, height: video.clientHeight },
		))
	}, [result, videoRef])

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

	const positioned = result?.regions.filter((region) => region.positioning === 'available') ?? []
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
					onLoadedMetadata={recalculate}
					onResize={recalculate}
				/>
				<div className="translation-overlay-layer" aria-hidden={positioned.length === 0}>
					{transform && positioned.map((region, index) => {
						const rect = mapRegionToPreview(region, transform)
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
