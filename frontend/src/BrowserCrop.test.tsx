import { act, fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { saveStoredCrop } from './cropSelection'
import { createStream, installCaptureElementMocks, jsonResponse } from './test/captureMocks'
import { currentEventSource } from './test/eventSourceMock'

const videoSize = { width: 1280, height: 720 }

function installPreviewBounds(): void {
	Object.defineProperty(HTMLVideoElement.prototype, 'clientWidth', {
		configurable: true,
		value: 1000,
	})
	Object.defineProperty(HTMLVideoElement.prototype, 'clientHeight', {
		configurable: true,
		value: 800,
	})
	vi.spyOn(HTMLVideoElement.prototype, 'getBoundingClientRect').mockReturnValue({
		bottom: 800,
		height: 800,
		left: 0,
		right: 1000,
		top: 0,
		width: 1000,
		x: 0,
		y: 0,
		toJSON: () => ({}),
	})
}

function installRunningCapture() {
	const capture = installCaptureElementMocks()
	installPreviewBounds()
	const { stream } = createStream()
	Object.defineProperty(navigator, 'mediaDevices', {
		configurable: true,
		value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
	})
	const fetchMock = vi.fn((input: RequestInfo | URL) => {
		if (input === '/api/status') return Promise.resolve(jsonResponse({ state: 'idle' }))
		if (input === '/api/control/start') {
			return Promise.resolve(jsonResponse({ state: 'awaiting_frame', session_token: 'crop-token' }))
		}
		if (input === '/frame') return Promise.resolve(new Response(null, { status: 204 }))
		throw new Error(`想定外のリクエスト: ${String(input)}`)
	})
	vi.stubGlobal('fetch', fetchMock)
	return { ...capture, fetchMock }
}

async function startAndLoadMetadata(): Promise<HTMLVideoElement> {
	render(<App />)
	await act(async () => {})
	fireEvent.click(screen.getByRole('button', { name: '画面を選択して開始' }))
	await act(async () => {})
	const video = screen.getByLabelText('共有画面のプレビュー') as HTMLVideoElement
	fireEvent.loadedMetadata(video)
	return video
}

function selectCrop(): void {
	const selector = screen.getByLabelText('翻訳対象領域を選択')
	fireEvent.pointerDown(selector, { clientX: 100, clientY: 175, pointerId: 1 })
	fireEvent.pointerMove(selector, { clientX: 300, clientY: 287.5, pointerId: 1 })
	fireEvent.pointerUp(selector, { clientX: 300, clientY: 287.5, pointerId: 1 })
}

describe('ブラウザ内クロップ', () => {
	beforeEach(() => {
		vi.useFakeTimers()
		localStorage.clear()
	})

	it('領域選択後はクロップ矩形の寸法でJPEGを生成して送信する', async () => {
		const { drawImage, encodedSizes } = installRunningCapture()
		const video = await startAndLoadMetadata()

		selectCrop()
		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 128, 72, 256, 144, 0, 0, 256, 144)
		expect(encodedSizes.at(-1)).toEqual({ width: 256, height: 144 })
		expect(screen.getByRole('button', { name: '選択範囲を解除' })).toBeEnabled()
	})

	it('選択範囲を解除すると動画全体の送信へ戻り、保存値も削除する', async () => {
		const { drawImage, encodedSizes } = installRunningCapture()
		const video = await startAndLoadMetadata()
		selectCrop()
		await act(async () => vi.advanceTimersByTime(500))

		fireEvent.click(screen.getByRole('button', { name: '選択範囲を解除' }))
		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 0, 0, 1280, 720)
		expect(encodedSizes.at(-1)).toEqual(videoSize)
		expect(localStorage).toHaveLength(0)
	})

	it('クロップオフセットを加算して元映像上へ翻訳領域を重畳する', async () => {
		installRunningCapture()
		await startAndLoadMetadata()
		selectCrop()

		act(() => currentEventSource().emitJson('translation_result', {
			generation: 1,
			frame_id: 1,
			captured_at: 10,
			processed_at: 11,
			frame_width: 256,
			frame_height: 144,
			regions: [{
				source: 'Crop text',
				translated: 'クロップ訳文',
				x: 0,
				y: 0,
				width: 128,
				height: 72,
				confidence: 0.9,
				positioning: 'available',
			}],
		}))

		expect(screen.getByTestId('translation-overlay')).toHaveStyle({
			left: '100px',
			top: '175px',
			width: '100px',
			minHeight: '56.25px',
		})
	})

	it('次回共有のメタデータ読込後に同じ解像度の保存領域を復元する', async () => {
		saveStoredCrop(localStorage, { x: 128, y: 72, width: 256, height: 144 }, videoSize)
		const { drawImage, encodedSizes } = installRunningCapture()
		const video = await startAndLoadMetadata()

		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 128, 72, 256, 144, 0, 0, 256, 144)
		expect(encodedSizes.at(-1)).toEqual({ width: 256, height: 144 })
		expect(screen.getByTestId('crop-selection')).toBeInTheDocument()
	})

	it('保存時と動画実解像度が異なる場合は復元せず全体を送信する', async () => {
		saveStoredCrop(localStorage, { x: 128, y: 72, width: 256, height: 144 }, videoSize)
		const { drawImage, encodedSizes } = installRunningCapture()
		Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', {
			configurable: true,
			value: 1920,
		})
		Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', {
			configurable: true,
			value: 1080,
		})
		const video = await startAndLoadMetadata()

		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 0, 0, 1920, 1080)
		expect(encodedSizes.at(-1)).toEqual({ width: 1920, height: 1080 })
		expect(screen.queryByTestId('crop-selection')).not.toBeInTheDocument()
	})
})
