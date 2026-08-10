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

function installRunningCapture(sourceLabel = '') {
	const capture = installCaptureElementMocks()
	installPreviewBounds()
	const { stream } = createStream(sourceLabel)
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

function dragCrop(start: { x: number; y: number }, end: { x: number; y: number }): void {
	const selector = screen.getByLabelText('翻訳対象領域を選択')
	fireEvent.pointerDown(selector, { clientX: start.x, clientY: start.y, pointerId: 1 })
	fireEvent.pointerMove(selector, { clientX: end.x, clientY: end.y, pointerId: 1 })
	fireEvent.pointerUp(selector, { clientX: end.x, clientY: end.y, pointerId: 1 })
}

function latestCropRevision(fetchMock: ReturnType<typeof vi.fn>): string {
	const calls = fetchMock.mock.calls as unknown as [RequestInfo | URL, RequestInit][]
	const frameCall = calls.findLast(([input]) => input === '/frame')
	const headers = frameCall?.[1].headers as Record<string, string> | undefined
	const revision = headers?.['X-Crop-Revision']
	if (!revision) throw new Error('クロップリビジョン付きのフレーム送信が見つかりません')
	return revision
}

function emitCropResult(
	frameId: number,
	width: number,
	height: number,
	translated: string,
	cropRevision: string,
): void {
	act(() => currentEventSource().emitJson('translation_result', {
		generation: 1,
		frame_id: frameId,
		captured_at: 10,
		processed_at: 11,
		frame_width: width,
		frame_height: height,
		crop_revision: cropRevision,
		regions: [{
			source: `Source ${frameId}`,
			translated,
			x: 0,
			y: 0,
			width: Math.max(1, width / 2),
			height: Math.max(1, height / 2),
			confidence: 0.9,
			positioning: 'available',
		}],
	}))
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

	it('選択範囲を解除するとリビジョンを進めて動画全体の送信へ戻り、保存値も削除する', async () => {
		const { drawImage, encodedSizes, fetchMock } = installRunningCapture()
		const video = await startAndLoadMetadata()
		selectCrop()
		await act(async () => vi.advanceTimersByTime(500))
		const selectedRevision = latestCropRevision(fetchMock)

		fireEvent.click(screen.getByRole('button', { name: '選択範囲を解除' }))
		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 0, 0, 1280, 720)
		expect(encodedSizes.at(-1)).toEqual(videoSize)
		expect(latestCropRevision(fetchMock)).not.toBe(selectedRevision)
		expect(localStorage).toHaveLength(0)
	})

	it('クロップオフセットを加算して元映像上へ翻訳領域を重畳する', async () => {
		const { fetchMock } = installRunningCapture()
		await startAndLoadMetadata()
		selectCrop()
		await act(async () => vi.advanceTimersByTime(500))

		act(() => currentEventSource().emitJson('translation_result', {
			generation: 1,
			frame_id: 1,
			captured_at: 10,
			processed_at: 11,
			frame_width: 256,
			frame_height: 144,
			crop_revision: latestCropRevision(fetchMock),
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

	it('同じ寸法で位置だけ異なるクロップへの変更後は旧リビジョンの結果を誤位置に重畳しない', async () => {
		const { fetchMock } = installRunningCapture()
		await startAndLoadMetadata()
		selectCrop()
		await act(async () => vi.advanceTimersByTime(500))
		const previousRevision = latestCropRevision(fetchMock)
		emitCropResult(1, 256, 144, '変更前の訳文', previousRevision)

		expect(screen.getByTestId('translation-overlay')).toHaveTextContent('変更前の訳文')
		dragCrop({ x: 400, y: 300 }, { x: 600, y: 412.5 })
		expect(screen.queryByTestId('translation-overlay')).not.toBeInTheDocument()

		fireEvent.click(screen.getByRole('tab', { name: '字幕リスト' }))
		expect(screen.getByText('変更前の訳文')).toBeInTheDocument()
		fireEvent.click(screen.getByRole('tab', { name: 'プレビュー' }))

		emitCropResult(2, 256, 144, '遅延した旧訳文', previousRevision)
		expect(screen.queryByTestId('translation-overlay')).not.toBeInTheDocument()

		await act(async () => vi.advanceTimersByTime(500))
		const currentRevision = latestCropRevision(fetchMock)
		expect(currentRevision).not.toBe(previousRevision)
		emitCropResult(3, 256, 144, '変更後の訳文', currentRevision)
		expect(screen.getByTestId('translation-overlay')).toHaveTextContent('変更後の訳文')
	})

	it.each([
		['極小ドラッグ', { x: 400, y: 300 }, { x: 405, y: 305 }],
		['letterbox外へのドラッグ', { x: 100, y: 10 }, { x: 300, y: 100 }],
		['単純クリック', { x: 400, y: 300 }, { x: 400, y: 300 }],
	] as const)('%sでは既存のクロップ選択を維持する', async (_name, start, end) => {
		installRunningCapture()
		await startAndLoadMetadata()
		selectCrop()

		dragCrop(start, end)

		expect(screen.getByTestId('crop-selection')).toBeInTheDocument()
		expect(screen.getByRole('button', { name: '選択範囲を解除' })).toBeEnabled()
		expect(localStorage).toHaveLength(1)
	})

	it('共有中に動画実解像度が変化した場合はリビジョンを進めてクロップを解除する', async () => {
		const { drawImage, encodedSizes, fetchMock } = installRunningCapture()
		let width = 1280
		let height = 720
		Object.defineProperty(HTMLVideoElement.prototype, 'videoWidth', {
			configurable: true,
			get: () => width,
		})
		Object.defineProperty(HTMLVideoElement.prototype, 'videoHeight', {
			configurable: true,
			get: () => height,
		})
		const video = await startAndLoadMetadata()
		selectCrop()
		await act(async () => vi.advanceTimersByTime(500))
		const selectedRevision = latestCropRevision(fetchMock)

		width = 640
		height = 360
		fireEvent.resize(video)
		await act(async () => vi.advanceTimersByTime(500))

		expect(screen.queryByTestId('crop-selection')).not.toBeInTheDocument()
		expect(screen.getByRole('button', { name: '選択範囲を解除' })).toBeDisabled()
		expect(localStorage).toHaveLength(0)
		expect(drawImage).toHaveBeenLastCalledWith(video, 0, 0, 640, 360)
		expect(encodedSizes.at(-1)).toEqual({ width: 640, height: 360 })
		expect(latestCropRevision(fetchMock)).not.toBe(selectedRevision)
	})

	it('次回共有のメタデータ読込後に同じラベルと解像度の保存領域を復元する', async () => {
		saveStoredCrop(localStorage, { x: 128, y: 72, width: 256, height: 144 }, videoSize, '共有元A')
		const { drawImage, encodedSizes } = installRunningCapture('共有元A')
		const video = await startAndLoadMetadata()

		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 128, 72, 256, 144, 0, 0, 256, 144)
		expect(encodedSizes.at(-1)).toEqual({ width: 256, height: 144 })
		expect(screen.getByTestId('crop-selection')).toBeInTheDocument()
	})

	it('共有元ラベルを取得できない場合は同じ解像度でも保存領域を復元しない', async () => {
		saveStoredCrop(localStorage, { x: 128, y: 72, width: 256, height: 144 }, videoSize, '共有元A')
		const { drawImage, encodedSizes } = installRunningCapture('')
		const video = await startAndLoadMetadata()

		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 0, 0, 1280, 720)
		expect(encodedSizes.at(-1)).toEqual(videoSize)
		expect(screen.queryByTestId('crop-selection')).not.toBeInTheDocument()
	})

	it('同じ解像度でも共有元ラベルが異なる場合は保存領域を復元しない', async () => {
		saveStoredCrop(
			localStorage,
			{ x: 128, y: 72, width: 256, height: 144 },
			videoSize,
			'共有元A',
		)
		const { drawImage, encodedSizes } = installRunningCapture('共有元B')
		const video = await startAndLoadMetadata()

		await act(async () => vi.advanceTimersByTime(500))

		expect(drawImage).toHaveBeenLastCalledWith(video, 0, 0, 1280, 720)
		expect(encodedSizes.at(-1)).toEqual(videoSize)
		expect(screen.queryByTestId('crop-selection')).not.toBeInTheDocument()
	})

	it('保存時と動画実解像度が異なる場合は復元せず全体を送信する', async () => {
		saveStoredCrop(localStorage, { x: 128, y: 72, width: 256, height: 144 }, videoSize, '共有元A')
		const { drawImage, encodedSizes } = installRunningCapture('共有元A')
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
