import { useState, useEffect, useMemo, useCallback } from "react"
import { AlertCircle, Camera, Check, Image, X } from "lucide-react"
import { useGroupUIStore } from "@/components/group/stores"
import { Modal } from "@/components/common"
import { ErrorText } from "@/components/common/ErrorText"
import { motion, AnimatePresence } from "framer-motion"
import type { AttendanceGroup, AttendanceMember } from "@/types/recognition"
import { useCamera } from "@/components/group/sections/enrollment/hooks/useCamera"
import { useFaceCapture } from "@/components/group/sections/enrollment/hooks/useFaceCapture"
import { useDialog, Tooltip } from "@/components/shared"
import { CameraFeed } from "@/components/group/sections/enrollment/components/CameraFeed"
import { UploadArea } from "@/components/group/sections/enrollment/components/UploadArea"
import { ResultView } from "@/components/group/sections/enrollment/components/ResultView"
import { FaceAlignmentOverlay } from "@/components/group/sections/enrollment/components/FaceAlignmentOverlay"
import { AngleProgressStrip } from "@/components/group/sections/enrollment/components/AngleProgressStrip"
import { useLiveFaceAlignment } from "@/components/group/sections/enrollment/hooks/useLiveFaceAlignment"
import {
  areAllRequiredAnglesCollected,
  ENROLLMENT_ANGLE_STEPS,
  isValidCapturedFrame,
  type EnrollmentAngleKey,
} from "@/components/group/sections/enrollment/enrollmentAngles"
import { useUIStore } from "@/components/main/stores"
import { EnrollmentInfoModal } from "@/components/group/sections/enrollment/components/EnrollmentInfoModal"
import type { CaptureSource } from "./types"

interface FaceCaptureProps {
  group: AttendanceGroup
  members: AttendanceMember[]
  onRefresh: () => void
  initialSource?: CaptureSource
  deselectMemberTrigger?: number
  onHasSelectedMemberChange?: (hasSelectedMember: boolean) => void
}

