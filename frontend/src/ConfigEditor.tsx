import { useEffect, useState } from 'react'

import { getConfig, saveConfig } from './api'
import { type ConfigDraft, toConfigDraft, validateConfigDraft } from './configForm'

const OCR_BACKENDS = [
  ['tesseract', 'Tesseract'],
  ['tesseract_llm_fallback', 'Tesseract + LLMフォールバック'],
  ['llm', 'LLM'],
  ['static', '固定値（テスト用）'],
] as const

const TRANSLATOR_BACKENDS = [
  ['argos', 'Argos Translate'],
  ['passthrough', '原文をそのまま返す（テスト用）'],
] as const

export function ConfigEditor() {
  const [draft, setDraft] = useState<ConfigDraft | null>(null)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    let active = true
    void getConfig()
      .then((config) => {
        if (active) setDraft(toConfigDraft(config))
      })
      .catch((reason: unknown) => {
        if (active) setError(messageOf(reason, '設定を取得できませんでした。'))
      })
    return () => {
      active = false
    }
  }, [])

  const update = <K extends keyof ConfigDraft>(field: K, value: ConfigDraft[K]) => {
    setDraft((current) => current && { ...current, [field]: value })
  }

  const submit = async () => {
    if (!draft || saving) return
    setError('')
    setNotice('')
    const validated = validateConfigDraft(draft)
    if (typeof validated === 'string') {
      setError(validated)
      return
    }
    setSaving(true)
    try {
      const saved = await saveConfig(validated)
      setNotice(saved.applied === 'next_start' ? '保存しました。次回開始から反映されます。' : '保存しました。')
      try {
        setDraft(toConfigDraft(await getConfig()))
      } catch (reason) {
        setError(`設定は保存されましたが、最新値を再取得できませんでした。${messageOf(reason, '')}`)
      }
    } catch (reason) {
      setError(messageOf(reason, '設定を保存できませんでした。'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="settings-section" aria-labelledby="config-heading">
      <div className="section-heading">
        <div>
          <h2 id="config-heading">翻訳設定</h2>
          <p>保存した変更は、実行中かどうかにかかわらず次回開始時に反映されます。</p>
        </div>
        <button type="button" onClick={() => void submit()} disabled={!draft || saving}>
          {saving ? '保存中…' : '設定を保存'}
        </button>
      </div>

      {error && <p className="form-message error" role="alert">{error}</p>}
      {notice && <p className="form-message success" role="status">{notice}</p>}
      {!draft ? (
        <p className="settings-loading">設定を読み込んでいます…</p>
      ) : (
        <form className="config-form" onSubmit={(event) => event.preventDefault()}>
          <fieldset>
            <legend>OCR・翻訳</legend>
            <div className="field-grid">
              <label>OCR FPS<input type="number" step="any" value={draft.ocr_fps} onChange={(event) => update('ocr_fps', event.target.value)} /></label>
              <label>最小信頼度<input type="number" step="any" min="0" max="1" value={draft.min_confidence} onChange={(event) => update('min_confidence', event.target.value)} /></label>
              <label>OCR方式<select value={draft.ocr_backend} onChange={(event) => update('ocr_backend', event.target.value as ConfigDraft['ocr_backend'])}>{OCR_BACKENDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label>OCRフォールバック信頼度<input type="number" step="any" min="0" max="1" value={draft.ocr_fallback_min_confidence} onChange={(event) => update('ocr_fallback_min_confidence', event.target.value)} /></label>
              <label>翻訳方式<select value={draft.translator_backend} onChange={(event) => update('translator_backend', event.target.value as ConfigDraft['translator_backend'])}>{TRANSLATOR_BACKENDS.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
              <label>LLMモデル<input type="text" value={draft.llm_model} onChange={(event) => update('llm_model', event.target.value)} /></label>
              <label>LLMタイムアウト（秒）<input type="number" step="any" value={draft.llm_timeout_seconds} onChange={(event) => update('llm_timeout_seconds', event.target.value)} /></label>
            </div>
          </fieldset>

          <fieldset>
            <legend>言語・実行方針</legend>
            <div className="field-grid">
              <label>原文言語<select value={draft.source_language} onChange={(event) => update('source_language', event.target.value as 'en')}><option value="en">英語 (en)</option></select></label>
              <label>翻訳先言語<select value={draft.target_language} onChange={(event) => update('target_language', event.target.value as 'ja')}><option value="ja">日本語 (ja)</option></select></label>
              <label>翻訳対象<select value={draft.target_scope} onChange={(event) => update('target_scope', event.target.value as 'ui_all')}><option value="ui_all">画面内UI全体</option></select></label>
              <label>外部API方針<select value={draft.external_api_policy} onChange={(event) => update('external_api_policy', event.target.value as 'local_first_free_only')}><option value="local_first_free_only">ローカル優先・無料のみ</option></select></label>
              <label className="wide-field">優先順位（カンマ区切り）<input type="text" value={draft.priority_order} onChange={(event) => update('priority_order', event.target.value)} /><small>gpu_speed, latency, translation_quality, implementation_speed</small></label>
            </div>
          </fieldset>

          <fieldset>
            <legend>オーバーレイ</legend>
            <div className="field-grid">
              <label>フォントサイズ<input type="number" step="1" min="1" value={draft.font_size} onChange={(event) => update('font_size', event.target.value)} /></label>
              <label>オーバーレイ透明度<input type="number" step="any" min="0" max="1" value={draft.overlay_opacity} onChange={(event) => update('overlay_opacity', event.target.value)} /></label>
              <label>文字色<input type="text" value={draft.text_color} onChange={(event) => update('text_color', event.target.value)} /></label>
              <label>背景色<input type="text" value={draft.background_color} onChange={(event) => update('background_color', event.target.value)} /></label>
            </div>
          </fieldset>
        </form>
      )}
    </section>
  )
}

function messageOf(reason: unknown, fallback: string): string {
  return reason instanceof Error ? reason.message : fallback
}
