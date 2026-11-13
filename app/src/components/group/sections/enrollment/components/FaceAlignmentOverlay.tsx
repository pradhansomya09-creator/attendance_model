import { useEffect, useRef, useState } from "react"
import { ArrowLeft, ArrowRight, CheckCircle2, AlertTriangle, Crosshair } from "lucide-react"

import type { FaceAlignmentEvaluation, OverlayPoint } from "@/services/BackendService"
import {
  ENROLLMENT_ANGLE_STEPS,
  type EnrollmentAngleKey,
} from "../enrollmentAngles"

interface FaceAlignmentOverlayProps {
  alignment: FaceAlignmentEvaluation | null
  currentAngle: EnrollmentAngleKey
  completedAngles: EnrollmentAngleKey[]
  videoWidth?: number
  videoHeight?: number
  objectMode?: "contain" | "cover"
  compact?: boolean
}

function toPolylinePoints(points: OverlayPoint[] | undefined): string {
  if (!points || points.length === 0) return ""
  return points.map((p) => `${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(" ")
}

export function FaceAlignmentOverlay({
  alignment,
  currentAngle,
  completedAngles,
  videoWidth = 640,
  videoHeight = 480,
  objectMode = "contain",
  compact = false,
}: FaceAlignmentOverlayProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [boxSize, setBoxSize] = useState({ width: 0, height: 0 })

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const update = () => {
      setBoxSize({
        width: el.clientWidth,
        height: el.clientHeight,
      })
    }
    update()
    if (typeof ResizeObserver === "undefined") return
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const overlay = alignment?.overlay || null
  const iw = overlay?.image_width || videoWidth || 640
  const ih = overlay?.image_height || videoHeight || 480

  // Compute rendered video rect inside container (matching CSS object-contain or object-cover)
  let renderW = boxSize.width || iw
  let renderH = boxSize.height || ih
  let offsetX = 0
  let offsetY = 0
  if (boxSize.width > 0 && boxSize.height > 0 && iw > 0 && ih > 0) {
    const containerRatio = boxSize.width / boxSize.height
    const mediaRatio = iw / ih
    const useWidth =
      objectMode === "contain" ? containerRatio < mediaRatio : containerRatio > mediaRatio
    if (useWidth) {
      renderW = boxSize.width
      renderH = boxSize.width / mediaRatio
      offsetX = 0
      offsetY = (boxSize.height - renderH) / 2
    } else {
      renderH = boxSize.height
      renderW = boxSize.height * mediaRatio
      offsetX = (boxSize.width - renderW) / 2
      offsetY = 0
    }
  }

  const currentSpec =
    ENROLLMENT_ANGLE_STEPS.find((s) => s.angle === currentAngle) || ENROLLMENT_ANGLE_STEPS[0]
  const status = alignment?.status || "missing"
  const isReady = Boolean(alignment?.ready)
  const isErrorState =
    status === "poor_lighting" ||
    status === "too_blurry" ||
    status === "occluded" ||
    status === "multiple_faces" ||
    status === "missing"

  const ovalColor = isReady
    ? "rgba(52, 211, 153, 0.92)"
    : isErrorState
      ? "rgba(251, 113, 133, 0.85)"
      : "rgba(34, 211, 238, 0.85)"

  const completedSet = new Set(completedAngles)
  const coords = overlay?.coordinates

  return (
    <div
      ref={containerRef}
      data-testid="face-alignment-overlay"
      className="pointer-events-none absolute inset-0 overflow-hidden select-none">
      {/* Lenskart-style central target oval + 5-segment progress ring */}
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="xMidYMid meet"
        className="absolute inset-0 h-full w-full">
        {/* Outer 5-segment progress arcs */}
        {ENROLLMENT_ANGLE_STEPS.map((step, idx) => {
          const startDeg = -90 + idx * 72 + 4
          const endDeg = startDeg + 64
          const rad1 = (startDeg * Math.PI) / 180
          const rad2 = (endDeg * Math.PI) / 180
          const rx = 31
          const ry = 40
          const x1 = 50 + rx * Math.cos(rad1)
          const y1 = 50 + ry * Math.sin(rad1)
          const x2 = 50 + rx * Math.cos(rad2)
          const y2 = 50 + ry * Math.sin(rad2)
          const done = completedSet.has(step.angle)
          const isCurrent = step.angle === currentAngle
          const strokeColor = done
            ? "#34d399"
            : isCurrent
              ? isReady
                ? "#34d399"
                : "#22d3ee"
              : "rgba(255,255,255,0.22)"
          return (
            <path
              key={step.angle}
              d={`M ${x1.toFixed(2)} ${y1.toFixed(2)} A ${rx} ${ry} 0 0 1 ${x2.toFixed(2)} ${y2.toFixed(2)}`}
              fill="none"
              stroke={strokeColor}
              strokeWidth={isCurrent || done ? "1.45" : "0.9"}
              strokeLinecap="round"
            />
          )
        })}

        {/* Inner reticle oval */}
        <ellipse
          cx="50"
          cy="50"
          rx="27"
          ry="36"
          fill="none"
          stroke={ovalColor}
          strokeWidth="0.7"
          strokeDasharray={isReady ? undefined : "2.2 1.6"}
        />

        {/* Frame crosshair ticks */}
        <line x1="50" y1="11" x2="50" y2="15" stroke="rgba(255,255,255,0.35)" strokeWidth="0.4" />
        <line x1="50" y1="85" x2="50" y2="89" stroke="rgba(255,255,255,0.35)" strokeWidth="0.4" />
        <line x1="19" y1="50" x2="24" y2="50" stroke="rgba(255,255,255,0.35)" strokeWidth="0.4" />
        <line x1="76" y1="50" x2="81" y2="50" stroke="rgba(255,255,255,0.35)" strokeWidth="0.4" />
      </svg>

      {/* Aligned video-space SVG drawing live facial landmarks, guides & axes */}
      {overlay && (
        <svg
          data-testid="facial-landmark-svg"
          viewBox={`0 0 ${iw} ${ih}`}
          preserveAspectRatio="none"
          style={{
            position: "absolute",
            left: `${offsetX}px`,
            top: `${offsetY}px`,
            width: `${renderW}px`,
            height: `${renderH}px`,
          }}>
          {/* Horizontal & Vertical reference coordinate axes across detected face */}
          <line
            data-testid="guide-axis-horizontal"
            x1={overlay.axes.horizontal.x1}
            y1={overlay.axes.horizontal.y1}
            x2={overlay.axes.horizontal.x2}
            y2={overlay.axes.horizontal.y2}
            stroke="rgba(34, 211, 238, 0.55)"
            strokeWidth="1.2"
            strokeDasharray="4 3"
          />
          <line
            data-testid="guide-axis-vertical"
            x1={overlay.axes.vertical.x1}
            y1={overlay.axes.vertical.y1}
            x2={overlay.axes.vertical.x2}
            y2={overlay.axes.vertical.y2}
            stroke="rgba(34, 211, 238, 0.55)"
            strokeWidth="1.2"
            strokeDasharray="4 3"
          />

          {/* Face outline contour */}
          <polygon
            data-testid="guide-face-outline"
            points={toPolylinePoints(overlay.features.face_outline)}
            fill="none"
            stroke={isReady ? "rgba(52, 211, 153, 0.85)" : "rgba(56, 189, 248, 0.78)"}
            strokeWidth="1.5"
          />

          {/* Left & Right Ear guides */}
          <polyline
            data-testid="guide-left-ear"
            points={toPolylinePoints(overlay.features.left_ear)}
            fill="none"
            stroke="rgba(250, 204, 21, 0.78)"
            strokeWidth="1.4"
            strokeLinecap="round"
          />
          <polyline
            data-testid="guide-right-ear"
            points={toPolylinePoints(overlay.features.right_ear)}
            fill="none"
            stroke="rgba(250, 204, 21, 0.78)"
            strokeWidth="1.4"
            strokeLinecap="round"
          />

          {/* Eyebrows */}
          <polyline
            data-testid="guide-left-eyebrow"
            points={toPolylinePoints(overlay.features.left_eyebrow)}
            fill="none"
            stroke="rgba(167, 243, 208, 0.9)"
            strokeWidth="1.6"
            strokeLinecap="round"
          />
          <polyline
            data-testid="guide-right-eyebrow"
            points={toPolylinePoints(overlay.features.right_eyebrow)}
            fill="none"
            stroke="rgba(167, 243, 208, 0.9)"
            strokeWidth="1.6"
            strokeLinecap="round"
          />

          {/* Left & Right Eyes contours + centers */}
          <polygon
            data-testid="guide-left-eye"
            points={toPolylinePoints(overlay.features.left_eye.contour)}
            fill="none"
            stroke="rgba(34, 211, 238, 0.95)"
            strokeWidth="1.3"
          />
          <circle
            cx={overlay.features.left_eye.center.x}
            cy={overlay.features.left_eye.center.y}
            r="2.6"
            fill="#22d3ee"
          />
          <polygon
            data-testid="guide-right-eye"
            points={toPolylinePoints(overlay.features.right_eye.contour)}
            fill="none"
            stroke="rgba(34, 211, 238, 0.95)"
            strokeWidth="1.3"
          />
          <circle
            cx={overlay.features.right_eye.center.x}
            cy={overlay.features.right_eye.center.y}
            r="2.6"
            fill="#22d3ee"
          />

          {/* Nose bridge & alar base + tip */}
          <polyline
            data-testid="guide-nose-bridge"
            points={toPolylinePoints(overlay.features.nose.bridge)}
            fill="none"
            stroke="rgba(255, 255, 255, 0.85)"
            strokeWidth="1.3"
          />
          <polyline
            data-testid="guide-nose-base"
            points={toPolylinePoints(overlay.features.nose.base)}
            fill="none"
            stroke="rgba(255, 255, 255, 0.85)"
            strokeWidth="1.3"
          />
          <circle
            cx={overlay.features.nose.tip.x}
            cy={overlay.features.nose.tip.y}
            r="2.8"
            fill="#facc15"
          />

          {/* Mouth contour + corner points */}
          <polygon
            data-testid="guide-mouth"
            points={toPolylinePoints(overlay.features.mouth.contour)}
            fill="none"
            stroke="rgba(244, 114, 182, 0.9)"
            strokeWidth="1.3"
          />
          <circle
            cx={overlay.features.mouth.left.x}
            cy={overlay.features.mouth.left.y}
            r="2.3"
            fill="#f472b6"
          />
          <circle
            cx={overlay.features.mouth.right.x}
            cy={overlay.features.mouth.right.y}
            r="2.3"
            fill="#f472b6"
          />

          {/* Key landmark points */}
          {Object.entries(overlay.coordinates.landmarks).map(([key, pt]) => (
            <circle
              key={key}
              data-testid={`landmark-pt-${key}`}
              cx={pt.x}
              cy={pt.y}
              r="1.9"
              fill={isReady ? "#34d399" : "#e2e8f0"}
              opacity="0.85"
            />
          ))}
        </svg>
      )}

      {/* Top HUD: Step angle prompt & directional turn cue */}
      <div className="absolute top-2.5 right-2.5 left-2.5 flex items-start justify-between gap-2">
        <div className="flex items-center gap-1.5 rounded-lg border border-white/15 bg-slate-950/75 px-2.5 py-1.5 backdrop-blur-md">
          <span className="rounded bg-cyan-500/20 px-1.5 py-0.5 font-mono text-[10px] font-bold text-cyan-300">
            {completedAngles.length}/{ENROLLMENT_ANGLE_STEPS.length}
          </span>
          <div className="min-w-0">
            <div className="flex items-center gap-1 text-[11px] font-semibold text-white">
              {(currentSpec.direction === "left" || currentSpec.direction === "far_left") && (
                <ArrowLeft className="size-3.5 text-cyan-300" />
              )}
              {(currentSpec.direction === "right" || currentSpec.direction === "far_right") && (
                <ArrowRight className="size-3.5 text-cyan-300" />
              )}
              <span>{currentSpec.label}</span>
            </div>
            {!compact && (
              <p className="text-[10px] text-white/65">{currentSpec.instruction}</p>
            )}
          </div>
        </div>

        {/* Live Horizontal / Vertical & Pose Coordinates */}
        <div
          data-testid="alignment-coordinates-hud"
          className="rounded-lg border border-white/15 bg-slate-950/75 px-2.5 py-1.5 font-mono text-[10px] text-white/80 backdrop-blur-md">
          {coords ? (
            <div className="flex flex-col items-end gap-0.5 leading-tight">
              <div className="flex items-center gap-1.5 text-cyan-300">
                <Crosshair className="size-2.5" />
                <span>
                  X:{coords.center_x.toFixed(0)} Y:{coords.center_y.toFixed(0)}
                </span>
              </div>
              <div className="text-[9px] text-white/65">
                dX:{coords.offset_x >= 0 ? "+" : ""}
                {(coords.offset_x * 100).toFixed(0)}% dY:{coords.offset_y >= 0 ? "+" : ""}
                {(coords.offset_y * 100).toFixed(0)}%
              </div>
              <div className="text-[9px] text-white/65">
                Yaw:{coords.yaw.toFixed(1)}° Pitch:{coords.pitch.toFixed(1)}° Roll:{coords.roll.toFixed(1)}°
              </div>
              {!compact && (
                <div className="text-[9px] text-white/50">
                  Light:{coords.brightness.toFixed(0)} Blur:{(coords.clarity_score * 100).toFixed(0)}%
                </div>
              )}
            </div>
          ) : (
            <span className="text-[9px] text-white/50">Scanning face coords…</span>
          )}
        </div>
      </div>

      {/* Bottom Live Guidance Pill */}
      <div
        className={`absolute right-3 left-3 flex justify-center ${
          compact ? "bottom-14" : "bottom-2.5"
        }`}>
        <div
          data-testid="alignment-guidance-banner"
          className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-medium backdrop-blur-md transition-colors ${
            isReady
              ? "border-emerald-400/40 bg-emerald-950/80 text-emerald-200"
              : isErrorState
                ? "border-rose-400/40 bg-rose-950/80 text-rose-200"
                : "border-amber-400/40 bg-slate-950/80 text-amber-200"
          }`}>
          {isReady ? (
            <CheckCircle2 className="size-3.5 shrink-0 text-emerald-400" />
          ) : (
            <AlertTriangle className="size-3.5 shrink-0" />
          )}
          <span className="truncate">
            {alignment?.guidance || currentSpec.instruction}
          </span>
        </div>
      </div>
    </div>
  )
}
