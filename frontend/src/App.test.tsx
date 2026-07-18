import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { createStream, installCaptureElementMocks, jsonResponse } from './test/captureMocks'

describe('App', () => {
  beforeEach(() => {
    installCaptureElementMocks()
  })

  it('初期状態を同期し、3つのタブの骨組みを表示する', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({ state: 'idle' })))

    render(<App />)

    expect(await screen.findByRole('button', { name: '画面を選択して開始' })).toBeEnabled()
    expect(screen.getByRole('tab', { name: 'プレビュー' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '字幕リスト' })).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: '設定' })).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith('/api/status')
  })

  it('設定タブを初めて開いたときに設定と辞書を読み込む', async () => {
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (input === '/api/status') return Promise.resolve(jsonResponse({ state: 'idle' }))
      if (input === '/api/config') {
        return Promise.resolve(jsonResponse({
          ocr_fps: 5,
          min_confidence: 0.45,
          ocr_backend: 'tesseract',
          ocr_fallback_min_confidence: 0.65,
          translator_backend: 'argos',
          llm_model: '',
          llm_timeout_seconds: 120,
          source_language: 'en',
          target_language: 'ja',
          target_scope: 'ui_all',
          external_api_policy: 'local_first_free_only',
          priority_order: ['gpu_speed', 'latency'],
          overlay_style: {
            font_size: 28,
            text_color: '#ffffff',
            background_color: '#000000',
            overlay_opacity: 0.72,
          },
        }))
      }
      if (input === '/api/glossary') return Promise.resolve(jsonResponse([]))
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)

    expect(fetchMock).not.toHaveBeenCalledWith('/api/config')
    fireEvent.click(screen.getByRole('tab', { name: '設定' }))

    expect(await screen.findByRole('spinbutton', { name: 'OCR FPS' })).toHaveValue(5)
    expect(fetchMock).toHaveBeenCalledWith('/api/config')
    expect(fetchMock).toHaveBeenCalledWith('/api/glossary')
  })

  it('開始応答のトークンで500msごとにJPEGフレームを送る', async () => {
    vi.useFakeTimers()
    const { stream } = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'start-token' }))
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await act(async () => {})

    fireEvent.click(screen.getByRole('button', { name: '画面を選択して開始' }))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTime(500))

    expect(navigator.mediaDevices.getDisplayMedia).toHaveBeenCalledWith({
      audio: false,
      video: { frameRate: 5 },
    })
    expect(fetchMock).toHaveBeenCalledWith('/frame', {
      body: expect.any(Blob),
      headers: {
        'Content-Type': 'image/jpeg',
        'X-Capture-Token': 'start-token',
      },
      method: 'POST',
      signal: expect.any(AbortSignal),
    })
  })

  it('前のフレーム送信中は次の送信を開始しない', async () => {
    vi.useFakeTimers()
    const { stream } = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    let resolveFrame: ((response: Response) => void) | undefined
    const pendingFrame = new Promise<Response>((resolve) => {
      resolveFrame = resolve
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'token' }))
      .mockReturnValue(pendingFrame)
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '画面を選択して開始' }))
    await act(async () => {})

    await act(async () => vi.advanceTimersByTime(1_500))

    expect(fetchMock.mock.calls.filter(([path]) => path === '/frame')).toHaveLength(1)
    resolveFrame?.(new Response(null, { status: 204 }))
  })

  it('再選択応答でセッショントークンを更新する', async () => {
    vi.useFakeTimers()
    const first = createStream()
    const second = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getDisplayMedia: vi.fn().mockResolvedValueOnce(first.stream).mockResolvedValueOnce(second.stream),
      },
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'first-token' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'second-token' }))
      .mockResolvedValue(new Response(null, { status: 204 }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '画面を選択して開始' }))
    await act(async () => {})

    fireEvent.click(screen.getByRole('button', { name: '画面を選び直す' }))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTime(500))

    expect(first.stop).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledWith(
      '/frame',
      expect.objectContaining({
        headers: expect.objectContaining({ 'X-Capture-Token': 'second-token' }),
      }),
    )
  })

  it('再選択前の送信に対する遅延403で新しい共有を停止しない', async () => {
    vi.useFakeTimers()
    const first = createStream()
    const second = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getDisplayMedia: vi.fn().mockResolvedValueOnce(first.stream).mockResolvedValueOnce(second.stream),
      },
    })
    let resolveOldFrame: ((response: Response) => void) | undefined
    const oldFrame = new Promise<Response>((resolve) => {
      resolveOldFrame = resolve
    })
    let controlCount = 0
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      if (input === '/api/status') return Promise.resolve(jsonResponse({ state: 'idle' }))
      if (input === '/api/control/start') {
        controlCount += 1
        return Promise.resolve(jsonResponse({ state: 'awaiting_frame', session_token: 'old-token' }))
      }
      if (input === '/api/control/reselect') {
        controlCount += 1
        return Promise.resolve(jsonResponse({ state: 'awaiting_frame', session_token: 'new-token' }))
      }
      return oldFrame
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '画面を選択して開始' }))
    await act(async () => {})
    await act(async () => vi.advanceTimersByTime(500))
    fireEvent.click(screen.getByRole('button', { name: '画面を選び直す' }))
    await act(async () => {})

    resolveOldFrame?.(new Response(null, { status: 403 }))
    await act(async () => {})

    expect(controlCount).toBe(2)
    expect(first.stop).toHaveBeenCalledOnce()
    expect(second.stop).not.toHaveBeenCalled()
  })

  it('フレーム送信が403なら共有を停止する', async () => {
    vi.useFakeTimers()
    const { stream, stop } = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
        .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'token' }))
        .mockResolvedValueOnce(new Response(null, { status: 403 })),
    )
    render(<App />)
    await act(async () => {})
    fireEvent.click(screen.getByRole('button', { name: '画面を選択して開始' }))
    await act(async () => {})

    await act(async () => vi.advanceTimersByTime(500))

    expect(stop).toHaveBeenCalledOnce()
    expect(screen.getByRole('status')).toHaveTextContent('セッションは終了しました')
  })

  it('pagehideで現行トークンを付けてkeepalive停止する', async () => {
    const { stream } = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'page-token' }))
      .mockResolvedValue(jsonResponse({ state: 'idle' }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: '画面を選択して開始' }))
    await waitFor(() => expect(navigator.mediaDevices.getDisplayMedia).toHaveBeenCalledOnce())

    fireEvent(window, new Event('pagehide'))

    expect(fetchMock).toHaveBeenCalledWith('/api/control/stop', {
      headers: { 'X-Capture-Token': 'page-token' },
      keepalive: true,
      method: 'POST',
    })
  })

  it('セッションを所有していないタブのpagehideでは停止要求を送らない', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ state: 'idle' }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await screen.findByRole('button', { name: '画面を選択して開始' })

    fireEvent(window, new Event('pagehide'))

    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/control/stop')).toHaveLength(0)
  })

  it('操作中は全ボタンを無効化し、開始を多重実行しない', async () => {
    let resolveStart: ((response: Response) => void) | undefined
    const pendingStart = new Promise<Response>((resolve) => {
      resolveStart = resolve
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockReturnValue(pendingStart)
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    const start = await screen.findByRole('button', { name: '画面を選択して開始' })

    fireEvent.click(start)
    fireEvent.click(start)

    expect(screen.getByRole('button', { name: '画面を選択して開始' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '画面を選び直す' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '共有を停止' })).toBeDisabled()
    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/control/start')).toHaveLength(1)
    resolveStart?.(jsonResponse({ state: 'error', error_message: '起動失敗' }, 500))
  })

  it('制御APIのerror状態では停止だけを有効にして詳細を表示する', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'error', error_message: 'パイプライン異常' }, 500))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: '画面を選択して開始' }))

    expect(await screen.findByRole('status')).toHaveTextContent('パイプライン異常')
    expect(screen.getByRole('button', { name: '画面を選択して開始' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '画面を選び直す' })).toBeDisabled()
    expect(screen.getByRole('button', { name: '共有を停止' })).toBeEnabled()
  })

  it('starting状態を200ms後に再同期する', async () => {
    vi.useFakeTimers()
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'starting' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await act(async () => {})

    expect(screen.getByRole('button', { name: '画面を選択して開始' })).toBeDisabled()
    await act(async () => vi.advanceTimersByTime(200))

    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/status')).toHaveLength(2)
    expect(screen.getByRole('button', { name: '画面を選択して開始' })).toBeEnabled()
  })
})
