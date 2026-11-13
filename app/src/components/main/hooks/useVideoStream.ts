import { useCallback, useEffect } from "react"
import { IP_CAMERA_DEVICE_ID, useCameraStore, useUIStore } from "@/components/main/stores"

interface UseVideoStreamOptions {
  videoRef: React.RefObject<HTMLVideoElement | null>
  ipImageRef?: React.RefObject<HTMLImageElement | null>
  canvasRef: React.RefObject<HTMLCanvasElement | null>
  isStreamingRef: React.MutableRefObject<boolean>
  isScanningRef: React.MutableRefObject<boolean>
  videoRectRef: React.MutableRefObject<DOMRect | null>
  lastVideoRectUpdateRef: React.MutableRefObject<number>
  isStartingRef: React.MutableRefObject<boolean>
  onDeviceDisconnected?: () => void
}

export function useVideoStream(options: UseVideoStreamOptions) {
  const {
    videoRef,
    ipImageRef,
    canvasRef,
    isStreamingRef,
    isScanningRef,
    videoRectRef,
    lastVideoRectUpdateRef,
    isStartingRef,
    onDeviceDisconnected,
  } = options

  const {
    cameraDevices,
    selectedCamera,
    activeIpStreamUrl,
    setCameraDevices,
    setSelectedCamera,
    setIsStreaming,
    setCameraActive,
  } = useCameraStore()
  const { setError } = useUIStore()

  useEffect(() => {
    const video = videoRef.current
    if (!video) return

    const checkVideoState = () => {
      const img = ipImageRef?.current
      const usingIp = Boolean(useCameraStore.getState().activeIpStreamUrl)
      let shouldBeActive = false
      if (usingIp) {
        shouldBeActive = Boolean(img && img.naturalWidth > 0 && img.naturalHeight > 0)
      } else {
        const hasStream = video.srcObject !== null
        const isPlaying = !video.paused && !video.ended && video.readyState > 2
        shouldBeActive = hasStream && isPlaying
      }

      const prevActive = useCameraStore.getState().cameraActive
      if (prevActive !== shouldBeActive) {
        if (shouldBeActive && !isStreamingRef.current) {
          isStreamingRef.current = true
          setIsStreaming(true)
        } else if (!shouldBeActive && isStreamingRef.current) {
          if (isStartingRef.current) {
            return
          }
          isStreamingRef.current = false
          setIsStreaming(false)
          isScanningRef.current = false
        }
        setCameraActive(shouldBeActive)
      }
    }

    checkVideoState()
    const events = ["loadedmetadata", "play", "pause", "ended", "emptied"]
    events.forEach((event) => {
      video.addEventListener(event, checkVideoState)
    })
    const interval = setInterval(checkVideoState, 200)

    const resizeObserver = new ResizeObserver(() => {
      requestAnimationFrame(() => {
        const target =
          useCameraStore.getState().activeIpStreamUrl && ipImageRef?.current ?
            ipImageRef.current
          : video
        if (target && videoRectRef.current) {
          videoRectRef.current = target.getBoundingClientRect()
          lastVideoRectUpdateRef.current = Date.now()
        }
      })
    })
    resizeObserver.observe(video)
    if (ipImageRef?.current) {
      resizeObserver.observe(ipImageRef.current)
    }

    return () => {
      events.forEach((event) => {
        video.removeEventListener(event, checkVideoState)
      })
      clearInterval(interval)
      resizeObserver.disconnect()
    }
  }, [
    activeIpStreamUrl,
    ipImageRef,
    isScanningRef,
    isStartingRef,
    isStreamingRef,
    lastVideoRectUpdateRef,
    setCameraActive,
    setIsStreaming,
    videoRectRef,
    videoRef,
  ])

  const captureFrame = useCallback((): Promise<ArrayBuffer | null> => {
    const video = videoRef.current
    const img = ipImageRef?.current
    const canvas = canvasRef.current
    const usingIp = Boolean(useCameraStore.getState().activeIpStreamUrl)

    if (!canvas) {
      return Promise.resolve(null)
    }

    const sourceWidth = usingIp ? (img?.naturalWidth ?? 0) : (video?.videoWidth ?? 0)
    const sourceHeight = usingIp ? (img?.naturalHeight ?? 0) : (video?.videoHeight ?? 0)
    const sourceEl = usingIp ? img : video

    if (!sourceEl || sourceWidth === 0 || sourceHeight === 0) {
      return Promise.resolve(null)
    }

    const ctx = canvas.getContext("2d", {
      alpha: false,
      willReadFrequently: false,
    })
    if (!ctx) {
      return Promise.resolve(null)
    }

    if (canvas.width !== sourceWidth || canvas.height !== sourceHeight) {
      canvas.width = sourceWidth
      canvas.height = sourceHeight
    }

    return new Promise((resolve) => {
      try {
        ctx.drawImage(sourceEl, 0, 0, canvas.width, canvas.height)
        canvas.toBlob(
          (blob) => {
            if (!blob) {
              resolve(null)
              return
            }
            blob
              .arrayBuffer()
              .then(resolve)
              .catch(() => {
                resolve(null)
              })
          },
          "image/jpeg",
          0.9,
        )
      } catch {
        resolve(null)
      }
    })
  }, [videoRef, ipImageRef, canvasRef])

  const getCameraDevices = useCallback(async (): Promise<MediaDeviceInfo[]> => {
    try {
      const devices = await navigator.mediaDevices.enumerateDevices()
      const videoDevices = devices.filter((device) => device.kind === "videoinput")
      setCameraDevices(videoDevices)
      return videoDevices
    } catch {
      setError("Unable to detect cameras. Ensure a camera is connected.")
      return []
    }
  }, [setError, setCameraDevices])

  useEffect(() => {
    getCameraDevices()

    // Respond to hardware changes (plugging/unplugging extra cameras)
    const handleDeviceChange = async () => {
      const refreshedDevices = await getCameraDevices()

      const activeCameraId = useCameraStore.getState().selectedCamera
      const isStreaming = useCameraStore.getState().isStreaming

      if (isStreaming && activeCameraId && activeCameraId !== IP_CAMERA_DEVICE_ID) {
        const stillExists = refreshedDevices.some((device) => device.deviceId === activeCameraId)
        if (!stillExists) {
          setError("Active camera disconnected. Select a different camera or reconnect the device.")

          if (onDeviceDisconnected) {
            onDeviceDisconnected()
          } else {
            useCameraStore.setState({ isStreaming: false, cameraActive: false })
          }
        }
      }
    }

    navigator.mediaDevices.addEventListener("devicechange", handleDeviceChange)
    return () => {
      navigator.mediaDevices.removeEventListener("devicechange", handleDeviceChange)
    }
  }, [getCameraDevices, onDeviceDisconnected, setError])

  return {
    cameraDevices,
    selectedCamera,
    setSelectedCamera,
    captureFrame,
    getCameraDevices,
  }
}
