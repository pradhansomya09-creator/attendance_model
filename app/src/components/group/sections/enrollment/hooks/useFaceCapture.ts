import { useState, useCallback, useEffect } from "react"
import { attendanceManager, backendService } from "@/services"
import type { AttendanceGroup, AttendanceMember } from "@/types/recognition"
import type { DialogAPI } from "@/components/shared"
import type { CapturedFrame } from "@/components/group/sections/enrollment/types"
import { makeId } from "@/utils/imageHelpers"
import { dataUrlToBlob } from "@/utils/dataUrl"
import { isTechnicalErrorMessage } from "@/utils/errorText"
import { validateAndGetBestFace } from "@/utils/faceValidation"
import {
  areAllRequiredAnglesCollected,
  ENROLLMENT_ANGLE_STEPS,
  getCollectedAngleCount,
  getNextMissingAngle,
  isValidCapturedFrame,
  type EnrollmentAngleKey,
} from "../enrollmentAngles"

export function useFaceCapture(
  group: AttendanceGroup | null,
  members: AttendanceMember[],
  onRefresh?: () => Promise<void> | void,
  dialog?: Pick<DialogAPI, "confirm">,
) {
  const [frames, setFrames] = useState<CapturedFrame[]>([])
  const [currentAngle, setCurrentAngle] = useState<EnrollmentAngleKey>("front")
  const [globalError, setGlobalError] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [isEnrolling, setIsEnrolling] = useState(false)

  // Clear routine errors after a few seconds, but leave diagnostics visible
  // until the operator dismisses or replaces them.
  useEffect(() => {
    if (globalError && !isTechnicalErrorMessage(globalError)) {
      const timer = setTimeout(() => setGlobalError(null), 3500)
      return () => clearTimeout(timer)
    }
  }, [globalError])

  const resetFrames = useCallback(() => {
    setFrames([])
    setCurrentAngle("front")
  }, [])

  const removeAngleFrame = useCallback((angle: EnrollmentAngleKey) => {
    setFrames((prev) => prev.filter((f) => f.angle !== angle))
    setCurrentAngle(angle)
    setGlobalError(null)
  }, [])

  const updateFrame = useCallback(
    (frameId: string, updater: (frame: CapturedFrame) => CapturedFrame) => {
      setFrames((prev) => prev.map((frame) => (frame.id === frameId ? updater(frame) : frame)))
    },
    [],
  )

  const captureProcessedFrame = useCallback(
    async (
      angle: string,
      dataUrl: string,
      width: number,
      height: number,
      options?: { enforceAlignment?: boolean },
    ) => {
      const canonicalAngle = (
        ENROLLMENT_ANGLE_STEPS.some((s) => s.angle === angle)
          ? angle
          : "front"
      ) as EnrollmentAngleKey
      const id = makeId()

      setGlobalError(null)
      setSuccessMessage(null)

      // Replace any previous capture for this slot
      setFrames((prev) => [
        ...prev.filter((frame) => frame.angle !== canonicalAngle),
        {
          id,
          angle: canonicalAngle,
          label:
            ENROLLMENT_ANGLE_STEPS.find((s) => s.angle === canonicalAngle)?.label ||
            canonicalAngle,
          dataUrl,
          width,
          height,
          status: "processing",
        },
      ])

      try {
        const blob = dataUrlToBlob(dataUrl)

        const detection = await backendService.detectFaces(blob, {
          model_type: "face_detector",
          enableLiveness: false, // Enrollment should not enforce liveness
          includeAlignment: true,
          targetAngle: canonicalAngle,
          mirrored: false,
        })

        const bestFace = validateAndGetBestFace(detection)

        if (
          options?.enforceAlignment !== false &&
          detection.alignment &&
          !detection.alignment.ready
        ) {
          throw new Error(
            detection.alignment.guidance ||
              `Please align your face clearly for ${canonicalAngle.replace("_", " ")}.`,
          )
        }

        const updatedSnapshot: CapturedFrame[] = []
        setFrames((prev) => {
          const next = prev.map((frame) => {
            if (frame.id !== id) return frame
            return {
              ...frame,
              status: "ready" as const,
              confidence: bestFace.confidence,
              bbox: bestFace.bbox,
              landmarks_5: bestFace.landmarks_5,
              error: undefined,
            }
          })
          updatedSnapshot.push(...next)
          return next
        })

        // Advance to next missing angle automatically
        const nextMissing = getNextMissingAngle(updatedSnapshot, canonicalAngle)
        setCurrentAngle(nextMissing)
        return true
      } catch (error) {
        const message =
          error instanceof Error ? error.message : "Could not check the photo. Try again."
        setFrames((prev) => prev.filter((frame) => frame.id !== id))
        setGlobalError(message)
        return false
      }
    },
    [],
  )

  const handleEnroll = useCallback(
    async (
      selectedMemberId: string,
      loadMemberStatus: () => Promise<void>,
      memberStatus: Map<string, boolean>,
    ) => {
      if (!group) {
        setGlobalError("No group selected.")
        return
      }

      if (!areAllRequiredAnglesCollected(frames)) {
        const collected = getCollectedAngleCount(frames)
        setGlobalError(
          `Collect all 5 distinct face angles before completing enrollment (${collected}/5 collected).`,
        )
        return
      }

      const orderedFrames = ENROLLMENT_ANGLE_STEPS.map((step) =>
        frames.find((f) => f.angle === step.angle && isValidCapturedFrame(f)),
      ).filter((f): f is CapturedFrame => Boolean(f))

      if (orderedFrames.length < ENROLLMENT_ANGLE_STEPS.length) {
        setGlobalError("All 5 distinct face angle captures are required before enrolling.")
        return
      }

      setIsEnrolling(true)
      setGlobalError(null)
      setSuccessMessage(null)

      try {
        const payload = orderedFrames.map((frame) => {
          if (frame.landmarks_5?.length !== 5 || !frame.bbox || !frame.angle) {
            throw new Error(
              "Facial features could not be detected for all 5 angles. Please retake affected captures.",
            )
          }
          return {
            angle: frame.angle,
            imageData: dataUrlToBlob(frame.dataUrl),
            bbox: frame.bbox,
            landmarks_5: frame.landmarks_5,
            mirrored: false,
          }
        })

        const result = await attendanceManager.enrollFaceMultiAngle(
          group.id,
          selectedMemberId,
          payload,
          { mirrored: false },
        )

        if (!result.success) {
          throw new Error(result.error || "Multi-angle enrollment failed.")
        }

        // Mark enrolled then clear temporary raw camera image data URLs from local state
        setFrames((prev) =>
          prev.map((current) => ({
            ...current,
            status: "enrolled",
            dataUrl: "",
          })),
        )

        const isAlreadyEnrolled = memberStatus.get(selectedMemberId) ?? false
        const member = members.find((m) => m.person_id === selectedMemberId)
        const memberName = member?.name || "Member"

        setSuccessMessage(
          isAlreadyEnrolled ? `${memberName} re-enrolled.` : `${memberName} enrolled.`,
        )

        await loadMemberStatus()
        if (onRefresh) await onRefresh()

        // Trigger immediate sync so other paired devices receive the new embedding
        try {
          if (window.electronAPI?.sync?.triggerNow) {
            window.electronAPI.sync.triggerNow().catch(() => {})
          }
        } catch {
          // Sync trigger is best-effort
        }
      } catch (error) {
        const message = error instanceof Error ? error.message : "Enrollment failed. Try again."
        setGlobalError(message)
      } finally {
        setIsEnrolling(false)
      }
    },
    [group, frames, members, onRefresh],
  )

  const handleRemoveFaceData = useCallback(
    async (
      member: AttendanceMember & { displayName?: string },
      loadMemberStatus: () => Promise<void>,
    ) => {
      if (!group) return

      const displayName = member.displayName || member.name

      if (dialog) {
        const ok = await dialog.confirm({
          title: "Remove face enrollment",
          message: `Remove face enrollment for ${displayName}? They will need to re-enroll to be recognized.`,
          confirmText: "Remove",
          cancelText: "Cancel",
          confirmVariant: "danger",
        })
        if (!ok) return
      } else {
        const confirmation = window.confirm(
          `Remove face enrollment for ${displayName}? They will need to re-enroll to be recognized.`,
        )
        if (!confirmation) return
      }

      try {
        const result = await attendanceManager.removeFaceDataForGroupPerson(
          group.id,
          member.person_id,
        )
        if (!result.success) {
          throw new Error(result.error || "Could not remove face enrollment.")
        }
        await loadMemberStatus()
        if (onRefresh) await onRefresh()
        setSuccessMessage(`Face enrollment removed for ${displayName}.`)
      } catch (error) {
        const message = error instanceof Error ? error.message : "Failed to remove face data."
        setGlobalError(message)
      }
    },
    [group, onRefresh, dialog],
  )

  return {
    frames,
    currentAngle,
    setCurrentAngle,
    globalError,
    successMessage,
    isEnrolling,
    setGlobalError,
    setSuccessMessage,
    resetFrames,
    removeAngleFrame,
    captureProcessedFrame,
    handleEnroll,
    handleRemoveFaceData,
  }
}
