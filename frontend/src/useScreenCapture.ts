import { useCallback, useEffect, useRef, useState } from 'react'

import { control, getStatus, ServiceApiError, stopWithKeepalive } from './api'
import type { ServiceState, ServiceStatus } from './api'
import { CaptureFrameSender } from './captureFrameSender'

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
  const frameSenderRef = useRef(new CaptureFrameSender())
  const operationGenerationRef = useRef(0)
  const operationRef = useRef(false)
  const mountedRef = useRef(false)
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

  const isOperationValid = useCallback(
    (generation: number) => mountedRef.current && operationGenerationRef.current === generation,
    [],
  )

  const stopSharing = useCallback(() => {
    frameSenderRef.current.reset()
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
    await frameSenderRef.current.send(
      videoRef.current,
      canvasRef.current,
      sessionTokenRef.current,
      () => {
        stopSharing()
        sessionTokenRef.current = undefined
        setStatusText('このタブのセッションは終了しました。画面を選び直してください。')
      },
    )
  }, [stopSharing])

  const selectAndShare = useCallback(
    async (generation: number) => {
      let selectedStream: MediaStream
      try {
        selectedStream = await navigator.mediaDevices.getDisplayMedia({
          video: { frameRate: 5 },
          audio: false,
        })
      } catch (error) {
        if (!isOperationValid(generation)) return false
        setStatusText(`画面の選択がキャンセルされたか、失敗しました: ${String(error)}`)
        try {
          const stopped = await control('stop', sessionTokenRef.current)
          if (!isOperationValid(generation)) {
            stopWithKeepalive(stopped.session_token)
            return false
          }
          applyStatus(stopped)
          sessionTokenRef.current = undefined
        } catch {
          // 選択失敗を主メッセージとして保つ。
        }
        return false
      }
      if (!isOperationValid(generation)) {
        selectedStream.getTracks().forEach((track) => track.stop())
        stopWithKeepalive(sessionTokenRef.current)
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
    },
    [applyStatus, isOperationValid, sendFrame],
  )

  const beginOperation = useCallback(() => {
    if (operationRef.current || !mountedRef.current) {
      return null
    }
    if (statusTimerRef.current !== null) {
      window.clearTimeout(statusTimerRef.current)
      statusTimerRef.current = null
    }
    operationRef.current = true
    operationGenerationRef.current += 1
    setOperationInProgress(true)
    return operationGenerationRef.current
  }, [])

  const endOperation = useCallback((generation: number) => {
    if (!mountedRef.current || operationGenerationRef.current !== generation) return
    operationRef.current = false
    setOperationInProgress(false)
  }, [])

  const invalidateOperation = useCallback((updateState: boolean) => {
    operationGenerationRef.current += 1
    operationRef.current = false
    if (updateState && mountedRef.current) {
      setOperationInProgress(false)
    }
  }, [])

  const syncStatus = useCallback(async () => {
    if (statusTimerRef.current !== null) {
      window.clearTimeout(statusTimerRef.current)
      statusTimerRef.current = null
    }
    const generation = operationGenerationRef.current
    try {
      const status = await getStatus()
      if (!isOperationValid(generation)) return
      applyStatus(status)
      if (status.state === 'starting' || status.state === 'stopping') {
        statusTimerRef.current = window.setTimeout(() => void syncStatus(), STATUS_POLL_INTERVAL_MS)
      } else if (status.state === 'running' || status.state === 'awaiting_frame') {
        setStatusText('翻訳処理は実行中です。「画面を選び直す」から共有を再開できます。')
      } else if (status.state === 'idle') {
        setStatusText('画面、ウィンドウ、またはタブを選択してください。')
      } else if (status.state === 'error') {
        setStatusText(`翻訳処理でエラーが発生しました: ${status.error_message || '詳細不明'}`)
      }
    } catch (error) {
      if (!isOperationValid(generation)) return
      setServiceState('error')
      setStatusText(`翻訳処理の状態を取得できませんでした: ${String(error)}`)
    }
  }, [applyStatus, isOperationValid])

  const applyOperationFailure = useCallback(
    async (error: unknown) => {
      applyFailureStatus(error)
      if (error instanceof ServiceApiError && error.responseStatus === 409) {
        await syncStatus()
      }
    },
    [applyFailureStatus, syncStatus],
  )

  const startSharing = useCallback(async () => {
    const generation = beginOperation()
    if (generation === null) return
    try {
      const status = await control('start')
      if (!isOperationValid(generation)) {
        stopWithKeepalive(status.session_token)
        return
      }
      applyStatus(status)
      await selectAndShare(generation)
    } catch (error) {
      if (!isOperationValid(generation)) return
      await applyOperationFailure(error)
      if (!isOperationValid(generation)) return
      setStatusText(`翻訳を開始できませんでした: ${String(error)}`)
    } finally {
      endOperation(generation)
    }
  }, [applyOperationFailure, applyStatus, beginOperation, endOperation, isOperationValid, selectAndShare])

  const stopByUser = useCallback(async () => {
    const generation = beginOperation()
    if (generation === null) return
    stopSharing()
    try {
      const status = await control('stop', sessionTokenRef.current)
      if (!isOperationValid(generation)) {
        stopWithKeepalive(status.session_token)
        return
      }
      applyStatus(status)
      sessionTokenRef.current = undefined
      setStatusText('共有を終了しました。画面を選択すると再開できます。')
    } catch (error) {
      if (!isOperationValid(generation)) return
      await applyOperationFailure(error)
      if (!isOperationValid(generation)) return
      setStatusText(`共有は停止しましたが、翻訳処理を停止できませんでした: ${String(error)}`)
    } finally {
      endOperation(generation)
    }
  }, [applyOperationFailure, applyStatus, beginOperation, endOperation, isOperationValid, stopSharing])

  stopByUserRef.current = () => void stopByUser()

  const reselectSharing = useCallback(async () => {
    const generation = beginOperation()
    if (generation === null) return
    stopSharing()
    try {
      const status = await control('reselect')
      if (!isOperationValid(generation)) {
        stopWithKeepalive(status.session_token)
        return
      }
      applyStatus(status)
      await selectAndShare(generation)
    } catch (error) {
      if (!isOperationValid(generation)) return
      await applyOperationFailure(error)
      if (!isOperationValid(generation)) return
      setStatusText(`画面を選び直せませんでした: ${String(error)}`)
    } finally {
      endOperation(generation)
    }
  }, [applyOperationFailure, applyStatus, beginOperation, endOperation, isOperationValid, selectAndShare, stopSharing])

  useEffect(() => {
    mountedRef.current = true
    const stopOwnedSession = () => {
      invalidateOperation(true)
      stopSharing()
      stopWithKeepalive(sessionTokenRef.current)
      sessionTokenRef.current = undefined
    }
    const handlePageShow = () => void syncStatus()
    window.addEventListener('pageshow', handlePageShow)
    window.addEventListener('pagehide', stopOwnedSession)
    void syncStatus()
    return () => {
      window.removeEventListener('pageshow', handlePageShow)
      window.removeEventListener('pagehide', stopOwnedSession)
      invalidateOperation(false)
      mountedRef.current = false
      if (statusTimerRef.current !== null) window.clearTimeout(statusTimerRef.current)
      stopSharing()
      stopWithKeepalive(sessionTokenRef.current)
      sessionTokenRef.current = undefined
    }
  }, [invalidateOperation, stopSharing, syncStatus])

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
