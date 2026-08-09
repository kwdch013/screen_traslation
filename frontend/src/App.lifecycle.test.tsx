import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App'
import { createStream, installCaptureElementMocks, jsonResponse } from './test/captureMocks'

describe('App lifecycle', () => {
  beforeEach(() => {
    installCaptureElementMocks()
  })

  it('pageshowでサーバー状態を再同期する', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ state: 'idle' }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await screen.findByRole('button', { name: '画面を選択して開始' })

    fireEvent(window, new Event('pageshow'))

    await waitFor(() => {
      expect(fetchMock.mock.calls.filter(([path]) => path === '/api/status')).toHaveLength(2)
    })
  })

  it('停止ボタンで共有と現行セッションを停止する', async () => {
    const { stream, stop } = createStream()
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getDisplayMedia: vi.fn().mockResolvedValue(stream) },
    })
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'awaiting_frame', session_token: 'stop-token' }))
      .mockResolvedValueOnce(jsonResponse({ state: 'idle' }))
    vi.stubGlobal('fetch', fetchMock)
    render(<App />)
    await userEvent.click(await screen.findByRole('button', { name: '画面を選択して開始' }))
    await userEvent.click(screen.getByRole('button', { name: '共有を停止' }))

    expect(stop).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledWith('/api/control/stop', {
      headers: { 'X-Capture-Token': 'stop-token' },
      method: 'POST',
    })
    expect(screen.getByRole('button', { name: '画面を選択して開始' })).toBeEnabled()
  })
})
