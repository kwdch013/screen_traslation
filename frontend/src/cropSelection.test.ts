import { beforeEach, describe, expect, it } from 'vitest'

import {
	CROP_STORAGE_KEY,
	clampCropRect,
	clearStoredCrop,
	loadStoredCrop,
	previewSelectionToCrop,
	saveStoredCrop,
} from './cropSelection'
import { calculateContainTransform } from './overlayGeometry'

const videoSize = { width: 1280, height: 720 }

describe('クロップ座標', () => {
	it('letterboxを除いた表示座標を動画実解像度の整数矩形へ変換する', () => {
		const transform = calculateContainTransform(videoSize, { width: 1000, height: 800 })
		if (!transform) throw new Error('座標変換を作成できませんでした')

		expect(previewSelectionToCrop(
			{ x: 100, y: 175, width: 200, height: 112.5 },
			transform,
			videoSize,
		)).toEqual({ x: 128, y: 72, width: 256, height: 144 })
	})

	it('表示上の選択がletterboxや動画外へはみ出しても動画範囲へクランプする', () => {
		const transform = calculateContainTransform(videoSize, { width: 1000, height: 800 })
		if (!transform) throw new Error('座標変換を作成できませんでした')

		expect(previewSelectionToCrop(
			{ x: -50, y: 50, width: 1100, height: 700 },
			transform,
			videoSize,
		)).toEqual({ x: 0, y: 0, width: 1280, height: 720 })
		expect(clampCropRect(
			{ x: -10, y: 20, width: 100, height: 800 },
			videoSize,
		)).toEqual({ x: 0, y: 20, width: 90, height: 700 })
	})

	it('動画実解像度で10px四方未満の選択を無視する', () => {
		const transform = calculateContainTransform(videoSize, { width: 1280, height: 720 })
		if (!transform) throw new Error('座標変換を作成できませんでした')

		expect(previewSelectionToCrop(
			{ x: 100, y: 100, width: 9, height: 20 },
			transform,
			videoSize,
		)).toBeNull()
	})
})

describe('クロップ設定の永続化', () => {
	beforeEach(() => localStorage.clear())

	it('同じ動画実解像度かつ同じ共有元ラベルなら保存したクロップ矩形を復元する', () => {
		const crop = { x: 128, y: 72, width: 256, height: 144 }
		saveStoredCrop(localStorage, crop, videoSize, '共有元A')

		expect(loadStoredCrop(localStorage, videoSize, '共有元A')).toEqual(crop)
	})

	it('同じ動画実解像度でも共有元ラベルが異なる場合は復元しない', () => {
		saveStoredCrop(
			localStorage,
			{ x: 128, y: 72, width: 256, height: 144 },
			videoSize,
			'共有元A',
		)

		expect(loadStoredCrop(localStorage, videoSize, '共有元B')).toBeNull()
	})

	it('共有元ラベルを取得できない場合は動画実解像度だけで復元する', () => {
		const crop = { x: 128, y: 72, width: 256, height: 144 }
		saveStoredCrop(localStorage, crop, videoSize, '共有元A')

		expect(loadStoredCrop(localStorage, videoSize, '')).toEqual(crop)
	})

	it('動画実解像度が保存時と異なる場合は復元しない', () => {
		saveStoredCrop(localStorage, { x: 128, y: 72, width: 256, height: 144 }, videoSize)

		expect(loadStoredCrop(localStorage, { width: 1920, height: 1080 })).toBeNull()
	})

	it('解除時は保存したクロップ設定を削除する', () => {
		saveStoredCrop(localStorage, { x: 128, y: 72, width: 256, height: 144 }, videoSize)
		clearStoredCrop(localStorage)

		expect(localStorage.getItem(CROP_STORAGE_KEY)).toBeNull()
	})
})
