import type { PublicConfig } from './api'

export interface ConfigDraft {
  ocr_fps: string
  min_confidence: string
  ocr_backend: PublicConfig['ocr_backend']
  ocr_fallback_min_confidence: string
  translator_backend: PublicConfig['translator_backend']
  llm_model: string
  llm_timeout_seconds: string
  source_language: PublicConfig['source_language']
  target_language: PublicConfig['target_language']
  target_scope: PublicConfig['target_scope']
  external_api_policy: PublicConfig['external_api_policy']
  priority_order: string
  font_size: string
  text_color: string
  background_color: string
  overlay_opacity: string
}

const PRIORITIES = new Set([
  'gpu_speed',
  'latency',
  'translation_quality',
  'implementation_speed',
])

export function toConfigDraft(config: PublicConfig): ConfigDraft {
  return {
    ocr_fps: String(config.ocr_fps),
    min_confidence: String(config.min_confidence),
    ocr_backend: config.ocr_backend,
    ocr_fallback_min_confidence: String(config.ocr_fallback_min_confidence),
    translator_backend: config.translator_backend,
    llm_model: config.llm_model,
    llm_timeout_seconds: String(config.llm_timeout_seconds),
    source_language: config.source_language,
    target_language: config.target_language,
    target_scope: config.target_scope,
    external_api_policy: config.external_api_policy,
    priority_order: config.priority_order.join(', '),
    font_size: String(config.overlay_style.font_size),
    text_color: config.overlay_style.text_color,
    background_color: config.overlay_style.background_color,
    overlay_opacity: String(config.overlay_style.overlay_opacity),
  }
}

export function validateConfigDraft(draft: ConfigDraft): PublicConfig | string {
  const ocrFps = numberValue(draft.ocr_fps)
  if (ocrFps === undefined || ocrFps <= 0) return 'OCR FPSは0より大きい値を入力してください。'
  const minConfidence = numberValue(draft.min_confidence)
  if (!inUnitRange(minConfidence)) return '最小信頼度は0から1の範囲で入力してください。'
  const fallbackConfidence = numberValue(draft.ocr_fallback_min_confidence)
  if (!inUnitRange(fallbackConfidence)) return 'OCRフォールバック信頼度は0から1の範囲で入力してください。'
  const timeout = numberValue(draft.llm_timeout_seconds)
  if (timeout === undefined || timeout <= 0) return 'LLMタイムアウトは0より大きい値を入力してください。'
  const fontSize = numberValue(draft.font_size)
  if (fontSize === undefined || !Number.isInteger(fontSize) || fontSize < 1) {
    return 'フォントサイズは1以上の整数を入力してください。'
  }
  const opacity = numberValue(draft.overlay_opacity)
  if (!inUnitRange(opacity)) return 'オーバーレイ透明度は0から1の範囲で入力してください。'
  const priorityOrder = draft.priority_order.split(',').map((item) => item.trim()).filter(Boolean)
  const unsupported = priorityOrder.find((item) => !PRIORITIES.has(item))
  if (unsupported) return `優先順位に未対応の値があります: ${unsupported}`

  return {
    ocr_fps: ocrFps,
    min_confidence: minConfidence,
    ocr_backend: draft.ocr_backend,
    ocr_fallback_min_confidence: fallbackConfidence,
    translator_backend: draft.translator_backend,
    llm_model: draft.llm_model,
    llm_timeout_seconds: timeout,
    source_language: draft.source_language,
    target_language: draft.target_language,
    target_scope: draft.target_scope,
    external_api_policy: draft.external_api_policy,
    priority_order: priorityOrder,
    overlay_style: {
      font_size: fontSize,
      text_color: draft.text_color,
      background_color: draft.background_color,
      overlay_opacity: opacity,
    },
  }
}

function numberValue(value: string): number | undefined {
  if (!value.trim()) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

function inUnitRange(value: number | undefined): value is number {
  return value !== undefined && value >= 0 && value <= 1
}
