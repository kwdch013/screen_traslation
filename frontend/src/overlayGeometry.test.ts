import { describe, expect, it } from 'vitest'

import { calculateContainTransform, mapRegionToPreview, offsetRegion } from './overlayGeometry'

describe('プレビュー座標変換', () => {
	it('上下にletterboxがあるプレビューへ画像座標を変換する', () => {
		const transform = calculateContainTransform(
			{ width: 1920, height: 1080 },
			{ width: 1000, height: 800 },
		)
		if (!transform) throw new Error('座標変換を作成できませんでした')

		expect(transform).toEqual({ scale: 1000 / 1920, offsetX: 0, offsetY: 118.75 })
		expect(
			mapRegionToPreview({ x: 192, y: 108, width: 384, height: 216 }, transform),
		).toEqual({ left: 100, top: 175, width: 200, height: 112.5 })
	})

	it('左右にletterboxがあるプレビューへ画像座標を変換する', () => {
		const transform = calculateContainTransform(
			{ width: 800, height: 1200 },
			{ width: 1000, height: 600 },
		)
		if (!transform) throw new Error('座標変換を作成できませんでした')

		expect(transform).toEqual({ scale: 0.5, offsetX: 300, offsetY: 0 })
		expect(mapRegionToPreview({ x: 20, y: 40, width: 100, height: 80 }, transform)).toEqual({
			left: 310,
			top: 20,
			width: 50,
			height: 40,
		})
	})

	it('画像またはプレビューの寸法が不正なら変換不能を返す', () => {
		expect(calculateContainTransform({ width: 0, height: 1080 }, { width: 1000, height: 800 })).toBeNull()
		expect(calculateContainTransform({ width: 1920, height: 1080 }, { width: 0, height: 800 })).toBeNull()
	})

	it('クロップ画像基準の領域へ元動画の左上オフセットを加算する', () => {
		expect(offsetRegion(
			{ x: 12, y: 34, width: 200, height: 80 },
			{ x: 320, y: 180 },
		)).toEqual({ x: 332, y: 214, width: 200, height: 80 })
	})
})
