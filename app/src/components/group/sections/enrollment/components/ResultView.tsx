import { useState } from "react"
import type { CapturedFrame } from "@/components/group/sections/enrollment/types"
import { ImagePreviewWithBbox } from "@/components/group/sections/enrollment/components/ImagePreviewWithBbox"
import {
  ENROLLMENT_ANGLE_STEPS,
  getCollectedAngleCount,
  type EnrollmentAngleKey,
} from "@/components/group/sections/enrollment/enrollmentAngles"

interface ResultViewProps {
  frames: CapturedFrame[]
  selectedMemberName: string
  onRetake: () => void
  onRetakeAngle?: (angle: EnrollmentAngleKey) => void
  onEnroll: () => void
  isEnrolling: boolean
  framesReady: boolean
}

export function ResultView({
  frames,
  onRetake,
  onRetakeAngle,
  onEnroll,
  isEnrolling,
  framesReady,
}: ResultViewProps) {
  const validFrames = ENROLLMENT_ANGLE_STEPS.map((step) =>
    frames.find((f) => f.angle === step.angle),
  ).filter((f): f is CapturedFrame => Boolean(f))

  const [previewAngle, setPreviewAngle] = useState<string>(
    validFrames[0]?.angle || "front",
  )

  const activeFrame =
    validFrames.find((f) => f.angle === previewAngle) || validFrames[0] || frames[0]
  const hasError = validFrames.some((f) => f.status === "error")
  const collectedCount = getCollectedAngleCount(frames)

  return (
    <div className="relative flex h-full flex-col overflow-hidden bg-black/40">
      <div className="min-h-0 flex-1">
        {activeFrame && <ImagePreviewWithBbox frame={activeFrame} />}
      </div>

      {/* Bottom 5-angle review strip & actions */}
      <div className="z-10 flex flex-wrap items-center justify-between gap-3 border-t border-white/10 bg-[#0d0e11]/95 px-3 py-2">
        <div className="flex items-center gap-1.5">
          {ENROLLMENT_ANGLE_STEPS.map((step) => {
            const frame = frames.find((f) => f.angle === step.angle)
            const isSelected = activeFrame?.angle === step.angle
            return (
              <button
                key={step.angle}
                type="button"
                onClick={() => setPreviewAngle(step.angle)}
                className={`flex items-center gap-1.5 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors ${
                  isSelected
                    ? "border-cyan-400 bg-cyan-500/15 text-cyan-200"
                    : "border-white/10 bg-white/[0.03] text-white/65 hover:border-white/25 hover:text-white"
                }`}>
                {frame?.dataUrl && (
                  <img
                    src={frame.dataUrl}
                    alt={step.shortLabel}
                    className="h-5 w-5 rounded-sm object-cover"
                  />
                )}
                <span>{step.shortLabel}</span>
              </button>
            )
          })}
        </div>

        <div className="flex items-center gap-1.5">
          {onRetakeAngle && activeFrame?.angle && (
            <button
              type="button"
              onClick={() => onRetakeAngle(activeFrame.angle as EnrollmentAngleKey)}
              className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-2 text-xs font-medium text-white/75 transition-all hover:bg-white/10 hover:text-white active:scale-95">
              Retake {ENROLLMENT_ANGLE_STEPS.find((s) => s.angle === activeFrame.angle)?.shortLabel || "angle"}
            </button>
          )}
          <button
            type="button"
            onClick={onRetake}
            className={`min-w-[90px] rounded-lg px-2.5 py-2 text-xs transition-all active:scale-95 ${
              hasError ?
                "bg-rose-600 font-semibold text-white shadow-sm hover:bg-rose-500"
              : "border border-white/10 bg-[#141518] font-medium text-white/70 hover:bg-[#1a1c20] hover:text-white"
            }`}>
            Retake All
          </button>

          {!hasError && (
            <button
              type="button"
              onClick={onEnroll}
              disabled={!framesReady || collectedCount < ENROLLMENT_ANGLE_STEPS.length || isEnrolling}
              className="flex min-w-[116px] items-center justify-center gap-2 rounded-lg bg-cyan-400 px-3 py-2 text-xs font-semibold text-black shadow-sm transition-all hover:bg-cyan-300 active:scale-95 disabled:cursor-not-allowed disabled:border disabled:border-white/10 disabled:bg-[#141518] disabled:text-white/40 disabled:shadow-none">
              {isEnrolling ?
                <>
                  <div className="h-3 w-3 animate-spin rounded-full border-2 border-black/30 border-t-black" />
                  <span className="font-semibold text-black">Saving…</span>
                </>
              : `Enroll (${collectedCount}/5)`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
