import { Check, RotateCcw } from "lucide-react"

import {
  ENROLLMENT_ANGLE_STEPS,
  getFrameForAngle,
  isValidCapturedFrame,
  type EnrollmentAngleKey,
} from "../enrollmentAngles"
import type { CapturedFrame } from "../types"

interface AngleProgressStripProps {
  frames: CapturedFrame[]
  activeAngle: EnrollmentAngleKey
  onSelectAngle: (angle: EnrollmentAngleKey) => void
  onRetakeAngle?: (angle: EnrollmentAngleKey) => void
  disabled?: boolean
  compact?: boolean
}

export function AngleProgressStrip({
  frames,
  activeAngle,
  onSelectAngle,
  onRetakeAngle,
  disabled = false,
  compact = false,
}: AngleProgressStripProps) {
  return (
    <div
      data-testid="multi-angle-progress-strip"
      className={`grid grid-cols-5 ${compact ? "gap-1.5" : "gap-2"}`}>
      {ENROLLMENT_ANGLE_STEPS.map((step) => {
        const frame = getFrameForAngle(frames, step.angle)
        const isReady = isValidCapturedFrame(frame)
        const isProcessing = frame?.status === "processing"
        const hasError = frame?.status === "error"
        const isSelected = activeAngle === step.angle

        return (
          <div
            key={step.angle}
            className={`group relative flex flex-col items-center rounded-lg border p-1.5 transition-all ${
              isSelected
                ? "border-cyan-400/70 bg-cyan-500/10"
                : isReady
                  ? "border-emerald-500/40 bg-emerald-500/5"
                  : hasError
                    ? "border-rose-500/50 bg-rose-500/10"
                    : "border-white/10 bg-white/[0.02]"
            }`}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onSelectAngle(step.angle)}
              className="flex w-full flex-col items-center gap-1 text-center focus-visible:outline-none disabled:opacity-60">
              <div
                className={`relative w-full overflow-hidden rounded border border-white/10 bg-black/40 ${
                  compact ? "h-10" : "h-12"
                }`}>
                {frame?.dataUrl ? (
                  <img
                    src={frame.dataUrl}
                    alt={step.label}
                    className="h-full w-full object-cover"
                  />
                ) : (
                  <div className="flex h-full w-full items-center justify-center font-mono text-[10px] text-white/35">
                    {step.stepNumber}/5
                  </div>
                )}

                {isReady && (
                  <span
                    aria-label={`${step.label} captured`}
                    className="absolute top-0.5 right-0.5 flex size-4 items-center justify-center rounded-full bg-emerald-500 text-slate-950 shadow">
                    <Check className="size-2.5 stroke-[3]" />
                  </span>
                )}
                {isProcessing && (
                  <span className="absolute inset-0 flex items-center justify-center bg-black/50 text-[9px] font-medium text-cyan-300">
                    …
                  </span>
                )}
              </div>

              <span
                className={`truncate text-[10px] font-medium leading-tight ${
                  isSelected
                    ? "text-cyan-300"
                    : isReady
                      ? "text-emerald-300"
                      : hasError
                        ? "text-rose-300"
                        : "text-white/60"
                }`}>
                {step.shortLabel}
              </span>
            </button>

            {isReady && onRetakeAngle && !disabled && (
              <button
                type="button"
                title={`Retake ${step.label}`}
                aria-label={`Retake ${step.label}`}
                onClick={(e) => {
                  e.stopPropagation()
                  onRetakeAngle(step.angle)
                }}
                className="mt-1 flex items-center gap-0.5 rounded px-1 py-0.5 text-[9px] text-white/55 transition-colors hover:bg-white/10 hover:text-white">
                <RotateCcw className="size-2.5" />
                <span>Retake</span>
              </button>
            )}
          </div>
        )
      })}
    </div>
  )
}

