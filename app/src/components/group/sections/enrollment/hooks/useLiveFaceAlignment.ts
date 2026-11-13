import { useCallback, useEffect, useRef, useState, type RefObject } from "react"

import {
  backendService,
  type FaceAlignmentEvaluation,
} from "@/services/BackendService"
import type { EnrollmentAngleKey } from "../enrollmentAngles"

interface UseLiveFaceAlignmentOptions {
  videoRef: RefObject<HTMLVideoElement | null>
  isActive: boolean
  targetAngle: EnrollmentAngleKey | null
  mirrored?: boolean
  intervalMs?: number
  autoCaptureEnabled?: boolean
  autoCapturePaused?: boolean
  onAutoCaptureReady?: (angle: EnrollmentAngleKey) => void
}

export function useLiveFaceAlignment({
  videoRef,
  isActive,
  targetAngle,
  mirrored = true,
  intervalMs = 340,
  autoCaptureEnabled = false,
  autoCapturePaused = false,
  onAutoCaptureReady,
}: UseLiveFaceAlignmentOptions) {
  const [alignment, setAlignment] = useState<FaceAlignmentEvaluation | null>(null)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [steadyCount, setSteadyCount] = useState(0)

  const inFlightRef = useRef(false)
  const sessionRef = useRef(0)
  const steadyCountRef = useRef(0)
  const lastAutoAngleRef = useRef<string | null>(null)
  const canvasRef = useRef<HTMLCanvasElement | null>(null)
  const onAutoCaptureRef = useRef(onAutoCaptureReady)

  useEffect(() => {
    onAutoCaptureRef.current = onAutoCaptureReady
  }, [onAutoCaptureReady])

  // Reset steady counter whenever target angle changes
  useEffect(() => {
    steadyCountRef.current = 0
    setSteadyCount(0)
    lastAutoAngleRef.current = null
  }, [targetAngle])

  const resetAlignment = useCallback(() => {
    sessionRef.current += 1
    inFlightRef.current = false
    steadyCountRef.current = 0
    lastAutoAngleRef.current = null
    setAlignment(null)
    setSteadyCount(0)
    setIsAnalyzing(false)
  }, [])

  useEffect(() => {
    if (!isActive || !targetAngle) {
      resetAlignment()
      return
    }

    const sessionId = ++sessionRef.current
    let cancelled = false

    const analyzeOnce = async () => {
      if (cancelled || inFlightRef.current || autoCapturePaused) return
      const video = videoRef.current
      if (
        !video ||
        video.readyState < 2 ||
        video.videoWidth <= 0 ||
        video.videoHeight <= 0
      ) {
        return
      }

      inFlightRef.current = true
      setIsAnalyzing(true)

      let canvas = canvasRef.current
      if (!canvas) {
        canvas = document.createElement("canvas")
        canvasRef.current = canvas
      }
      if (canvas.width !== video.videoWidth || canvas.height !== video.videoHeight) {
        canvas.width = video.videoWidth
        canvas.height = video.videoHeight
      }

      const ctx = canvas.getContext("2d")
      if (!ctx) {
        inFlightRef.current = false
        setIsAnalyzing(false)
        return
      }

      ctx.save()
      if (mirrored) {
        // Flip pixels horizontally to match mirrored selfie video preview
        ctx.translate(canvas.width, 0)
        ctx.scale(-1, 1)
      }
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      ctx.restore()

      let blob: Blob | null = null
      try {
        blob = await new Promise<Blob | null>((resolve) =>
          canvas!.toBlob(resolve, "image/jpeg", 0.78),
        )
        if (!blob || cancelled || sessionId !== sessionRef.current) return

        const detection = await backendService.detectFaces(blob, {
          model_type: "face_detector",
          enableLiveness: false,
          includeAlignment: true,
          targetAngle,
          mirrored: false,
        })

        if (cancelled || sessionId !== sessionRef.current) return

        const evalResult = detection.alignment || null
        setAlignment(evalResult)

        if (evalResult?.ready && autoCaptureEnabled && !autoCapturePaused) {
          steadyCountRef.current += 1
          setSteadyCount(steadyCountRef.current)
          if (
            steadyCountRef.current >= 2 &&
            lastAutoAngleRef.current !== targetAngle
          ) {
            lastAutoAngleRef.current = targetAngle
            steadyCountRef.current = 0
            setSteadyCount(0)
            onAutoCaptureRef.current?.(targetAngle)
          }
        } else {
          steadyCountRef.current = 0
          setSteadyCount(0)
        }
      } catch {
        // Keep last telemetry transient without spamming modal error banner during polling
      } finally {
        blob = null
        inFlightRef.current = false
        if (!cancelled && sessionId === sessionRef.current) {
          setIsAnalyzing(false)
        }
      }
    }

    // Immediate probe plus interval loop
    void analyzeOnce()
    const timer = window.setInterval(() => {
      void analyzeOnce()
    }, intervalMs)

    return () => {
      cancelled = true
      window.clearInterval(timer)
      inFlightRef.current = false
    }
  }, [
    isActive,
    targetAngle,
    videoRef,
    mirrored,
    intervalMs,
    autoCaptureEnabled,
    autoCapturePaused,
    resetAlignment,
  ])

  return {
    alignment,
    isAnalyzing,
    steadyCount,
    resetAlignment,
  }
}

