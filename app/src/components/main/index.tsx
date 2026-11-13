import { useEffect, useRef, useCallback, useState } from "react"
import { AnimatePresence } from "framer-motion"
import { AlertTriangle } from "lucide-react"
import { attendanceManager, WebSocketService } from "@/services"
import { cctvService } from "@/services/cctvService"
import {
  useStreamState,
  useVideoStream,
  useOverlayRendering,
  useFaceDetection,
  useFaceRecognition,
  useFaceTracking,
  useAttendanceGroups,
  useBackendService,
  useCameraControl,
} from "@/components/main/hooks"
import {
  cleanupStream,
  cleanupVideo,
  cleanupAnimationFrame,
  resetLastDetectionRef,
} from "@/components/main/utils"
import {
  useCameraStore,
  useDetectionStore,
  useAttendanceStore,
  useUIStore,
} from "@/components/main/stores"
import { IP_CAMERA_DEVICE_ID } from "@/components/main/stores/cameraStore"
import { useGroupStore, useGroupUIStore } from "@/components/group/stores"
import { FloatingAlert } from "@/components/common"

import { ControlBar } from "@/components/main/components/ControlBar"
import { VideoCanvas } from "@/components/main/components/VideoCanvas"
import { Sidebar } from "@/components/main/components/Sidebar"
import { MainModals } from "@/components/main/components/MainModals"
import { CooldownOverlay } from "@/components/main/components/CooldownOverlay"
import { CctvStatusHud, type SmartCctvTab, type ViewportMode } from "@/components/cctv/CctvStatusHud"
import { SmartCctvHub } from "@/components/cctv/SmartCctvHub"
import { VLaserEditorModal, VLaserLiveCanvas } from "@/components/cctv/vlaser"
import type { DetectionResult } from "@/components/main/types"
import { soundEffects } from "@/services/SoundEffectsService"
import { consumeClockWarning, type ClockWarningDetail } from "@/services/clockWarnings"
import { getScanReadiness } from "@/components/main/utils/scanReadiness"

let globalStopCamera: ((forceCleanup: boolean) => void) | null = null