export function FaceCapture({
  group,
  members,
  onRefresh,
  initialSource,
  deselectMemberTrigger,
  onHasSelectedMemberChange: onSelectedMemberChange,
}: FaceCaptureProps) {
  const dialog = useDialog()

  const preSelectedId = useGroupUIStore((state) => state.preSelectedMemberId)
  const resetEnrollment = useGroupUIStore((state) => state.resetEnrollment)

  const [source, setSource] = useState<CaptureSource>(initialSource ?? "live")
  const [selectedMemberId, setSelectedMemberId] = useState(preSelectedId ?? "")

  const enrollmentInfoDismissed = useUIStore((state) => state.enrollmentInfoDismissed)
  const setEnrollmentInfoDismissed = useUIStore((state) => state.setEnrollmentInfoDismissed)
  const [showInfoModal, setShowInfoModal] = useState(false)
  const [dontShowAgainChecked, setDontShowAgainChecked] = useState(false)
  const [successCountdown, setSuccessCountdown] = useState<number | null>(null)

  const memberStatus = useMemo(() => {
    const status = new Map<string, boolean>()
    for (const member of members) {
      status.set(member.person_id, !!member.has_face_data)
    }
    return status
  }, [members])

  const {
    videoRef,
    isStreaming,
    isVideoReady,
    cameraError,
    cameraDevices,
    selectedCamera,
    setSelectedCamera,
    startCamera,
    stopCamera,
  } = useCamera()

  const {
    frames,
    currentAngle,
    setCurrentAngle,
    isEnrolling,
    successMessage,
    globalError,
    setSuccessMessage,
    setGlobalError,
    captureProcessedFrame,
    handleEnroll,
    resetFrames,
    removeAngleFrame,
  } = useFaceCapture(group, members, onRefresh, dialog)

  const [autoCaptureEnabled, setAutoCaptureEnabled] = useState(true)
  const framesReady = areAllRequiredAnglesCollected(frames)
  const completedAngles = useMemo(
    () =>
      frames
        .filter((f) => isValidCapturedFrame(f) && f.angle)
        .map((f) => f.angle as EnrollmentAngleKey),
    [frames],
  )
  const isProcessing = frames.some((f) => f.status === "processing")
  const visibleError = globalError || (source === "live" ? cameraError : null)

  const handleCaptureForAngle = useCallback(
    (angleToCapture: EnrollmentAngleKey) => {
      if (!videoRef.current || !selectedMemberId) return
      if (!videoRef.current.videoWidth || !videoRef.current.videoHeight) {
        setGlobalError("Camera stream interrupted or not ready. Please check your camera.")
        return
      }
      const canvas = document.createElement("canvas")
      canvas.width = videoRef.current.videoWidth
      canvas.height = videoRef.current.videoHeight
      const ctx = canvas.getContext("2d")
      if (!ctx) return

      // Flip the capture to match the mirrored video preview
      ctx.translate(canvas.width, 0)
      ctx.scale(-1, 1)

      ctx.drawImage(videoRef.current, 0, 0)
      const url = canvas.toDataURL("image/jpeg", 0.95)
      void captureProcessedFrame(angleToCapture, url, canvas.width, canvas.height)
    },
    [videoRef, selectedMemberId, captureProcessedFrame, setGlobalError],
  )

  const handleCaptureFromCamera = useCallback(() => {
    handleCaptureForAngle(currentAngle)
  }, [handleCaptureForAngle, currentAngle])

  const liveAlignmentActive =
    source === "live" &&
    Boolean(selectedMemberId) &&
    !showInfoModal &&
    isStreaming &&
    isVideoReady &&
    !framesReady &&
    !successMessage &&
    !cameraError

  const { alignment } = useLiveFaceAlignment({
    videoRef,
    isActive: liveAlignmentActive,
    targetAngle: currentAngle,
    mirrored: true,
    autoCaptureEnabled,
    autoCapturePaused: isProcessing || isEnrolling,
    onAutoCaptureReady: handleCaptureForAngle,
  })

  useEffect(() => {
    if (source !== "live" || !selectedMemberId || showInfoModal || framesReady || successMessage) {
      stopCamera()
    }
  }, [source, selectedMemberId, showInfoModal, framesReady, successMessage, stopCamera])

  // Trigger modal on member select if not already dismissed
  useEffect(() => {
    if (selectedMemberId && !enrollmentInfoDismissed) {
      setShowInfoModal(true)
      setDontShowAgainChecked(false)
    } else {
      setShowInfoModal(false)
    }
  }, [selectedMemberId, enrollmentInfoDismissed])

  useEffect(() => {
    let active = true
    if (
      source === "live" &&
      selectedMemberId &&
      !showInfoModal &&
      !isStreaming &&
      !cameraError &&
      !framesReady &&
      !successMessage
    ) {
      const timer = setTimeout(() => {
        if (active) startCamera()
      }, 100)
      return () => clearTimeout(timer)
    }
    return () => {
      active = false
    }
  }, [
    source,
    selectedMemberId,
    showInfoModal,
    isStreaming,
    cameraError,
    framesReady,
    successMessage,
    startCamera,
  ])

  useEffect(() => {
    if (onSelectedMemberChange) {
      onSelectedMemberChange(!!selectedMemberId)
    }
  }, [selectedMemberId, onSelectedMemberChange])

  useEffect(() => {
    setGlobalError(null)
  }, [selectedMemberId, setGlobalError])

  useEffect(() => {
    if (deselectMemberTrigger) {
      setTimeout(() => setSelectedMemberId(""), 0)
    }
  }, [deselectMemberTrigger])

  // Start countdown when successMessage is set
  useEffect(() => {
    if (successMessage) {
      setSuccessCountdown(3)
    } else {
      setSuccessCountdown(null)
    }
  }, [successMessage])

  // Count down every second and auto-dismiss on 0
  useEffect(() => {
    if (successCountdown === null) return
    if (successCountdown <= 0) {
      setSuccessMessage(null)
      setSelectedMemberId("")
      resetFrames()
      resetEnrollment()
      return
    }
    const timer = setTimeout(() => {
      setSuccessCountdown((prev) => (prev !== null ? prev - 1 : null))
    }, 1000)
    return () => clearTimeout(timer)
  }, [successCountdown, setSuccessMessage, setSelectedMemberId, resetFrames, resetEnrollment])

  const handleWrapperEnroll = useCallback(async () => {
    if (!selectedMemberId) return
    await handleEnroll(selectedMemberId, async () => {}, memberStatus)
  }, [selectedMemberId, handleEnroll, memberStatus])

  const resetWorkflow = useCallback(() => {
    resetFrames()
    if (source === "live" && !showInfoModal) {
      startCamera()
    }
  }, [resetFrames, source, startCamera, showInfoModal])

  const handleRetakeSingleAngle = useCallback(
    (angle: EnrollmentAngleKey) => {
      removeAngleFrame(angle)
      if (source === "live" && !showInfoModal && !isStreaming) {
        startCamera()
      }
    },
    [removeAngleFrame, source, showInfoModal, isStreaming, startCamera],
  )

  const handleConfirmInfoModal = useCallback(() => {
    if (dontShowAgainChecked) {
      setEnrollmentInfoDismissed(true)
    }
    setShowInfoModal(false)
  }, [dontShowAgainChecked, setEnrollmentInfoDismissed])

  const handleCloseInfoModal = useCallback(() => {
    setShowInfoModal(false)
    setSelectedMemberId("")
    resetEnrollment()
  }, [resetEnrollment])

  useEffect(() => {
    const handleKeyPress = (e: KeyboardEvent) => {
      if (!selectedMemberId) return

      if (e.key === " " || e.key === "Space") {
        if (source === "live" && isStreaming && isVideoReady && !isProcessing) {
          e.preventDefault()
          handleCaptureFromCamera()
        }
      } else if (e.key === "r" || e.key === "R") {
        if (framesReady) {
          e.preventDefault()
          resetWorkflow()
        }
      } else if (e.key === "Enter") {
        if (framesReady && !isEnrolling) {
          e.preventDefault()
          void handleWrapperEnroll()
        }
      } else if (e.key === "Escape") {
        e.preventDefault()
        e.stopImmediatePropagation()
        setSelectedMemberId("")
        resetEnrollment()
      }
    }

    window.addEventListener("keydown", handleKeyPress, true)
    return () => window.removeEventListener("keydown", handleKeyPress, true)
  }, [
    selectedMemberId,
    source,
    isStreaming,
    isVideoReady,
    isProcessing,
    framesReady,
    isEnrolling,
    handleCaptureFromCamera,
    resetWorkflow,
    handleWrapperEnroll,
    resetEnrollment,
  ])

  const selectedMemberName = useMemo(() => {
    const m = members.find((m) => m.person_id === selectedMemberId)
    return m ? m.name || "Member" : ""
  }, [members, selectedMemberId])

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <Modal
        isOpen={!!successMessage}
        onClose={() => {
          setSuccessMessage(null)
          setSelectedMemberId("")
          resetFrames()
          // Close the overlay entirely — go back to the main members list
          resetEnrollment()
        }}
        title="Success"
        maxWidth="sm"
        hideCloseButton={true}>
        <div className="flex flex-col items-center gap-3 py-2">
          <Check className="size-8 text-cyan-400" />
          <p className="text-center text-sm font-medium text-white/85">{successMessage}</p>

          <div className="mt-6 flex w-full items-center justify-between">
            {/* Subtle countdown text on the left */}
            <div className="flex items-center gap-1 text-[10px] font-medium text-white/30 select-none">
              <span>Closing in</span>
              <span className="font-bold text-white/50 tabular-nums">{successCountdown}s</span>
            </div>

            <button
              onClick={() => {
                setSuccessMessage(null)
                setSelectedMemberId("")
                resetFrames()
                // Close the overlay entirely — go back to the main members list
                resetEnrollment()
              }}
              className="rounded-lg border border-cyan-500/30 bg-cyan-500/20 px-5 py-1.5 text-[11px] font-bold tracking-wider text-cyan-400 transition-all hover:bg-cyan-500/30">
              Done
            </button>
          </div>
        </div>
      </Modal>

      <EnrollmentInfoModal
        isOpen={showInfoModal}
        dontShowAgain={dontShowAgainChecked}
        onClose={handleCloseInfoModal}
        onConfirm={handleConfirmInfoModal}
        onDontShowAgainChange={setDontShowAgainChecked}
      />

      <div className="relative min-h-0 flex-1 overflow-hidden">
        <AnimatePresence mode="wait">
          {!selectedMemberId ?
            <motion.div
              key="select-member"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -6 }}
              transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
              className="absolute inset-0 flex items-center justify-center">
              <div className="text-center text-xs font-medium text-white/55">
                Select a member to begin enrollment
              </div>
            </motion.div>
          : <motion.div
              key="camera-viewport"
              initial={{ opacity: 0, scale: 0.96 }}
              animate={{ opacity: 1, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{ duration: 0.22, ease: "easeOut" }}
              className="absolute inset-0 flex flex-col items-center justify-center gap-4 overflow-hidden p-6">
              <div className="flex w-full max-w-4xl items-center justify-between px-1">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-[10px] font-bold tracking-[0.15em] text-cyan-400/80 uppercase">
                    Member
                  </span>
                  <h2 className="truncate text-base font-bold tracking-tight text-white sm:text-lg">
                    {selectedMemberName}
                  </h2>
                </div>
                <div className="flex items-center gap-3 text-[11px] font-medium text-white/65">
                  <span>
                    Angle{" "}
                    <strong className="text-cyan-300">
                      {completedAngles.length}/{ENROLLMENT_ANGLE_STEPS.length}
                    </strong>{" "}
                    collected
                  </span>
                  {source === "live" && !framesReady && (
                    <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-white/65">
                      <input
                        type="checkbox"
                        checked={autoCaptureEnabled}
                        onChange={(e) => setAutoCaptureEnabled(e.target.checked)}
                        className="h-3.5 w-3.5 rounded border-white/20 bg-transparent accent-cyan-500"
                      />
                      Auto-capture
                    </label>
                  )}
                </div>
              </div>

              <div className="relative aspect-video min-h-0 w-full max-w-4xl shrink overflow-hidden rounded-xl border border-white/10">
                {!framesReady ?
                  source === "live" ?
                    <CameraFeed
                      videoRef={videoRef}
                      isStreaming={isStreaming}
                      isVideoReady={isVideoReady}
                      onStart={startCamera}
                      onStop={stopCamera}
                      source={source}
                      cameraDevices={cameraDevices}
                      selectedCamera={selectedCamera}
                      setSelectedCamera={setSelectedCamera}>
                      {isStreaming && isVideoReady && (
                        <FaceAlignmentOverlay
                          alignment={alignment}
                          currentAngle={currentAngle}
                          completedAngles={completedAngles}
                          videoWidth={videoRef.current?.videoWidth || 640}
                          videoHeight={videoRef.current?.videoHeight || 480}
                          objectMode="contain"
                        />
                      )}
                    </CameraFeed>
                  : <UploadArea
                      onFileProcessed={(url: string, w: number, h: number) =>
                        void captureProcessedFrame(currentAngle, url, w, h, {
                          enforceAlignment: true,
                        })
                      }
                      onError={setGlobalError}
                    />

                : <ResultView
                    frames={frames}
                    selectedMemberName={selectedMemberName}
                    onRetake={resetWorkflow}
                    onRetakeAngle={handleRetakeSingleAngle}
                    onEnroll={handleWrapperEnroll}
                    isEnrolling={isEnrolling}
                    framesReady={!!framesReady}
                  />
                }

                {/* Sleek, non-blocking glassmorphic warning toast inside single viewport */}
                <AnimatePresence>
                  {visibleError && (
                    <motion.div
                      role="alert"
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      transition={{ duration: 0.22, ease: "easeOut" }}
                      className="pointer-events-auto absolute bottom-4 left-1/2 z-20 flex max-w-[85%] -translate-x-1/2 items-center gap-2 rounded-lg border border-red-500/30 bg-red-950/85 px-4 py-2.5 text-center text-[11px] font-medium text-red-200">
                      <AlertCircle className="size-4 shrink-0 text-red-400" />
                      <ErrorText message={visibleError} />
                      {!globalError && cameraError ?
                        <button
                          type="button"
                          onClick={() => void startCamera()}
                          className="shrink-0 rounded px-2 py-1 text-white hover:bg-white/10 focus-visible:outline focus-visible:outline-2">
                          Retry camera
                        </button>
                      : <button
                          type="button"
                          aria-label="Dismiss error"
                          onClick={() => setGlobalError(null)}
                          className="shrink-0 rounded p-1 hover:bg-white/10 focus-visible:outline focus-visible:outline-2">
                          <X className="size-4" aria-hidden="true" />
                        </button>
                      }
                    </motion.div>
                  )}
                </AnimatePresence>
              </div>

              {/* 5-Angle Guided Progress Strip */}
              {!framesReady && (
                <div className="w-full max-w-4xl">
                  <AngleProgressStrip
                    frames={frames}
                    activeAngle={currentAngle}
                    onSelectAngle={setCurrentAngle}
                    onRetakeAngle={handleRetakeSingleAngle}
                    disabled={isProcessing || isEnrolling}
                  />
                </div>
              )}

              {/* Bottom Control Bar */}
              {!framesReady && (
                <div className="flex w-full max-w-4xl items-center justify-between px-4">
                  <div className="w-32">
                    <Tooltip
                      content={source === "live" ? "Switch to file upload" : "Switch to camera"}>
                      <button
                        onClick={() => setSource(source === "live" ? "upload" : "live")}
                        className="group flex items-center justify-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-2 text-[11px] font-medium text-white/65 transition-all hover:border-white/20 hover:bg-white/10 hover:text-white"
                        aria-label={
                          source === "live" ? "Switch to file upload" : "Switch to camera"
                        }>
                        {source === "live" ?
                          <Image className="size-4" />
                        : <Camera className="size-4" />}
                        <span>{source === "live" ? "Upload" : "Camera"}</span>
                      </button>
                    </Tooltip>
                  </div>

                  <div className="flex flex-1 justify-center">
                    {source === "live" && isStreaming && (
                      <Tooltip content="Capture photo">
                        <span className="inline-flex shrink-0">
                          <button
                            onClick={handleCaptureFromCamera}
                            disabled={!isVideoReady || !!cameraError || isProcessing}
                            className="group flex h-16 w-16 items-center justify-center rounded-full bg-white/10 p-1 transition-all hover:bg-white/20 disabled:cursor-not-allowed disabled:opacity-40"
                            aria-label="Capture photo">
                            {isProcessing ?
                              <div className="h-8 w-8 animate-spin rounded-full border-2 border-white/20 border-t-white" />
                            : <div className="h-full w-full rounded-full bg-white shadow-[0_0_15px_rgba(255,255,255,0.3)] transition-transform group-active:scale-90" />
                            }
                          </button>
                        </span>
                      </Tooltip>
                    )}
                  </div>

                  {/* Empty div for right side balance */}
                  <div className="flex w-32 items-center justify-end">
                    <div className="flex flex-col items-end gap-1 text-[9px] leading-tight font-medium text-white/45">
                      <div className="flex items-center gap-1">
                        <kbd className="rounded bg-white/10 px-1 py-0.5 text-white/65">Space</kbd>
                        <span>Capture</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <kbd className="rounded bg-white/10 px-1 py-0.5 text-white/65">R</kbd>
                        <span>Retake</span>
                      </div>
                    </div>
                  </div>
                </div>
              )}
            </motion.div>
          }
        </AnimatePresence>
      </div>
    </div>
  )
}
