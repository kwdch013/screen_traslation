export type Positioning = 'available' | 'unavailable'

export interface TranslationRegion {
	source: string
	translated: string
	x: number
	y: number
	width: number
	height: number
	confidence: number
	positioning: Positioning
}

export interface TranslationResult {
	generation: number
	frame_id: number
	captured_at: number
	processed_at: number
	frame_width: number
	frame_height: number
	crop_revision: string | null
	regions: TranslationRegion[]
}

export interface TranslationStateEvent {
	generation: number
	state: string
	error_message: string | null
}

export interface SubtitleEntry extends TranslationRegion {
	id: string
	generation: number
	frameId: number
}

export function parseTranslationResult(data: string): TranslationResult | null {
	const value = parseJson(data)
	if (!isRecord(value) || !Array.isArray(value.regions)) return null
	if (
		!isNonNegativeInteger(value.generation)
		|| !isNonNegativeInteger(value.frame_id)
		|| !isFiniteNumber(value.captured_at)
		|| !isFiniteNumber(value.processed_at)
		|| !isPositiveInteger(value.frame_width)
		|| !isPositiveInteger(value.frame_height)
		|| !(value.crop_revision === null || typeof value.crop_revision === 'string')
	) return null
	const regions = value.regions.map(parseRegion)
	if (regions.some((region) => region === null)) return null
	return {
		generation: value.generation,
		frame_id: value.frame_id,
		captured_at: value.captured_at,
		processed_at: value.processed_at,
		frame_width: value.frame_width,
		frame_height: value.frame_height,
		crop_revision: value.crop_revision,
		regions: regions as TranslationRegion[],
	}
}

export function parseTranslationState(data: string): TranslationStateEvent | null {
	const value = parseJson(data)
	if (
		!isRecord(value)
		|| !isNonNegativeInteger(value.generation)
		|| typeof value.state !== 'string'
		|| !(value.error_message === null || typeof value.error_message === 'string')
	) return null
	return {
		generation: value.generation,
		state: value.state,
		error_message: value.error_message,
	}
}

function parseRegion(value: unknown): TranslationRegion | null {
	if (
		!isRecord(value)
		|| typeof value.source !== 'string'
		|| typeof value.translated !== 'string'
		|| !isFiniteNumber(value.x)
		|| !isFiniteNumber(value.y)
		|| !isFiniteNumber(value.width)
		|| !isFiniteNumber(value.height)
		|| !isFiniteNumber(value.confidence)
		|| (value.positioning !== 'available' && value.positioning !== 'unavailable')
	) return null
	return value as unknown as TranslationRegion
}

function parseJson(data: string): unknown {
	try {
		return JSON.parse(data)
	} catch {
		return null
	}
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return value !== null && typeof value === 'object'
}

function isFiniteNumber(value: unknown): value is number {
	return typeof value === 'number' && Number.isFinite(value)
}

function isNonNegativeInteger(value: unknown): value is number {
	return isFiniteNumber(value) && Number.isInteger(value) && value >= 0
}

function isPositiveInteger(value: unknown): value is number {
	return isFiniteNumber(value) && Number.isInteger(value) && value > 0
}
