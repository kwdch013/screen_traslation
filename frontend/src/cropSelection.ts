import type { ContainTransform, RegionRect, Size } from './overlayGeometry'

export type CropRect = RegionRect

export const CROP_STORAGE_KEY = 'screen-translation.crop-selection.v1'
export const MIN_CROP_SIZE = 10

interface StoredCrop {
	crop: CropRect
	videoWidth: number
	videoHeight: number
	sourceLabel?: string
}

export function clampCropRect(crop: CropRect, video: Size): CropRect | null {
	if (!isValidSize(video) || !isFiniteRect(crop)) return null
	const left = clamp(Math.floor(Math.min(crop.x, crop.x + crop.width)), 0, video.width)
	const top = clamp(Math.floor(Math.min(crop.y, crop.y + crop.height)), 0, video.height)
	const right = clamp(Math.ceil(Math.max(crop.x, crop.x + crop.width)), 0, video.width)
	const bottom = clamp(Math.ceil(Math.max(crop.y, crop.y + crop.height)), 0, video.height)
	if (right <= left || bottom <= top) return null
	return { x: left, y: top, width: right - left, height: bottom - top }
}

export function previewSelectionToCrop(
	selection: RegionRect,
	transform: ContainTransform,
	video: Size,
): CropRect | null {
	if (!Number.isFinite(transform.scale) || transform.scale <= 0 || !isFiniteRect(selection)) {
		return null
	}
	const crop = clampCropRect({
		x: (selection.x - transform.offsetX) / transform.scale,
		y: (selection.y - transform.offsetY) / transform.scale,
		width: selection.width / transform.scale,
		height: selection.height / transform.scale,
	}, video)
	if (!crop || crop.width < MIN_CROP_SIZE || crop.height < MIN_CROP_SIZE) return null
	return crop
}

export function saveStoredCrop(
	storage: Storage | null,
	crop: CropRect,
	video: Size,
	sourceLabel = '',
): void {
	const bounded = clampCropRect(crop, video)
	if (!storage || !bounded) return
	const stored: StoredCrop = {
		crop: bounded,
		videoWidth: video.width,
		videoHeight: video.height,
		sourceLabel,
	}
	try {
		storage.setItem(CROP_STORAGE_KEY, JSON.stringify(stored))
	} catch {
		// 保存不能でも現在の共有セッションではクロップを継続できる。
	}
}

export function loadStoredCrop(storage: Storage | null, video: Size, sourceLabel = ''): CropRect | null {
	if (!storage || !isValidSize(video)) return null
	try {
		const raw = storage.getItem(CROP_STORAGE_KEY)
		if (!raw) return null
		const stored: unknown = JSON.parse(raw)
		if (!isStoredCrop(stored)) return null
		if (stored.videoWidth !== video.width || stored.videoHeight !== video.height) return null
		if (!sourceLabel || !stored.sourceLabel || stored.sourceLabel !== sourceLabel) return null
		return clampCropRect(stored.crop, video)
	} catch {
		return null
	}
}

export function clearStoredCrop(storage: Storage | null): void {
	if (!storage) return
	try {
		storage.removeItem(CROP_STORAGE_KEY)
	} catch {
		// ストレージ障害でクロップ解除そのものを失敗させない。
	}
}

export function getBrowserStorage(): Storage | null {
	try {
		return window.localStorage
	} catch {
		return null
	}
}

function isStoredCrop(value: unknown): value is StoredCrop {
	if (!value || typeof value !== 'object') return false
	const candidate = value as Partial<StoredCrop>
	return Number.isFinite(candidate.videoWidth)
		&& Number.isFinite(candidate.videoHeight)
		&& (candidate.sourceLabel === undefined || typeof candidate.sourceLabel === 'string')
		&& Boolean(candidate.crop)
		&& isFiniteRect(candidate.crop as CropRect)
}

function isFiniteRect(rect: RegionRect): boolean {
	return [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite)
}

function isValidSize(size: Size): boolean {
	return Number.isFinite(size.width) && size.width > 0
		&& Number.isFinite(size.height) && size.height > 0
}

function clamp(value: number, min: number, max: number): number {
	return Math.min(Math.max(value, min), max)
}
