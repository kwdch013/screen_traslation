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
