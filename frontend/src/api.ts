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

  constructor(message: string, status?: ServiceStatus) {
    super(message)
    this.status = status
  }
}

export async function getStatus(): Promise<ServiceStatus> {
  const response = await fetch('/api/status')
  return parseStatusResponse(response, '状態を取得できませんでした。')
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

export function stopWithKeepalive(sessionToken?: string): void {
  if (!sessionToken) {
    return
  }
  void fetch('/api/control/stop', {
    method: 'POST',
    headers: { 'X-Capture-Token': sessionToken },
    keepalive: true,
  }).catch(() => undefined)
}

async function parseStatusResponse(response: Response, fallback: string): Promise<ServiceStatus> {
  let body: ServiceStatus
  try {
    body = (await response.json()) as ServiceStatus
  } catch {
    throw new ServiceApiError(fallback)
  }
  if (!response.ok || body.state === 'error') {
    throw new ServiceApiError(body.detail || body.error_message || fallback, body)
  }
  return body
}
