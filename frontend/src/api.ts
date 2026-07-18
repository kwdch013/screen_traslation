export type ServiceState =
  | 'loading'
  | 'idle'
  | 'starting'
  | 'awaiting_frame'
  | 'running'
  | 'stopping'
  | 'error'

export interface ServiceStatus {
  state: ServiceState
  error_message?: string | null
  session_token?: string
  session_token_valid?: boolean
  detail?: string
}

export interface OverlayStyleConfig {
  font_size: number
  text_color: string
  background_color: string
  overlay_opacity: number
}

export interface PublicConfig {
  ocr_fps: number
  min_confidence: number
  ocr_backend: 'static' | 'tesseract' | 'tesseract_llm_fallback' | 'llm'
  ocr_fallback_min_confidence: number
  translator_backend: 'passthrough' | 'argos'
  llm_model: string
  llm_timeout_seconds: number
  source_language: 'en'
  target_language: 'ja'
  target_scope: 'ui_all'
  external_api_policy: 'local_first_free_only'
  priority_order: string[]
  overlay_style: OverlayStyleConfig
}

export interface ConfigSaveResponse extends PublicConfig {
  applied: 'next_start'
}

export interface GlossaryTerm {
  source: string
  target: string
}

export class ServiceApiError extends Error {
  readonly status?: ServiceStatus
  readonly responseStatus?: number

  constructor(message: string, status?: ServiceStatus, responseStatus?: number) {
    super(message)
    this.status = status
    this.responseStatus = responseStatus
  }
}

export async function getStatus(): Promise<ServiceStatus> {
  const response = await fetch('/api/status')
  return parseStatusResponse(response, '状態を取得できませんでした。', true)
}

export async function control(
  action: 'start' | 'stop' | 'reselect',
  sessionToken?: string,
): Promise<ServiceStatus> {
  const headers = sessionToken ? { 'X-Capture-Token': sessionToken } : undefined
  const response = await fetch(`/api/control/${action}`, {
    method: 'POST',
    ...(headers ? { headers } : {}),
  })
  return parseStatusResponse(response, '制御APIの呼び出しに失敗しました。')
}

export async function stopWithKeepalive(sessionToken?: string): Promise<void> {
  if (!sessionToken) {
    return
  }
  try {
    await fetch('/api/control/stop', {
      method: 'POST',
      headers: { 'X-Capture-Token': sessionToken },
      keepalive: true,
    })
  } catch {
    // ページ離脱時のベストエフォート停止では通信失敗を画面へ反映できない。
  }
}

export async function getConfig(): Promise<PublicConfig> {
  const response = await fetch('/api/config')
  return parseJsonResponse(response, '設定を取得できませんでした。', isPublicConfig)
}

export async function saveConfig(config: PublicConfig): Promise<ConfigSaveResponse> {
  const response = await fetch('/api/config', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  })
  return parseJsonResponse(response, '設定を保存できませんでした。', isConfigSaveResponse)
}

export async function getGlossary(): Promise<GlossaryTerm[]> {
  const response = await fetch('/api/glossary')
  return parseJsonResponse(response, '辞書を取得できませんでした。', isGlossaryTerms)
}

export async function registerGlossaryTerm(source: string, target: string): Promise<GlossaryTerm> {
  const response = await fetch('/api/glossary', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source, target }),
  })
  return parseJsonResponse(response, '用語を登録できませんでした。', isGlossaryTerm)
}

export async function deleteGlossaryTerm(source: string): Promise<void> {
  const response = await fetch(`/api/glossary/${encodeURIComponent(source)}`, { method: 'DELETE' })
  if (!response.ok) {
    throw new ServiceApiError(await responseErrorMessage(response, '用語を削除できませんでした。'), undefined, response.status)
  }
}

