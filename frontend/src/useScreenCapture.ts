import { useCallback, useEffect, useRef, useState } from 'react'

import { control, getStatus, ServiceApiError, stopWithKeepalive } from './api'
import type { ServiceState, ServiceStatus } from './api'

const SEND_INTERVAL_MS = 500
const STATUS_POLL_INTERVAL_MS = 200

export function useScreenCapture() {
  const [serviceState, setServiceState] = useState<ServiceState>('loading')
  const [operationInProgress, setOperationInProgress] = useState(false)
  const [statusText, setStatusText] = useState('翻訳処理の状態を確認しています。')
  const videoRef = useRef<HTMLVideoElement>(null)
  const canvasRef = useRef(document.createElement('canvas'))
  const streamRef = useRef<MediaStream | null>(null)
  const sendTimerRef = useRef<number | null>(null)
  const statusTimerRef = useRef<number | null>(null)
  const sessionTokenRef = useRef<string | undefined>(undefined)
  const sendingRef = useRef(false)
  const operationRef = useRef(false)
  const stopByUserRef = useRef<() => void>(() => undefined)

  const applyStatus = useCallback((status: ServiceStatus) => {
    setServiceState(status.state)
    if (status.session_token) {
      sessionTokenRef.current = status.session_token
    }
  }, [])

  const applyFailureStatus = useCallback(
    (error: unknown) => {
      if (error instanceof ServiceApiError && error.status) {
        applyStatus(error.status)
      }
    },
    [applyStatus],
  )

  const stopSharing = useCallback(() => {
    if (sendTimerRef.current !== null) {
      window.clearInterval(sendTimerRef.current)
      sendTimerRef.current = null
    }
    const stream = streamRef.current
    streamRef.current = null
    stream?.getTracks().forEach((track) => track.stop())
    if (videoRef.current) {
      videoRef.current.srcObject = null
    }
  }, [])

  const sendFrame = useCallback(async () => {
    const video = videoRef.current
    const token = sessionTokenRef.current
    if (sendingRef.current || !video || !token || !video.videoWidth || !video.videoHeight) {
      return
    }
    sendingRef.current = true
    try {
      const canvas = canvasRef.current
      canvas.width = video.videoWidth
      canvas.height = video.videoHeight
      const context = canvas.getContext('2d')
      if (!context) {
        return
      }
      context.drawImage(video, 0, 0, canvas.width, canvas.height)
      const blob = await canvasToJpeg(canvas)
      if (!blob) {
        return
      }
      const response = await fetch('/frame', {
        method: 'POST',
        headers: {
          'Content-Type': 'image/jpeg',
          'X-Capture-Token': token,
        },
        body: blob,
      })
      if (response.status === 403 && sessionTokenRef.current === token) {
        stopSharing()
        setStatusText('このタブのセッションは終了しました。画面を選び直してください。')
      }
    } catch {
      // 一時的な送信失敗は次のフレームで回復できるため、共有自体は維持する。
    } finally {
      sendingRef.current = false
    }
  }, [stopSharing])

  const selectAndShare = useCallback(async () => {
    let selectedStream: MediaStream
    try {
      selectedStream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: 5 },
        audio: false,
      })
    } catch (error) {
      setStatusText(`画面の選択がキャンセルされたか、失敗しました: ${String(error)}`)
      try {
        const stopped = await control('stop', sessionTokenRef.current)
        applyStatus(stopped)
        sessionTokenRef.current = undefined
      } catch {
        // 選択失敗を主メッセージとして保つ。
      }
      return false
    }
    streamRef.current = selectedStream
    if (videoRef.current) {
      videoRef.current.srcObject = selectedStream
    }
    selectedStream.getVideoTracks()[0]?.addEventListener('ended', () => {
      if (streamRef.current === selectedStream) {
        stopByUserRef.current()
      }
    })
    sendTimerRef.current = window.setInterval(() => void sendFrame(), SEND_INTERVAL_MS)
    setStatusText('送信中です。このタブは翻訳中も開いたままにしてください。')
    return true
  }, [applyStatus, sendFrame])

  const beginOperation = useCallback(() => {
    if (operationRef.current) {
      return false
    }
    operationRef.current = true
    setOperationInProgress(true)
    return true
  }, [])

  const endOperation = useCallback(() => {
    operationRef.current = false
    setOperationInProgress(false)
  }, [])

  const startSharing = useCallback(async () => {
    if (!beginOperation()) return
    try {
      applyStatus(await control('start'))
      await selectAndShare()
    } catch (error) {
      applyFailureStatus(error)
      setStatusText(`翻訳を開始できませんでした: ${String(error)}`)
    } finally {
      endOperation()
    }
  }, [applyFailureStatus, applyStatus, beginOperation, endOperation, selectAndShare])

  const stopByUser = useCallback(async () => {
    if (!beginOperation()) return
    stopSharing()
    try {
      applyStatus(await control('stop', sessionTokenRef.current))
      sessionTokenRef.current = undefined
      setStatusText('共有を終了しました。画面を選択すると再開できます。')
    } catch (error) {
      applyFailureStatus(error)
      setStatusText(`共有は停止しましたが、翻訳処理を停止できませんでした: ${String(error)}`)
    } finally {
      endOperation()
    }
  }, [applyFailureStatus, applyStatus, beginOperation, endOperation, stopSharing])

  stopByUserRef.current = () => void stopByUser()

  const reselectSharing = useCallback(async () => {
    if (!beginOperation()) return
    try {
      applyStatus(await control('reselect'))
      stopSharing()
      await selectAndShare()
    } catch (error) {
      applyFailureStatus(error)
      setStatusText(`画面を選び直せませんでした: ${String(error)}`)
    } finally {
      endOperation()
    }
  }, [applyFailureStatus, applyStatus, beginOperation, endOperation, selectAndShare, stopSharing])

  const syncStatus = useCallback(async () => {
    if (statusTimerRef.current !== null) {
      window.clearTimeout(statusTimerRef.current)
      statusTimerRef.current = null
    }
    try {
      const status = await getStatus()
      applyStatus(status)
      if (status.state === 'starting' || status.state === 'stopping') {
        statusTimerRef.current = window.setTimeout(() => void syncStatus(), STATUS_POLL_INTERVAL_MS)
      } else if (status.state === 'running' || status.state === 'awaiting_frame') {
        setStatusText('翻訳処理は実行中です。「画面を選び直す」から共有を再開できます。')
      } else if (status.state === 'idle') {
        setStatusText('画面、ウィンドウ、またはタブを選択してください。')
      }
    } catch (error) {
      setServiceState('error')
      setStatusText(`翻訳処理の状態を取得できませんでした: ${String(error)}`)
    }
  }, [applyStatus])

  useEffect(() => {
    const handlePageHide = () => {
      stopSharing()
      stopWithKeepalive(sessionTokenRef.current)
    }
    window.addEventListener('pageshow', syncStatus)
    window.addEventListener('pagehide', handlePageHide)
    void syncStatus()
    return () => {
      window.removeEventListener('pageshow', syncStatus)
      window.removeEventListener('pagehide', handlePageHide)
      if (statusTimerRef.current !== null) window.clearTimeout(statusTimerRef.current)
      stopSharing()
    }
  }, [stopSharing, syncStatus])

  const active = serviceState === 'running' || serviceState === 'awaiting_frame'
  const locked = operationInProgress || ['loading', 'starting', 'stopping'].includes(serviceState)
  return {
    videoRef,
    statusText,
    startSharing,
    stopByUser,
    reselectSharing,
    startDisabled: locked || active || serviceState === 'error',
    reselectDisabled: locked || !active,
    stopDisabled: locked || (!active && serviceState !== 'error'),
  }
}

function canvasToJpeg(canvas: HTMLCanvasElement): Promise<Blob | null> {
  return new Promise((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.8))
}