export default function Main() {
  const videoRef = useRef<HTMLVideoElement>(null)
  const ipImageRef = useRef<HTMLImageElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [showCctvHub, setShowCctvHub] = useState(false)
  const [cctvInitialTab, setCctvInitialTab] = useState<SmartCctvTab>("faculty")
  const [showVLaserModal, setShowVLaserModal] = useState(false)
  const [viewportMode, setViewportMode] = useState<ViewportMode>("split")
  const overlayCanvasRef = useRef<HTMLCanvasElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const animationFrameRef = useRef<number | undefined>(undefined)
  const webSocketServiceRef = useRef<WebSocketService | null>(null)
  const isProcessingRef = useRef<boolean>(false)
  const isStreamingRef = useRef<boolean>(false)
  const lastDetectionFrameRef = useRef<ArrayBuffer | null>(null)
  const frameCounterRef = useRef(0)
  const skipFramesRef = useRef(0)
  const trackingSessionRef = useRef(0)
  const detectionInFlightRef = useRef(false)
  const shownClockWarningKeysRef = useRef(new Set<string>())

  const lastStartTimeRef = useRef<number>(0)
  const lastStopTimeRef = useRef<number>(0)
  const isStartingRef = useRef<boolean>(false)
  const isStoppingRef = useRef<boolean>(false)

  const lastDetectionRef = useRef<DetectionResult | null>(null)
  const lastFrameTimestampRef = useRef<number>(0)
  const processCurrentFrameRef = useRef<() => Promise<void>>(async () => {})
  const previousTrackingGroupIdRef = useRef<string | null | undefined>(undefined)

  const backendServiceReadyRef = useRef(false)
  const isScanningRef = useRef(false)
  const videoRectRef = useRef<DOMRect | null>(null)
  const lastVideoRectUpdateRef = useRef<number>(0)

  const {
    isStreaming,
    isVideoLoading,
    setIsStreaming,
    setIsVideoLoading,
    setCameraActive,
    cameraDevices,
    selectedCamera,
    setSelectedCamera,
    ipCameraUrl,
    activeIpStreamUrl,
    setIpCameraUrl,
    setActiveIpStreamUrl,
  } = useCameraStore()

  const {
    currentDetections,
    trackedFaces,
    currentRecognitionResults: rawCurrentRecognitionResults,
    activeCctvCameraId,
    setActiveCctvCameraId,
  } = useDetectionStore()

  const {
    currentGroup,
    setCurrentGroup,
    attendanceGroups,
    setAttendanceGroups,
    groupMembers,
    isShellReady,
    isPanelLoading,
    isPanelSwitchPending,
    panelDataError,
    shellBootstrapError,
    setShowGroupManagement,
    attendanceCooldownSeconds,
    enableSpoofDetection,
    maxRecognitionFacesPerFrame,
    persistentCooldowns,
    timeHealth,
    setTimeHealth,
  } = useAttendanceStore()

  const {
    error,
    setError,
    success,
    setSuccess,
    warning,
    setWarning,
    showSettings,
    setShowSettings,
    requestOpenSettings,
    quickSettings,
    audioSettings,
    setSidebarCollapsed,
    pendingCloudSetup,
    setPendingCloudSetup,
    adminPinEnabled,
    isHydrated,
  } = useUIStore()
  const showAddMemberModal = useGroupUIStore((state) => state.showAddMemberModal)
  const showEditMemberModal = useGroupUIStore((state) => state.showEditMemberModal)
  const showCreateGroupModal = useGroupUIStore((state) => state.showCreateGroupModal)
  const showEditGroupModal = useGroupUIStore((state) => state.showEditGroupModal)

  const handleOpenCctvHub = useCallback((initialTab?: SmartCctvTab) => {
    setCctvInitialTab(initialTab ?? "faculty")
    setShowCctvHub(true)
  }, [])

  const handleOpenVLaser = useCallback(async () => {
    if (!activeCctvCameraId) {
      try {
        const cams = await cctvService.listCameras()
        if (cams && cams.length > 0) {
          setActiveCctvCameraId(cams[0].id)
        }
      } catch {
        // Non-critical fallback
      }
    }
    setShowVLaserModal(true)
  }, [activeCctvCameraId, setActiveCctvCameraId])

  // Auto-open Settings → Sync when user chose "Connect to Cloud" during onboarding
  const hasCheckedCloudSetupRef = useRef(false)
  useEffect(() => {
    if (!hasCheckedCloudSetupRef.current && pendingCloudSetup) {
      hasCheckedCloudSetupRef.current = true
      requestOpenSettings("remote-sync")
      setPendingCloudSetup(false)
    }
  }, [pendingCloudSetup, requestOpenSettings, setPendingCloudSetup])

  // Auto-close Settings after 60s of inactivity when Admin PIN Lock is enabled.
  // Prevents settings from being left open when an admin walks away from the kiosk.
  const inactivityTimerRef = useRef<NodeJS.Timeout | null>(null)
  useEffect(() => {
    if (!showSettings || !adminPinEnabled) {
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current)
      return
    }
    const IDLE_MS = 60_000
    const resetTimer = () => {
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current)
      inactivityTimerRef.current = setTimeout(() => {
        setShowSettings(false)
      }, IDLE_MS)
    }
    resetTimer()
    window.addEventListener("mousemove", resetTimer)
    window.addEventListener("mousedown", resetTimer)
    window.addEventListener("keydown", resetTimer)
    window.addEventListener("touchstart", resetTimer)
    return () => {
      if (inactivityTimerRef.current) clearTimeout(inactivityTimerRef.current)
      window.removeEventListener("mousemove", resetTimer)
      window.removeEventListener("mousedown", resetTimer)
      window.removeEventListener("keydown", resetTimer)
      window.removeEventListener("touchstart", resetTimer)
    }
  }, [showSettings, adminPinEnabled, setShowSettings])

  // Preload sound to minimize delay on first recognition
  useEffect(() => {
    if (audioSettings.recognitionSoundEnabled && audioSettings.recognitionSoundUrl) {
      soundEffects.preload(audioSettings.recognitionSoundUrl)
    }
  }, [audioSettings.recognitionSoundEnabled, audioSettings.recognitionSoundUrl])

  // Auto-dismiss success alerts after 5 seconds
  useEffect(() => {
    if (success) {
      const timer = setTimeout(() => {
        setSuccess(null)
      }, 5000)
      return () => clearTimeout(timer)
    }
  }, [success, setSuccess])

  // Auto-dismiss warning alerts after 8 seconds
  useEffect(() => {
    if (warning) {
      const timer = setTimeout(() => {
        setWarning(null)
      }, 8000)
      return () => clearTimeout(timer)
    }
  }, [warning, setWarning])

  const currentRecognitionResults =
    rawCurrentRecognitionResults instanceof Map ? rawCurrentRecognitionResults : new Map()

  useStreamState({
    isProcessingRef,
    animationFrameRef,
    isScanningRef,
    isStreamingRef,
    isStartingRef,
    isStoppingRef,
    lastStartTimeRef,
    lastStopTimeRef,
  })

  const { calculateAngleConsistencyRef } = useFaceTracking()

  const {
    currentGroupRef,
    memberCacheRef,
    loadAttendanceData,
    loadAttendanceDataRef,
    handleSelectGroup,
    confirmDeleteGroup,
    cancelDeleteGroup,
  } = useAttendanceGroups()

  const { captureFrame, getCameraDevices } = useVideoStream({
    videoRef,
    ipImageRef,
    canvasRef,
    isStreamingRef,
    isScanningRef,
    videoRectRef,
    lastVideoRectUpdateRef,
    isStartingRef,
    onDeviceDisconnected: useCallback(() => {
      globalStopCamera?.(false)
    }, []),
  })

  useFaceDetection({
    webSocketServiceRef,
    isScanningRef,
    isStreamingRef,
    captureFrame,
    lastDetectionFrameRef,
    frameCounterRef,
    skipFramesRef,
    lastFrameTimestampRef,
    lastDetectionRef,
    processCurrentFrameRef,
    trackingSessionRef,
    detectionInFlightRef,
  })

  const { performFaceRecognition } = useFaceRecognition({
    currentGroupRef,
    memberCacheRef,
    calculateAngleConsistencyRef,
  })

  const { animate, resetOverlayRefs } = useOverlayRendering({
    videoRef,
    ipImageRef,
    overlayCanvasRef,
    animationFrameRef,
    videoRectRef,
    lastVideoRectUpdateRef,
  })

  const stopCameraRef = useRef<((forceCleanup: boolean) => void) | null>(null)

  const { initializeWebSocket } = useBackendService({
    webSocketServiceRef,
    isStreamingRef,
    isScanningRef,
    isStartingRef,
    currentGroupId: currentGroup?.id ?? null,
    maxRecognitionFacesPerFrame,
    performFaceRecognition,
    lastFrameTimestampRef,
    lastDetectionRef,
    skipFramesRef,
    processCurrentFrameRef,
    trackingSessionRef,
    detectionInFlightRef,
    stopCamera: stopCameraRef,
    animationFrameRef,
    streamRef,
    videoRef,
    backendServiceReadyRef,
    loadAttendanceDataRef,
  })

  const { startCamera, stopCamera } = useCameraControl({
    videoRef,
    ipImageRef,
    streamRef,
    animationFrameRef,
    webSocketServiceRef,
    isStreamingRef,
    isScanningRef,
    isStartingRef,
    isStoppingRef,
    lastStartTimeRef,
    lastStopTimeRef,
    frameCounterRef,
    skipFramesRef,
    lastFrameTimestampRef,
    lastDetectionRef,
    lastDetectionFrameRef,
    backendServiceReadyRef,
    processCurrentFrameRef,
    trackingSessionRef,
    detectionInFlightRef,
    resetOverlayRefs,
    overlayCanvasRef,
    setIsStreaming,
    setIsVideoLoading,
    setCameraActive,
    setSelectedCamera,
    setError,
    selectedCamera,
    cameraDevices,
    ipCameraUrl,
    setActiveIpStreamUrl,
    initializeWebSocket,
    getCameraDevices,
  })

  useEffect(() => {
    globalStopCamera = stopCamera
    return () => {
      globalStopCamera = null
    }
  }, [stopCamera])

  const requestGroupSelection = useCallback(() => {
    setSidebarCollapsed(false)

    if (!isShellReady) {
      return
    }

    if (attendanceGroups.length === 0) {
      setShowGroupManagement(true)
      return
    }
  }, [attendanceGroups.length, isShellReady, setShowGroupManagement, setSidebarCollapsed])

  const hasCameraSource =
    cameraDevices.length > 0 ||
    (selectedCamera === IP_CAMERA_DEVICE_ID && Boolean(ipCameraUrl?.trim()))
  const scanReadiness = getScanReadiness(useAttendanceStore.getState(), hasCameraSource)
  const isGroupDataLoading = isPanelLoading || isPanelSwitchPending

  const startCameraGuarded = useCallback(() => {
    const cameraState = useCameraStore.getState()
    const hasSource =
      cameraState.cameraDevices.length > 0 ||
      (cameraState.selectedCamera === IP_CAMERA_DEVICE_ID &&
        Boolean(cameraState.ipCameraUrl?.trim()))
    const readiness = getScanReadiness(useAttendanceStore.getState(), hasSource)
    if (!readiness.canStart) {
      if (readiness.reason === "no_groups" || readiness.reason === "no_selection") {
        requestGroupSelection()
      }
      return false
    }
    void startCamera()
    return true
  }, [requestGroupSelection, startCamera])

  const handleConnectIpCamera = useCallback(
    async (url: string) => {
      const result = await cctvService.probeIpStream(url)
      if (!result.ok || !result.resolved_url) {
        throw new Error(result.message || "Could not connect to Mobile IP camera.")
      }
      setIpCameraUrl(result.resolved_url)
      setSelectedCamera(IP_CAMERA_DEVICE_ID)
      setError(null)
    },
    [setError, setIpCameraUrl, setSelectedCamera],
  )

  const handleDisconnectIpCamera = useCallback(() => {
    setActiveIpStreamUrl?.(null)
    setIpCameraUrl("")
    setError(null)
    const fallbackDevice =
      cameraDevices.find((d) => d.deviceId && d.deviceId !== IP_CAMERA_DEVICE_ID)?.deviceId ?? ""
    setSelectedCamera(fallbackDevice)
  }, [cameraDevices, setActiveIpStreamUrl, setError, setIpCameraUrl, setSelectedCamera])

  const syncUpdatedGroupLocally = useCallback(
    (updatedGroup: typeof currentGroup) => {
      setCurrentGroup(updatedGroup)

      if (!updatedGroup) {
        return
      }

      const exists = attendanceGroups.some((g) => g.id === updatedGroup.id)
      setAttendanceGroups(
        exists ?
          attendanceGroups.map((group) => (group.id === updatedGroup.id ? updatedGroup : group))
        : [...attendanceGroups, updatedGroup],
      )
      useGroupStore.getState().setSelectedGroup(updatedGroup)
    },
    [attendanceGroups, setAttendanceGroups, setCurrentGroup],
  )

  // Handle start time changes from inline chip
  const handleStartTimeChange = useCallback(
    async (newTime: string) => {
      if (!currentGroup) return

      try {
        const updatedSettings = {
          ...currentGroup.settings,
          class_start_time: newTime,
        }
        await attendanceManager.updateGroup(currentGroup.id, {
          settings: updatedSettings,
        })
        syncUpdatedGroupLocally({
          ...currentGroup,
          settings: updatedSettings,
        })
      } catch (error) {
        console.error("Failed to update start time:", error)
      }
    },
    [currentGroup, syncUpdatedGroupLocally],
  )

  const cleanupOnUnload = useCallback(() => {
    try {
      cleanupStream(streamRef)
      cleanupVideo(videoRef, true)
      cleanupAnimationFrame(animationFrameRef)

      if (webSocketServiceRef.current) {
        try {
          const wsStatus = webSocketServiceRef.current.getWebSocketStatus()
          if (wsStatus === "connected" || wsStatus === "connecting") {
            webSocketServiceRef.current.disconnect()
          }
        } catch {
          // Ignore disconnect errors
        }
      }

      isStreamingRef.current = false
      isScanningRef.current = false
      isProcessingRef.current = false
      isStartingRef.current = false
      isStoppingRef.current = false
      backendServiceReadyRef.current = false
    } catch {
      // Ignore cleanup errors
    }
  }, [])

  useEffect(() => {
    if (isStreaming) {
      animate()
    }
    return () => {
      cleanupAnimationFrame(animationFrameRef)
    }
  }, [isStreaming, animate])

  useEffect(() => {
    const currentGroupId = currentGroup?.id ?? null

    if (previousTrackingGroupIdRef.current === undefined) {
      previousTrackingGroupIdRef.current = currentGroupId
      return
    }

    if (previousTrackingGroupIdRef.current === currentGroupId) {
      return
    }

    previousTrackingGroupIdRef.current = currentGroupId

    resetLastDetectionRef(lastDetectionRef)
    useDetectionStore.getState().resetDetectionState()

    if (isStreamingRef.current) {
      stopCamera(false)
    }
  }, [currentGroup?.id, stopCamera, isStreamingRef, lastDetectionRef])

  useEffect(() => {
    let cleanupExecuted = false

    const performCleanup = () => {
      if (cleanupExecuted) return
      cleanupExecuted = true
      cleanupOnUnload()
    }

    const handleBeforeUnload = () => {
      performCleanup()
    }

    const handlePageHide = () => {
      performCleanup()
    }

    window.addEventListener("beforeunload", handleBeforeUnload, {
      capture: true,
    })
    window.addEventListener("pagehide", handlePageHide, { capture: true })

    return () => {
      window.removeEventListener("beforeunload", handleBeforeUnload, {
        capture: true,
      })
      window.removeEventListener("pagehide", handlePageHide, { capture: true })
    }
  }, [cleanupOnUnload])

  // Listen for openSettings event (e.g., from WindowFooter update notification)
  useEffect(() => {
    const handleOpenSettings = (event: CustomEvent<{ section?: string }>) => {
      const section = event.detail?.section
      requestOpenSettings(section)
    }

    window.addEventListener("openSettings", handleOpenSettings as EventListener)

    return () => {
      window.removeEventListener("openSettings", handleOpenSettings as EventListener)
    }
  }, [requestOpenSettings])

  // Listen for system clock warnings emitted by AttendanceManager
  useEffect(() => {
    const handleClockWarning = (event: CustomEvent<ClockWarningDetail>) => {
      const message = consumeClockWarning(event.detail, shownClockWarningKeysRef.current)
      if (message) {
        setWarning(message)
      }
    }

    window.addEventListener("facenox:clock-warning", handleClockWarning as unknown as EventListener)

    return () => {
      window.removeEventListener(
        "facenox:clock-warning",
        handleClockWarning as unknown as EventListener,
      )
    }
  }, [setWarning])

  useEffect(() => {
    if (!isShellReady) return

    let isCancelled = false
    let debounceTimer: number | null = null

    const loadTimeHealth = async () => {
      try {
        const health = await attendanceManager.getTimeHealth()
        if (!isCancelled) {
          setTimeHealth(health)
        }
      } catch {
        if (!isCancelled) {
          setTimeHealth(null)
        }
      }
    }

    const debouncedLoadTimeHealth = () => {
      if (debounceTimer !== null) {
        window.clearTimeout(debounceTimer)
      }
      debounceTimer = window.setTimeout(() => {
        void loadTimeHealth()
      }, 500)
    }

    // Initial load
    void loadTimeHealth()

    const interval = window.setInterval(
      () => {
        void loadTimeHealth()
      },
      5 * 60 * 1000,
    )

    const handleVisibilityChange = () => {
      if (document.visibilityState === "visible") {
        debouncedLoadTimeHealth()
      }
    }

    const handleOnline = () => {
      debouncedLoadTimeHealth()
    }

    window.addEventListener("visibilitychange", handleVisibilityChange)
    window.addEventListener("online", handleOnline)

    // Hook into pure Electron native OS wake detection
    let cleanupSystemResume: (() => void) | undefined
    if (window.facenoxElectron?.onSystemResume) {
      cleanupSystemResume = window.facenoxElectron.onSystemResume(() => {
        debouncedLoadTimeHealth()
      })
    }

    return () => {
      isCancelled = true
      window.clearInterval(interval)
      if (debounceTimer !== null) {
        window.clearTimeout(debounceTimer)
      }
      window.removeEventListener("visibilitychange", handleVisibilityChange)
      window.removeEventListener("online", handleOnline)
      if (cleanupSystemResume) cleanupSystemResume()
    }
  }, [isShellReady, setTimeHealth])

  const handleOpenTimeSettings = useCallback(() => {
    requestOpenSettings("database")
  }, [requestOpenSettings])

  // Handle auto-pause on minimize
  const wasStreamingBeforeMinimize = useRef(false)
  const wasStreamingBeforeBlockingGroupModal = useRef(false)

  useEffect(() => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const electron = (window as any).facenoxElectron
    if (!electron) return

    const cleanupMinimize = electron.onMinimize(() => {
      if (isStreamingRef.current) {
        wasStreamingBeforeMinimize.current = true
        stopCamera(false) // Pause tracking
      } else {
        wasStreamingBeforeMinimize.current = false
      }
    })

    const cleanupRestore = electron.onRestore(() => {
      if (wasStreamingBeforeMinimize.current) {
        startCameraGuarded()
        wasStreamingBeforeMinimize.current = false
      }
    })

    return () => {
      if (cleanupMinimize) cleanupMinimize()
      if (cleanupRestore) cleanupRestore()
    }
  }, [stopCamera, startCameraGuarded])

  // Auto-start scanning on launch when enabled in settings
  const hasAutoStartedOnLaunchRef = useRef(false)
  useEffect(() => {
    if (
      !scanReadiness.canStart ||
      !isHydrated ||
      hasAutoStartedOnLaunchRef.current ||
      !quickSettings.autoStartScan
    ) {
      return
    }

    if (!currentGroup) return

    if (!isStreamingRef.current) {
      if (startCameraGuarded()) hasAutoStartedOnLaunchRef.current = true
    }
  }, [
    scanReadiness.canStart,
    isHydrated,
    currentGroup,
    quickSettings.autoStartScan,
    startCameraGuarded,
  ])

  const hasBlockingGroupModalOpen =
    showAddMemberModal || showEditMemberModal || showCreateGroupModal || showEditGroupModal

  const lastEnrollmentMode = useGroupUIStore((state) => state.lastEnrollmentMode)

  useEffect(() => {
    const isBlockingActive = (hasBlockingGroupModalOpen || !!lastEnrollmentMode) && showSettings

    if (isBlockingActive) {
      if (isStreamingRef.current) {
        wasStreamingBeforeBlockingGroupModal.current = true
        stopCamera(false)
      }
    } else {
      if (wasStreamingBeforeBlockingGroupModal.current) {
        startCameraGuarded()
        wasStreamingBeforeBlockingGroupModal.current = false
      }
    }
  }, [hasBlockingGroupModalOpen, lastEnrollmentMode, showSettings, startCameraGuarded, stopCamera])

  const hasEnrolledFaces = groupMembers.length > 0 && groupMembers.some((m) => m.has_face_data)

  // Keyboard shortcut: Space toggles Start/Stop Scan
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      const activeEl = document.activeElement
      const isInput =
        activeEl &&
        (activeEl.tagName === "INPUT" ||
          activeEl.tagName === "TEXTAREA" ||
          activeEl.tagName === "SELECT" ||
          (activeEl as HTMLElement).isContentEditable)

      if (isInput || showSettings || hasBlockingGroupModalOpen || showCctvHub) {
        return
      }

      if (e.code === "Space") {
        e.preventDefault()
        if (isStreamingRef.current) {
          stopCamera(false)
        } else {
          startCameraGuarded()
        }
      }
    }

    window.addEventListener("keydown", handleKeyDown)
    return () => window.removeEventListener("keydown", handleKeyDown)
  }, [hasBlockingGroupModalOpen, showCctvHub, showSettings, startCameraGuarded, stopCamera])

  return (
    <div className="flex h-full flex-col overflow-hidden bg-[var(--bg-primary)] text-white">
      {!showSettings && timeHealth?.online_verification_status === "drift_detected" && (
        <div className="pointer-events-none absolute top-3 left-1/2 z-90 -translate-x-1/2">
          <button
            type="button"
            onClick={handleOpenTimeSettings}
            className="pointer-events-auto inline-flex items-center gap-2 rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1.5 text-[11px] font-medium text-amber-300/90 shadow-lg transition-all hover:bg-amber-500/15 hover:text-amber-200"
            aria-label="Open device time settings">
            <AlertTriangle className="size-3 text-amber-400" />
            Device time needs attention
          </button>
        </div>
      )}

      {/* Floating Alert System */}
      <div className="pointer-events-none absolute bottom-12 left-1/2 z-100 flex w-full -translate-x-1/2 flex-col items-center px-4">
        <AnimatePresence>
          {success && (
            <FloatingAlert message={success} variant="success" onDismiss={() => setSuccess(null)} />
          )}

          {warning && (
            <FloatingAlert message={warning} variant="warning" onDismiss={() => setWarning(null)} />
          )}

          {error && (
            <FloatingAlert message={error} variant="error" onDismiss={() => setError(null)} />
          )}
        </AnimatePresence>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="relative flex min-h-0 flex-1 flex-col p-3">
            <CctvStatusHud
              isStreaming={isStreaming}
              onOpenHub={handleOpenCctvHub}
              onOpenVLaser={handleOpenVLaser}
              viewportMode={viewportMode}
              onChangeViewportMode={setViewportMode}
            />

            <div className="relative flex min-h-0 flex-1 w-full gap-3 pt-12">
              {/* Window 1: Original Camera Footage with Biometrics & Overlays */}
              <div
                className={`relative min-h-0 h-full overflow-hidden rounded-xl border border-white/10 bg-black/40 transition-all ${
                  viewportMode === "camera"
                    ? "flex flex-1 w-full"
                    : viewportMode === "split"
                      ? "flex flex-1 w-1/2"
                      : "hidden"
                }`}>
                <div className="pointer-events-none absolute top-2.5 left-3 z-30 flex items-center gap-2 rounded-lg border border-white/10 bg-[#0c1017]/90 px-2.5 py-1 text-[11px] font-semibold text-white/90 shadow-lg backdrop-blur-md">
                  <span
                    className={`size-2 rounded-full ${
                      isStreaming
                        ? "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)] animate-pulse"
                        : "bg-white/30"
                    }`}
                  />
                  <span className="tracking-wide">Camera Footage</span>
                  {selectedCamera?.label && (
                    <span className="max-w-[140px] truncate text-[10px] text-cyan-300/70 border-l border-white/15 pl-1.5 font-mono">
                      {selectedCamera.label}
                    </span>
                  )}
                </div>

                <VideoCanvas
                  videoRef={videoRef}
                  ipImageRef={ipImageRef}
                  activeIpStreamUrl={activeIpStreamUrl}
                  canvasRef={canvasRef}
                  overlayCanvasRef={overlayCanvasRef}
                  quickSettings={quickSettings}
                  isVideoLoading={isVideoLoading}
                  isStreaming={isStreaming}
                  isShellReady={isShellReady}
                  isGroupDataLoading={isGroupDataLoading}
                  dataError={shellBootstrapError || panelDataError}
                  hasSelectedGroup={Boolean(currentGroup)}
                  hasEnrolledFaces={hasEnrolledFaces}
                  hasGroups={attendanceGroups.length > 0}
                  hasMembers={groupMembers.length > 0}
                  lateTrackingEnabled={!!currentGroup?.settings?.late_threshold_enabled}
                  classStartTime={currentGroup?.settings?.class_start_time}
                  onStartTimeChange={handleStartTimeChange}
                  currentGroup={currentGroup}
                  enableSpoofDetection={enableSpoofDetection}
                  maxRecognitionFacesPerFrame={maxRecognitionFacesPerFrame}
                />

                {/* Cooldown Overlay */}
                <CooldownOverlay
                  persistentCooldowns={persistentCooldowns}
                  attendanceCooldownSeconds={attendanceCooldownSeconds}
                />
              </div>

              {/* Window 2: V-LASER Spatial Digital Twin & Continuous Movement Tracking */}
              <div
                className={`relative min-h-0 h-full overflow-hidden rounded-xl border border-cyan-500/20 bg-[#070d12]/90 shadow-2xl transition-all ${
                  viewportMode === "vlaser"
                    ? "flex flex-1 w-full"
                    : viewportMode === "split"
                      ? "flex flex-1 w-1/2"
                      : "hidden"
                }`}>
                <VLaserLiveCanvas
                  cameraId={activeCctvCameraId || "cam-main-1"}
                  cameraName={selectedCamera?.label || "Live Camera"}
                  classroom={currentGroup?.name}
                  isStreaming={isStreaming}
                  onOpenEditor={handleOpenVLaser}
                />
              </div>
            </div>
          </div>

          <ControlBar
            cameraDevices={cameraDevices}
            selectedCamera={selectedCamera}
            setSelectedCamera={setSelectedCamera}
            isStreaming={isStreaming}
            startCamera={startCameraGuarded}
            stopCamera={stopCamera}
            readiness={scanReadiness}
            ipCameraUrl={ipCameraUrl}
            onConnectIpCamera={handleConnectIpCamera}
            onDisconnectIpCamera={handleDisconnectIpCamera}
          />
        </div>

        <Sidebar
          currentDetections={currentDetections}
          currentRecognitionResults={currentRecognitionResults}
          recognitionEnabled={true}
          trackedFaces={trackedFaces}
          isStreaming={isStreaming}
          isVideoLoading={isVideoLoading}
          handleSelectGroup={handleSelectGroup}
          refreshAttendanceData={loadAttendanceData}
        />
      </div>

      <MainModals
        confirmDeleteGroup={confirmDeleteGroup}
        cancelDeleteGroup={cancelDeleteGroup}
        loadAttendanceDataRef={loadAttendanceDataRef}
        streamRef={streamRef}
      />

      <SmartCctvHub
        isOpen={showCctvHub}
        initialTab={cctvInitialTab}
        onClose={() => setShowCctvHub(false)}
      />

      {showVLaserModal && (
        <VLaserEditorModal
          cameraId={activeCctvCameraId || "cam-main-1"}
          cameraName={
            activeCctvCameraId ?
              `CCTV Camera (${activeCctvCameraId})`
            : "Classroom Main CCTV Camera"
          }
          classroom={currentGroup?.name || "Classroom"}
          isOpen={showVLaserModal}
          onClose={() => setShowVLaserModal(false)}
        />
      )}
    </div>
  )
}