async function parseStatusResponse(
  response: Response,
  fallback: string,
  acceptErrorState = false,
): Promise<ServiceStatus> {
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ServiceApiError(fallback, undefined, response.status)
  }
  const status = isServiceStatus(body) ? body : undefined
  if (!response.ok) {
    throw new ServiceApiError(errorMessage(body, fallback), status, response.status)
  }
  if (!status) {
    throw new ServiceApiError(fallback, undefined, response.status)
  }
  if (status.state === 'error' && !acceptErrorState) {
    throw new ServiceApiError(status.error_message || fallback, status, response.status)
  }
  return status
}

const SERVICE_STATES: readonly ServiceState[] = [
  'loading',
  'idle',
  'starting',
  'awaiting_frame',
  'running',
  'stopping',
  'error',
]

function isServiceStatus(body: unknown): body is ServiceStatus {
  if (!body || typeof body !== 'object' || !('state' in body)) {
    return false
  }
  return typeof body.state === 'string' && SERVICE_STATES.includes(body.state as ServiceState)
}

function errorMessage(body: unknown, fallback: string): string {
  if (!body || typeof body !== 'object') {
    return fallback
  }
  if ('detail' in body && typeof body.detail === 'string') {
    return body.detail
  }
  if ('error_message' in body && typeof body.error_message === 'string') {
    return body.error_message
  }
  return fallback
}

async function parseJsonResponse<T>(
  response: Response,
  fallback: string,
  isExpected: (body: unknown) => body is T,
): Promise<T> {
  let body: unknown
  try {
    body = await response.json()
  } catch {
    throw new ServiceApiError(fallback, undefined, response.status)
  }
  if (!response.ok) {
    throw new ServiceApiError(errorMessage(body, fallback), undefined, response.status)
  }
  if (!isExpected(body)) {
    throw new ServiceApiError(fallback, undefined, response.status)
  }
  return body
}

async function responseErrorMessage(response: Response, fallback: string): Promise<string> {
  try {
    return errorMessage(await response.json(), fallback)
  } catch {
    return fallback
  }
}

function isPublicConfig(body: unknown): body is PublicConfig {
  if (!body || typeof body !== 'object') return false
  const value = body as Record<string, unknown>
  const style = value.overlay_style
  return (
    isFiniteNumber(value.ocr_fps) &&
    isFiniteNumber(value.min_confidence) &&
    isOneOf(value.ocr_backend, ['static', 'tesseract', 'tesseract_llm_fallback', 'llm']) &&
    isFiniteNumber(value.ocr_fallback_min_confidence) &&
    isOneOf(value.translator_backend, ['passthrough', 'argos']) &&
    typeof value.llm_model === 'string' &&
    isFiniteNumber(value.llm_timeout_seconds) &&
    value.source_language === 'en' &&
    value.target_language === 'ja' &&
    value.target_scope === 'ui_all' &&
    value.external_api_policy === 'local_first_free_only' &&
    Array.isArray(value.priority_order) &&
    value.priority_order.every((item) => typeof item === 'string') &&
    isOverlayStyle(style)
  )
}

function isConfigSaveResponse(body: unknown): body is ConfigSaveResponse {
  return isPublicConfig(body) && 'applied' in body && body.applied === 'next_start'
}

function isOverlayStyle(value: unknown): value is OverlayStyleConfig {
  if (!value || typeof value !== 'object') return false
  const style = value as Record<string, unknown>
  return (
    Number.isInteger(style.font_size) &&
    typeof style.text_color === 'string' &&
    typeof style.background_color === 'string' &&
    isFiniteNumber(style.overlay_opacity)
  )
}

function isGlossaryTerm(body: unknown): body is GlossaryTerm {
  if (!body || typeof body !== 'object') return false
  const term = body as Record<string, unknown>
  return typeof term.source === 'string' && typeof term.target === 'string'
}

function isGlossaryTerms(body: unknown): body is GlossaryTerm[] {
  return Array.isArray(body) && body.every(isGlossaryTerm)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function isOneOf<T extends string>(value: unknown, choices: readonly T[]): value is T {
  return typeof value === 'string' && choices.includes(value as T)
}
