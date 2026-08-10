import { useCallback, useEffect, useRef, useState } from 'react'

import { control, getStatus, ServiceApiError, stopWithKeepalive } from './api'
import type { ServiceState, ServiceStatus } from './api'
import { CaptureFrameSender } from './captureFrameSender'
import { useCropSelection } from './useCropSelection'

const SEND_INTERVAL_MS = 500
const STATUS_POLL_INTERVAL_MS = 200

export function useScreenCapture() {
  const [serviceState, setServiceState] = useState<ServiceState>('loading')
  const [operationInProgress, setOperationInProgress] = useState(false)
  const [statusText, setStatusText] = useState('翻訳処理の状態を確認しています。')
  const videoRef = useRef<HTMLVideoElement>(null)
  const {
    crop,
    cropEnabled,
    cropRef,
    disableSelection,
    handleVideoResize,
    prepareForStream,
    restoreForVideo,
    setCropSelection,
  } = useCropSelection(videoRef)
  const canvasRef = useRef(document.createElement('canvas'))
  const streamRef = useRef<MediaStream | null>(null)
  const sendTimerRef = useRef<number | null>(null)
  const statusTimerRef = useRef<number | null>(null)
  const sessionTokenRef = useRef<string | undefined>(undefined)
  const frameSenderRef = useRef(new CaptureFrameSender())
  const operationGenerationRef = useRef(0)
  const operationRef = useRef(false)
  const mountedRef = useRef(false)
  const pageHiddenRef = useRef(false)
  const keepaliveStopRef = useRef<Promise<void> | null>(null)
  const syncStatusRef = useRef<() => Promise<void>>(async () => undefined)
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
    disableSelection()
  }, [disableSelection])

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
      cropRef.current,
    )
  }, [cropRef, stopSharing])

  const stopWithKeepaliveAndSync = useCallback((sessionToken?: string) => {
    if (!sessionToken) return
    const stopPromise = stopWithKeepalive(sessionToken)
    keepaliveStopRef.current = stopPromise
    void stopPromise.then(() => {
      if (keepaliveStopRef.current !== stopPromise) return
      keepaliveStopRef.current = null
      if (mountedRef.current && !pageHiddenRef.current) {
        void syncStatusRef.current()
      }
    })
  }, [])

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
            stopWithKeepaliveAndSync(stopped.session_token)
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
        stopWithKeepaliveAndSync(sessionTokenRef.current)
        return false
      }
      streamRef.current = selectedStream
      prepareForStream(selectedStream.getVideoTracks()[0]?.label ?? '')
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
    [applyStatus, isOperationValid, prepareForStream, sendFrame, stopWithKeepaliveAndSync],
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

  syncStatusRef.current = syncStatus

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
        stopWithKeepaliveAndSync(status.session_token)
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
  }, [applyOperationFailure, applyStatus, beginOperation, endOperation, isOperationValid, selectAndShare, stopWithKeepaliveAndSync])

  const stopByUser = useCallback(async () => {
    const generation = beginOperation()
    if (generation === null) return
    stopSharing()
    try {
      const status = await control('stop', sessionTokenRef.current)
      if (!isOperationValid(generation)) {
        stopWithKeepaliveAndSync(status.session_token)
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
  }, [applyOperationFailure, applyStatus, beginOperation, endOperation, isOperationValid, stopSharing, stopWithKeepaliveAndSync])

  stopByUserRef.current = () => void stopByUser()

  const reselectSharing = useCallback(async () => {
    const generation = beginOperation()
    if (generation === null) return
    stopSharing()
    try {
      const status = await control('reselect')
      if (!isOperationValid(generation)) {
        stopWithKeepaliveAndSync(status.session_token)
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
  }, [applyOperationFailure, applyStatus, beginOperation, endOperation, isOperationValid, selectAndShare, stopSharing, stopWithKeepaliveAndSync])

  useEffect(() => {
    mountedRef.current = true
    const stopOwnedSession = () => {
      pageHiddenRef.current = true
      invalidateOperation(true)
      stopSharing()
      stopWithKeepaliveAndSync(sessionTokenRef.current)
      sessionTokenRef.current = undefined
    }
    const handlePageShow = () => {
      pageHiddenRef.current = false
      void syncStatus()
    }
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
      stopWithKeepaliveAndSync(sessionTokenRef.current)
      sessionTokenRef.current = undefined
    }
  }, [invalidateOperation, stopSharing, stopWithKeepaliveAndSync, syncStatus])

  const active = serviceState === 'running' || serviceState === 'awaiting_frame'
  const locked = operationInProgress || ['loading', 'starting', 'stopping'].includes(serviceState)
  return {
    videoRef,
    crop,
    cropEnabled,
    handleVideoResize,
    restoreCropForVideo: restoreForVideo,
    setCropSelection,
    statusText,
    startSharing,
    stopByUser,
    reselectSharing,
    startDisabled: locked || active || serviceState === 'error',
    reselectDisabled: locked || !active,
    stopDisabled: locked || (!active && serviceState !== 'error'),
  }
}
