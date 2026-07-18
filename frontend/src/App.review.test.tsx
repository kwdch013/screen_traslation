import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { createStream, installCaptureElementMocks, jsonResponse } from './test/captureMocks'

describe('App PRレビュー回帰', () => {
  beforeEach(() => {
    installCaptureElementMocks()
  })

  it('pagehide後の遅延開始を停止し、pageshowとの競合後に状態を再同期する', async () => {
    let resolveStart: ((response: Response) => void) | undefined
    const pendingStart = new Promise<Response>((resolve) => {
      resolveStart = resolve
    })
    let resolveStop: ((response: Response) => void) | undefined
    const pendingStop = new Promise<Response>((resolve) => {
      resolveStop = resolve
    })
    let statusCalls = 0
    const getDisplayMedia = vi.fn()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia },
    })
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (input === '/api/status') {
        statusCalls += 1
        const state = statusCalls === 1 || statusCalls >= 3 ? 'idle' : 'running'
        return Promise.resolve(jsonResponse({ state }))
      }
      if (input === '/api/control/start') return pendingStart
      if (input === '/api/control/stop') return pendingStop
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: '画面を選択して開始' }))

    fireEvent(window, new Event('pagehide'))
    fireEvent(window, new Event('pageshow'))
    await waitFor(() => expect(statusCalls).toBe(2))
    expect(screen.getByRole('button', { name: '画面を選び直す' })).toBeEnabled()

    resolveStart?.(jsonResponse({ state: 'awaiting_frame', session_token: 'late-token' }))
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith('/api/control/stop', {
        headers: { 'X-Capture-Token': 'late-token' },
        keepalive: true,
        method: 'POST',
      })
    })
    expect(getDisplayMedia).not.toHaveBeenCalled()

    resolveStop?.(jsonResponse({ state: 'idle' }))
    await waitFor(() => expect(statusCalls).toBe(3))
    expect(screen.getByRole('button', { name: '画面を選択して開始' })).toBeEnabled()
  })

  it('アンマウント後に画面選択が完了した場合は取得ストリームを停止する', async () => {
    let resolveSelection: ((stream: MediaStream) => void) | undefined
    const pendingSelection = new Promise<MediaStream>((resolve) => {
      resolveSelection = resolve
    })
    const selected = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockReturnValue(pendingSelection) },
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'owned-token' }))
      .mockResolvedValue(jsonResponse({ state: 'idle' }))
    vi.stubGlobal('fetch', fetchMock)
    const view = render(<App />)
    const startButton = screen.getByRole('button', { name: '画面を選択して開始' })
    await waitFor(() => expect(startButton).toBeEnabled())
    fireEvent.click(startButton)
    await waitFor(() => expect(navigator.mediaDevices.getDisplayMedia).toHaveBeenCalledOnce())

    view.unmount()
    resolveSelection?.(selected.stream)
    await act(async () => {})

    expect(selected.stop).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledWith('/api/control/stop', {
      headers: { 'X-Capture-Token': 'owned-token' },
      keepalive: true,
      method: 'POST',
    })
  })

  it('旧フレームが未解決でも再選択時にabortし新トークンで送信する', async () => {
    vi.useFakeTimers()
    const first = createStream()
    const second = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getDisplayMedia: vi.fn().mockResolvedValueOnce(first.stream).mockResolvedValueOnce(second.stream),
      },
    })
    const pendingFrame = new Promise<Response>(() => undefined)
    const frameRequests: RequestInit[] = []
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/status') return Promise.resolve(jsonResponse({ state: 'idle' }))
      if (input === '/api/control/start') {
        return Promise.resolve(jsonResponse({ state: 'awaiting_frame', session_token: 'old-token' }))
      }
      if (input === '/api/control/reselect') {
        return Promise.resolve(jsonResponse({ state: 'awaiting_frame', session_token: 'new-token' }))
      }
      frameRequests.push(init ?? {})
      return frameRequests.length === 1 ? pendingFrame : Promise.resolve(new Response(null, { status: 204 }))
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '画面を選択して開始' }))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTime(500))

    fireEvent.click(screen.getByRole('button', { name: '画面を選び直す' }))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTime(500))

    expect(frameRequests[0]?.signal).toBeInstanceOf(AbortSignal)
    expect(frameRequests[0]?.signal?.aborted).toBe(true)
    expect(frameRequests).toHaveLength(2)
    expect(frameRequests[1]?.headers).toEqual(
      expect.objectContaining({ 'X-Capture-Token': 'new-token' }),
    )
  })

  it.each([
    ['start', '画面を選択して開始', 'idle'],
    ['stop', '共有を停止', 'awaiting_frame'],
    ['reselect', '画面を選び直す', 'awaiting_frame'],
  ] as const)('%sの409では状態を再同期してボタン整合性を保つ', async (action, label, state) => {
    let statusCalls = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (input === '/api/status') {
        statusCalls += 1
        return Promise.resolve(jsonResponse({ state }))
      }
      if (input === `/api/control/${action}`) {
        return Promise.resolve(jsonResponse({ detail: '状態が競合しました' }, 409))
      }
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    const actionButton = screen.getByRole('button', { name: label })
    await waitFor(() => expect(actionButton).toBeEnabled())
    fireEvent.click(actionButton)

    await waitFor(() => expect(statusCalls).toBe(2))
    const active = state === 'awaiting_frame'
    const startButton = screen.getByRole('button', { name: '画面を選択して開始' })
    const reselectButton = screen.getByRole('button', { name: '画面を選び直す' })
    const stopButton = screen.getByRole('button', { name: '共有を停止' })
    if (active) {
      expect(startButton).toBeDisabled()
      expect(reselectButton).toBeEnabled()
      expect(stopButton).toBeEnabled()
    } else {
      expect(startButton).toBeEnabled()
      expect(reselectButton).toBeDisabled()
      expect(stopButton).toBeDisabled()
    }
  })

  it('初期statusのerror状態は通信失敗ではなくサービスエラーとして表示する', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(jsonResponse({ state: 'error', error_message: 'モデル初期化失敗' })),
    )

    render(<App />)

    expect(await screen.findByRole('status')).toHaveTextContent('モデル初期化失敗')
    expect(screen.getByRole('status')).not.toHaveTextContent('状態を取得できませんでした')
    expect(screen.getByRole('button', { name: '画面を選択して開始' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '画面を選び直す' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '共有を停止' })).toBeEnabled()
  })
})
