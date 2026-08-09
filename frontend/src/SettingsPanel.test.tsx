import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import { SettingsPanel } from './SettingsPanel'
import { jsonResponse } from './test/captureMocks'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

const config = {
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
  priority_order: ['gpu_speed', 'latency', 'translation_quality', 'implementation_speed'],
  overlay_style: {
    font_size: 28,
    text_color: '#ffffff',
    background_color: '#000000',
    overlay_opacity: 0.72,
  },
}

function installInitialFetch(glossary: { source: string; target: string }[] = []) {
  const fetchMock = vi.fn((input: RequestInfo | URL, _init?: RequestInit) => {
    if (input === '/api/config') return Promise.resolve(jsonResponse(config))
    if (input === '/api/glossary') return Promise.resolve(jsonResponse(glossary))
    throw new Error(`想定外のリクエスト: ${String(input)}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('SettingsPanel', () => {
  it('APIの公開設定と辞書一覧を表示する', async () => {
    installInitialFetch([{ source: 'Save', target: 'セーブ' }])

    render(<SettingsPanel />)

    expect(await screen.findByRole('spinbutton', { name: 'OCR FPS' })).toHaveValue(5)
    expect(screen.getByRole('spinbutton', { name: '最小信頼度' })).toHaveValue(0.45)
    expect(screen.getByRole('spinbutton', { name: 'オーバーレイ透明度' })).toHaveValue(0.72)
    expect(screen.getByRole('combobox', { name: 'OCR方式' })).toHaveValue('tesseract')
    const glossary = screen.getByRole('region', { name: '辞書' })
    expect(within(glossary).getByText('Save')).toBeInTheDocument()
    expect(within(glossary).getByText('セーブ')).toBeInTheDocument()
  })

  it('数値範囲をクライアントで検証し、入力値を保持する', async () => {
    const user = userEvent.setup()
    const fetchMock = installInitialFetch()
    render(<SettingsPanel />)
    const fps = await screen.findByRole('spinbutton', { name: 'OCR FPS' })

    await user.clear(fps)
    await user.type(fps, '0')
    await user.click(screen.getByRole('button', { name: '設定を保存' }))

    expect(screen.getByRole('alert')).toHaveTextContent('OCR FPSは0より大きい値を入力してください。')
    expect(fps).toHaveValue(0)
    expect(fetchMock.mock.calls.filter(([path]) => path === '/api/config')).toHaveLength(1)
  })

  it('設定保存の400エラーを表示し、編集中の値を失わない', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config' && init?.method === 'PUT') {
        return Promise.resolve(jsonResponse({ detail: '設定の組み合わせが不正です。' }, 400))
      }
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary') return Promise.resolve(jsonResponse([]))
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)
    const model = await screen.findByRole('textbox', { name: 'LLMモデル' })

    await user.type(model, 'local-model')
    await user.selectOptions(screen.getByRole('combobox', { name: 'OCR方式' }), 'llm')
    await user.click(screen.getByRole('button', { name: '設定を保存' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('設定の組み合わせが不正です。')
    expect(model).toHaveValue('local-model')
    expect(screen.getByRole('combobox', { name: 'OCR方式' })).toHaveValue('llm')
  })

  it('設定保存後に再取得し、次回開始から反映されることを表示する', async () => {
    const user = userEvent.setup()
    let configGets = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config' && init?.method === 'PUT') {
        return Promise.resolve(jsonResponse({ ...config, ocr_fps: 2.5, applied: 'next_start' }))
      }
      if (input === '/api/config') {
        configGets += 1
        return Promise.resolve(jsonResponse({ ...config, ocr_fps: configGets === 1 ? 5 : 2.5 }))
      }
      if (input === '/api/glossary') return Promise.resolve(jsonResponse([]))
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)
    const fps = await screen.findByRole('spinbutton', { name: 'OCR FPS' })

    await user.clear(fps)
    await user.type(fps, '2.5')
    await user.click(screen.getByRole('button', { name: '設定を保存' }))

    expect(await screen.findByRole('status')).toHaveTextContent('次回開始から反映')
    await waitFor(() => expect(fps).toHaveValue(2.5))
    expect(configGets).toBe(2)
  })

  it('設定保存の応答待ち中は入力欄を無効化し、編集値の上書きを防ぐ', async () => {
    const user = userEvent.setup()
    const saveResponse = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config' && init?.method === 'PUT') return saveResponse.promise
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary') return Promise.resolve(jsonResponse([]))
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)
    const model = await screen.findByRole('textbox', { name: 'LLMモデル' })

    await user.type(model, 'local-model')
    await user.click(screen.getByRole('button', { name: '設定を保存' }))

    await waitFor(() => expect(model).toBeDisabled())
    await user.type(model, '-編集中')
    expect(model).toHaveValue('local-model')

    saveResponse.resolve(jsonResponse({ ...config, llm_model: 'local-model', applied: 'next_start' }))
    await waitFor(() => expect(model).not.toBeDisabled())
  })

  it('辞書の空文字と重複エラーを表示し、入力値を保持する', async () => {
    const user = userEvent.setup()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ detail: '用語は既に登録されています: Save' }, 409))
      }
      if (input === '/api/glossary') return Promise.resolve(jsonResponse([]))
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)
    await screen.findByRole('spinbutton', { name: 'OCR FPS' })

    await user.click(screen.getByRole('button', { name: '用語を登録' }))
    expect(screen.getByRole('alert')).toHaveTextContent('原文と訳文を入力してください。')

    await user.type(screen.getByRole('textbox', { name: '原文' }), 'Save')
    await user.type(screen.getByRole('textbox', { name: '訳文' }), 'セーブ')
    await user.click(screen.getByRole('button', { name: '用語を登録' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('用語は既に登録されています: Save')
    expect(screen.getByRole('textbox', { name: '原文' })).toHaveValue('Save')
    expect(screen.getByRole('textbox', { name: '訳文' })).toHaveValue('セーブ')
  })

  it.each(['.', '..'])('削除不能になる原文「%s」の登録エラーをUIに表示する', async (sourceValue) => {
    const user = userEvent.setup()
    const fetchMock = installInitialFetch()
    render(<SettingsPanel />)

    await user.type(await screen.findByRole('textbox', { name: '原文' }), sourceValue)
    await user.type(screen.getByRole('textbox', { name: '訳文' }), '訳')
    await user.click(screen.getByRole('button', { name: '用語を登録' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('原文に「.」または「..」は登録できません。')
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)
  })

  it('辞書登録後に一覧を再取得して入力欄を空にする', async () => {
    const user = userEvent.setup()
    let glossaryGets = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ source: 'Save', target: 'セーブ' }, 201))
      }
      if (input === '/api/glossary') {
        glossaryGets += 1
        const terms = glossaryGets === 1 ? [] : [{ source: 'Save', target: 'セーブ' }]
        return Promise.resolve(jsonResponse(terms))
      }
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)
    await screen.findByRole('spinbutton', { name: 'OCR FPS' })

    await user.type(screen.getByRole('textbox', { name: '原文' }), 'Save')
    await user.type(screen.getByRole('textbox', { name: '訳文' }), 'セーブ')
    await user.click(screen.getByRole('button', { name: '用語を登録' }))

    expect(await screen.findByText('セーブ')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '原文' })).toHaveValue('')
    expect(screen.getByRole('textbox', { name: '訳文' })).toHaveValue('')
    expect(glossaryGets).toBe(2)
  })

  it('辞書登録の応答待ち中は入力欄を無効化し、編集値のクリアを防ぐ', async () => {
    const user = userEvent.setup()
    const registerResponse = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary' && init?.method === 'POST') return registerResponse.promise
      if (input === '/api/glossary') return Promise.resolve(jsonResponse([{ source: 'Save', target: 'セーブ' }]))
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)
    const source = await screen.findByRole('textbox', { name: '原文' })
    const target = screen.getByRole('textbox', { name: '訳文' })

    await user.type(source, 'Load')
    await user.type(target, 'ロード')
    await user.click(screen.getByRole('button', { name: '用語を登録' }))

    await waitFor(() => expect(source).toBeDisabled())
    await user.type(source, ' now')
    expect(source).toHaveValue('Load')

    registerResponse.resolve(jsonResponse({ source: 'Load', target: 'ロード' }, 201))
    await waitFor(() => expect(source).not.toBeDisabled())
    expect(source).toHaveValue('')
  })

  it('登録成功後の一覧再取得失敗を区別し、暫定一覧から再試行できる', async () => {
    const user = userEvent.setup()
    let glossaryGets = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ source: 'Save', target: 'セーブ' }, 201))
      }
      if (input === '/api/glossary') {
        glossaryGets += 1
        if (glossaryGets === 1) return Promise.resolve(jsonResponse([]))
        if (glossaryGets === 2) return Promise.resolve(jsonResponse({ detail: '一時的な取得失敗' }, 500))
        return Promise.resolve(jsonResponse([{ source: 'Save', target: 'セーブ' }]))
      }
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)

    await user.type(await screen.findByRole('textbox', { name: '原文' }), 'Save')
    await user.type(screen.getByRole('textbox', { name: '訳文' }), 'セーブ')
    await user.click(screen.getByRole('button', { name: '用語を登録' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('登録済みですが、一覧の再取得に失敗しました。')
    expect(screen.getByText('セーブ')).toBeInTheDocument()
    expect(screen.getByRole('textbox', { name: '原文' })).toHaveValue('')
    await user.click(screen.getByRole('button', { name: '一覧を再取得' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(glossaryGets).toBe(3)
  })

  it('確認後にURLエンコードして削除し、一覧を再取得する', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let glossaryGets = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary/Save%2FLoad%3F' && init?.method === 'DELETE') {
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (input === '/api/glossary') {
        glossaryGets += 1
        const terms = glossaryGets === 1 ? [{ source: 'Save/Load?', target: '保存/読込' }] : []
        return Promise.resolve(jsonResponse(terms))
      }
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)

    await user.click(await screen.findByRole('button', { name: 'Save/Load? を削除' }))

    await waitFor(() => expect(screen.queryByText('Save/Load?')).not.toBeInTheDocument())
    expect(window.confirm).toHaveBeenCalledWith('「Save/Load?」を辞書から削除しますか？')
    expect(glossaryGets).toBe(2)
  })

  it('削除成功後の一覧再取得失敗を区別し、暫定一覧から再試行できる', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let glossaryGets = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary/Save' && init?.method === 'DELETE') {
        return Promise.resolve(new Response(null, { status: 204 }))
      }
      if (input === '/api/glossary') {
        glossaryGets += 1
        if (glossaryGets === 1) return Promise.resolve(jsonResponse([{ source: 'Save', target: 'セーブ' }]))
        if (glossaryGets === 2) return Promise.resolve(jsonResponse({ detail: '一時的な取得失敗' }, 500))
        return Promise.resolve(jsonResponse([]))
      }
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)

    await user.click(await screen.findByRole('button', { name: 'Save を削除' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('削除済みですが、一覧の再取得に失敗しました。')
    expect(screen.queryByText('Save')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: '一覧を再取得' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
    expect(glossaryGets).toBe(3)
  })

  it('削除の404エラーを表示し、一覧を再取得して存在しない項目を除く', async () => {
    const user = userEvent.setup()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let glossaryGets = 0
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary/Save' && init?.method === 'DELETE') {
        return Promise.resolve(jsonResponse({ detail: '用語が見つかりません: Save' }, 404))
      }
      if (input === '/api/glossary') {
        glossaryGets += 1
        return Promise.resolve(jsonResponse(glossaryGets === 1 ? [{ source: 'Save', target: 'セーブ' }] : []))
      }
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)

    await user.click(await screen.findByRole('button', { name: 'Save を削除' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('用語が見つかりません: Save')
    await waitFor(() => expect(screen.queryByText('Save')).not.toBeInTheDocument())
    expect(glossaryGets).toBe(2)
  })

  it('初回一覧取得が完了するまで登録を無効化し、応答順逆転を防ぐ', async () => {
    const user = userEvent.setup()
    const initialGlossary = deferred<Response>()
    const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      if (input === '/api/config') return Promise.resolve(jsonResponse(config))
      if (input === '/api/glossary' && init?.method === 'POST') {
        return Promise.resolve(jsonResponse({ source: 'Save', target: 'セーブ' }, 201))
      }
      if (input === '/api/glossary') return initialGlossary.promise
      throw new Error(`想定外のリクエスト: ${String(input)}`)
    })
    vi.stubGlobal('fetch', fetchMock)
    render(<SettingsPanel />)
    const registerButton = screen.getByRole('button', { name: '用語を登録' })

    expect(registerButton).toBeDisabled()
    await user.click(registerButton)
    expect(fetchMock.mock.calls.filter(([, init]) => init?.method === 'POST')).toHaveLength(0)

    initialGlossary.resolve(jsonResponse([]))
    await waitFor(() => expect(registerButton).not.toBeDisabled())
  })
})
