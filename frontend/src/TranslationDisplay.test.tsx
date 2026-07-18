import { act, fireEvent, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { RESULT_TTL_MS, SUBTITLE_HISTORY_LIMIT } from './useTranslationEvents'
import { createStream, installCaptureElementMocks, jsonResponse } from './test/captureMocks'
import { currentEventSource } from './test/eventSourceMock'

const availableRegion = {
	source: 'New Game',
	translated: 'ニューゲーム',
	x: 192,
	y: 108,
	width: 384,
	height: 216,
	confidence: 0.9,
	positioning: 'available',
}

function resultEvent(frameId: number, regions: object[], generation = 1) {
	return {
		generation,
		frame_id: frameId,
		captured_at: 10,
		processed_at: 11,
		frame_width: 1920,
		frame_height: 1080,
		regions,
	}
}

describe('翻訳表示UI', () => {
	beforeEach(() => {
		installCaptureElementMocks()
		Object.defineProperty(HTMLVideoElement.prototype, 'clientWidth', {
			configurable: true,
			value: 1000,
		})
		Object.defineProperty(HTMLVideoElement.prototype, 'clientHeight', {
			configurable: true,
			value: 800,
		})
		vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ state: 'idle' })))
	})

	it('SSE結果を重畳し、位置情報なしの訳文はプレビュー下部へ表示する', async () => {
		render(<App />)
		const events = currentEventSource()

		act(() => {
			events.emitJson('state', { generation: 1, state: 'running', error_message: null })
			events.emitJson('translation_result', resultEvent(1, [
				availableRegion,
				{ ...availableRegion, source: 'Continue', translated: '続ける', positioning: 'unavailable' },
			]))
		})

		const overlay = screen.getByTestId('translation-overlay')
		expect(overlay).toHaveTextContent('ニューゲーム')
		expect(overlay).toHaveStyle({ left: '100px', top: '175px', width: '200px', minHeight: '112.5px' })
		expect(screen.getByLabelText('位置情報のない翻訳')).toHaveTextContent('続ける')
		expect(screen.getByLabelText('位置情報のない翻訳')).not.toHaveTextContent('ニューゲーム')
	})

	it('字幕タブへ原文と訳文を新しい順に表示し、切替後も同じSSE購読を維持する', async () => {
		render(<App />)
		const events = currentEventSource()
		act(() => events.emitJson('translation_result', resultEvent(1, [availableRegion])))

		await userEvent.click(screen.getByRole('tab', { name: '字幕リスト' }))

		expect(screen.getByText('New Game')).toBeInTheDocument()
		expect(within(screen.getByRole('list')).getByText('ニューゲーム')).toBeInTheDocument()
		expect(events.close).not.toHaveBeenCalled()
		expect(events.url).toBe('/api/events')
		expect(screen.getByRole('list')).toHaveTextContent('New Gameニューゲーム')
	})

	it('空regionsでは現在表示だけを消去し、字幕履歴は維持する', async () => {
		render(<App />)
		const events = currentEventSource()
		act(() => events.emitJson('translation_result', resultEvent(1, [availableRegion])))
		act(() => events.emitJson('translation_result', resultEvent(2, [])))

		expect(screen.queryByTestId('translation-overlay')).not.toBeInTheDocument()
		await userEvent.click(screen.getByRole('tab', { name: '字幕リスト' }))
		expect(screen.getByText('ニューゲーム')).toBeInTheDocument()
	})

	it('プレビュー寸法とイベントのフレーム解像度変更時に座標を再計算する', () => {
		let previewWidth = 1000
		let previewHeight = 800
		Object.defineProperty(HTMLVideoElement.prototype, 'clientWidth', {
			configurable: true,
			get: () => previewWidth,
		})
		Object.defineProperty(HTMLVideoElement.prototype, 'clientHeight', {
			configurable: true,
			get: () => previewHeight,
		})
		render(<App />)
		const events = currentEventSource()
		act(() => events.emitJson('translation_result', resultEvent(1, [availableRegion])))
		const video = screen.getByLabelText('共有画面のプレビュー')

		previewWidth = 500
		previewHeight = 500
		fireEvent.resize(video)
		expect(screen.getByTestId('translation-overlay')).toHaveStyle({ left: '50px', top: '137.5px' })

		act(() => events.emitJson('translation_result', {
			...resultEvent(2, [availableRegion]),
			frame_width: 1000,
			frame_height: 1000,
		}))
		expect(screen.getByTestId('translation-overlay')).toHaveStyle({ left: '96px', top: '54px' })
	})

	it('TTL経過後は古い現在表示を消し、字幕履歴は維持する', async () => {
		vi.useFakeTimers()
		render(<App />)
		const events = currentEventSource()
		act(() => events.emitJson('translation_result', resultEvent(1, [availableRegion])))

		act(() => vi.advanceTimersByTime(RESULT_TTL_MS))

		expect(screen.queryByTestId('translation-overlay')).not.toBeInTheDocument()
		fireEvent.click(screen.getByRole('tab', { name: '字幕リスト' }))
		expect(screen.getByText('ニューゲーム')).toBeInTheDocument()
	})

	it('古い重複フレームを無視しても現行結果のTTLを維持する', () => {
		vi.useFakeTimers()
		render(<App />)
		const events = currentEventSource()
		act(() => events.emitJson('translation_result', resultEvent(2, [availableRegion])))
		act(() => vi.advanceTimersByTime(RESULT_TTL_MS / 2))

		act(() => events.emitJson('translation_result', resultEvent(1, [availableRegion])))
		act(() => vi.advanceTimersByTime(RESULT_TTL_MS / 2))

		expect(screen.queryByTestId('translation-overlay')).not.toBeInTheDocument()
	})

	it('世代変更と停止・再選択操作で旧世代の重畳と字幕履歴を消去する', async () => {
		render(<App />)
		const events = currentEventSource()
		act(() => events.emitJson('translation_result', resultEvent(1, [availableRegion])))
		act(() => events.emitJson('state', { generation: 2, state: 'awaiting_frame', error_message: null }))

		expect(screen.queryByTestId('translation-overlay')).not.toBeInTheDocument()
		await userEvent.click(screen.getByRole('tab', { name: '字幕リスト' }))
		expect(screen.queryByText('ニューゲーム')).not.toBeInTheDocument()
	})

	it.each(['共有を停止', '画面を選び直す'])('%sの開始時点で旧世代の表示を消去する', async (label) => {
		const { stream } = createStream()
		Object.defineProperty(navigator, 'mediaDevices', {
			configurable: true,
			value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
		})
		vi.stubGlobal('fetch', vi.fn()
			.mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'old-token' }))
			.mockResolvedValue(jsonResponse({
				state: label === '共有を停止' ? 'idle' : 'awaiting_frame',
				session_token: 'next-token',
			})))
		render(<App />)
		const events = currentEventSource()
		act(() => events.emitJson('translation_result', resultEvent(1, [availableRegion])))
		await act(async () => {})

		fireEvent.click(screen.getByRole('button', { name: label }))
		act(() => events.emitJson('translation_result', resultEvent(2, [availableRegion])))

		expect(screen.queryByTestId('translation-overlay')).not.toBeInTheDocument()
		fireEvent.click(screen.getByRole('tab', { name: '字幕リスト' }))
		expect(screen.queryByText('ニューゲーム')).not.toBeInTheDocument()
	})

	it('切断時に再接続中を表示し、EventSourceの自動再接続後に復旧表示する', () => {
		render(<App />)
		const events = currentEventSource()

		act(() => events.emitError())
		expect(screen.getByText('翻訳結果を再接続中です。')).toBeInTheDocument()

		act(() => events.emitOpen())
		expect(screen.queryByText('翻訳結果を再接続中です。')).not.toBeInTheDocument()
	})

	it('字幕履歴の上限を超えたとき古い項目を破棄する', async () => {
		render(<App />)
		const events = currentEventSource()
		act(() => {
			for (let frameId = 1; frameId <= SUBTITLE_HISTORY_LIMIT + 1; frameId += 1) {
				events.emitJson('translation_result', resultEvent(frameId, [{
					...availableRegion,
					source: `Source ${frameId}`,
					translated: `訳文 ${frameId}`,
				}]))
			}
		})
		await userEvent.click(screen.getByRole('tab', { name: '字幕リスト' }))

		expect(screen.getAllByRole('listitem')).toHaveLength(SUBTITLE_HISTORY_LIMIT)
		expect(screen.queryByText('訳文 1')).not.toBeInTheDocument()
		expect(screen.getAllByRole('listitem')[0]).toHaveTextContent(`訳文 ${SUBTITLE_HISTORY_LIMIT + 1}`)
	})
})
