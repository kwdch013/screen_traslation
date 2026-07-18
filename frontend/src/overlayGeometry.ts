export interface Size {
	width: number
	height: number
}

export interface RegionRect {
	x: number
	y: number
	width: number
	height: number
}

export interface ContainTransform {
	scale: number
	offsetX: number
	offsetY: number
}

export interface PreviewRect {
	left: number
	top: number
	width: number
	height: number
}

export function calculateContainTransform(
	frame: Size,
	preview: Size,
): ContainTransform | null {
	if (![frame.width, frame.height, preview.width, preview.height].every(isPositiveFinite)) {
		return null
	}
	const scale = Math.min(preview.width / frame.width, preview.height / frame.height)
	return {
		scale,
		offsetX: normalizePixel((preview.width - frame.width * scale) / 2),
		offsetY: normalizePixel((preview.height - frame.height * scale) / 2),
	}
}

export function mapRegionToPreview(
	region: RegionRect,
	transform: ContainTransform,
): PreviewRect {
	return {
		left: normalizePixel(transform.offsetX + region.x * transform.scale),
		top: normalizePixel(transform.offsetY + region.y * transform.scale),
		width: normalizePixel(region.width * transform.scale),
		height: normalizePixel(region.height * transform.scale),
	}
}

function isPositiveFinite(value: number): boolean {
	return Number.isFinite(value) && value > 0
}

function normalizePixel(value: number): number {
	const rounded = Math.round(value * 1_000_000) / 1_000_000
	return Object.is(rounded, -0) ? 0 : rounded
}
