import { AlertTriangle, Camera, Columns2, Eye, ShieldAlert, Sparkles, Users, X, Zap } from "lucide-react"
import { useDetectionStore } from "@/components/main/stores"

export type SmartCctvTab =
  | "faculty"
  | "playback"
  | "unknowns"
  | "admin"
  | "timetable"
  | "hod"
  | "student"

export type ViewportMode = "camera" | "split" | "vlaser"

interface CctvStatusHudProps {
  isStreaming: boolean
  onOpenHub: (initialTab?: SmartCctvTab) => void
  onOpenVLaser?: () => void
  viewportMode?: ViewportMode
  onChangeViewportMode?: (mode: ViewportMode) => void
}

const STATUS_STYLES: Record<
  "green" | "yellow" | "red",
  { dot: string; border: string; bg: string; text: string; label: string }
> = {
  green: {
    dot: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]",
    border: "border-emerald-500/30",
    bg: "bg-emerald-950/50",
    text: "text-emerald-300",
    label: "Good Visibility",
  },
  yellow: {
    dot: "bg-amber-400 shadow-[0_0_8px_rgba(251,191,36,0.8)]",
    border: "border-amber-500/30",
    bg: "bg-amber-950/50",
    text: "text-amber-300",
    label: "Reduced Visibility",
  },
  red: {
    dot: "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.85)]",
    border: "border-rose-500/40",
    bg: "bg-rose-950/60",
    text: "text-rose-300",
    label: "Poor Visibility – Unreliable",
  },
}

export function CctvStatusHud({
  isStreaming,
  onOpenHub,
  onOpenVLaser,
  viewportMode = "split",
  onChangeViewportMode,
}: CctvStatusHudProps) {
  const { imageQuality, headcountSummary, cctvAlerts = [], dismissCctvAlert, activeCctvCameraId } =
    useDetectionStore()

  const safeAlerts = Array.isArray(cctvAlerts) ? cctvAlerts : []
  const qualityKey = (imageQuality?.status ?? "green") as keyof typeof STATUS_STYLES
  const qualityStyle = STATUS_STYLES[qualityKey] ?? STATUS_STYLES.green

  return (
    <header
      role="region"
      aria-label="CCTV System Telemetry and Mode Control"
      className="pointer-events-none absolute top-2 right-2 left-2 z-40 flex flex-col gap-1.5 select-none">
      {/* Top Command Bar Capsule */}
      <div className="pointer-events-auto flex items-center justify-between gap-2 rounded-xl border border-white/10 bg-[#0a0d14]/90 px-3 py-1.5 shadow-2xl backdrop-blur-xl">
        {/* Left: Telemetry & Biometric Quality Badges */}
        <div className="flex min-w-0 items-center gap-2 overflow-x-auto no-scrollbar">
          {isStreaming && imageQuality ? (
            <div
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-semibold backdrop-blur-md ${qualityStyle.border} ${qualityStyle.bg} ${qualityStyle.text}`}>
              <span className={`size-2 rounded-full ${qualityStyle.dot}`} />
              <span className="truncate">{qualityStyle.label}</span>
              <span className="text-white/30">•</span>
              <span className="font-mono text-white/90">
                {Math.round(imageQuality.score * 100)}%
              </span>
              {imageQuality.is_ir_mode && (
                <span className="rounded bg-indigo-500/25 px-1.5 py-0.2 text-[9.5px] font-bold text-indigo-300 border border-indigo-400/30">
                  IR
                </span>
              )}
              {imageQuality.enhancements_applied.length > 0 && (
                <span
                  title={`Applied: ${imageQuality.enhancements_applied.join(", ")}`}
                  className="inline-flex items-center gap-1 rounded bg-cyan-500/20 px-1.5 py-0.2 text-[9.5px] font-medium text-cyan-200 border border-cyan-400/30">
                  <Sparkles className="size-2.5" />
                  Enhanced
                </span>
              )}
            </div>
          ) : (
            <div className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white/70">
              <Camera className="size-3.5 text-cyan-400" />
              <span>{activeCctvCameraId ? "CCTV Camera Bound" : "Smart CCTV Ready"}</span>
            </div>
          )}

          {isStreaming && headcountSummary && (
            <button
              type="button"
              onClick={() => onOpenHub("faculty")}
              className="inline-flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-2.5 py-1 text-xs text-white/80 transition hover:border-cyan-500/40 hover:bg-white/10 hover:text-white">
              <Users className="size-3.5 text-cyan-400" />
              <span>
                Detected <strong className="text-white font-mono">{headcountSummary.unique_detected ?? 0}</strong> / Verified{" "}
                <strong className="text-emerald-300 font-mono">
                  {headcountSummary.successfully_identified ?? 0}
                </strong>
              </span>
              {(headcountSummary.unknown_individuals ?? 0) > 0 && (
                <span className="rounded bg-amber-500/20 px-1.5 py-0.2 text-[9.5px] font-bold text-amber-300 border border-amber-500/30">
                  {headcountSummary.unknown_individuals} Unknown
                </span>
              )}
              {(headcountSummary.section_mismatches ?? 0) > 0 && (
                <span className="rounded bg-rose-500/20 px-1.5 py-0.2 text-[9.5px] font-bold text-rose-300 border border-rose-500/30">
                  {headcountSummary.section_mismatches} Mismatch
                </span>
              )}
            </button>
          )}
        </div>

        {/* Center: Segmented Viewport Mode Switcher */}
        {onChangeViewportMode && (
          <nav
            aria-label="Viewport Switcher"
            className="flex items-center rounded-lg border border-white/10 bg-black/60 p-0.5 shadow-inner">
            <button
              type="button"
              onClick={() => onChangeViewportMode("camera")}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                viewportMode === "camera"
                  ? "border border-cyan-400/40 bg-cyan-500/20 text-cyan-200 shadow-sm"
                  : "text-white/60 hover:text-white"
              }`}
              title="Camera View Only">
              <Camera className="size-3.5" />
              <span className="hidden sm:inline">Camera</span>
            </button>
            <button
              type="button"
              onClick={() => onChangeViewportMode("split")}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                viewportMode === "split"
                  ? "border border-cyan-400/50 bg-cyan-500/25 text-white shadow-sm font-semibold"
                  : "text-white/60 hover:text-white"
              }`}
              title="Dual View: Original Camera + V-LASER Grid">
              <Columns2 className="size-3.5 text-cyan-400" />
              <span>Dual View</span>
            </button>
            <button
              type="button"
              onClick={() => onChangeViewportMode("vlaser")}
              className={`inline-flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition ${
                viewportMode === "vlaser"
                  ? "border border-cyan-400/40 bg-cyan-500/20 text-cyan-200 shadow-sm"
                  : "text-white/60 hover:text-white"
              }`}
              title="V-LASER Digital Twin Only">
              <Zap className="size-3.5 text-cyan-400" />
              <span className="hidden sm:inline">V-LASER</span>
            </button>
          </nav>
        )}

        {/* Right: Hub & Calibration Quick Launchers */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenVLaser ? onOpenVLaser : () => onOpenHub("admin")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-cyan-500/15 px-3 py-1 text-xs font-semibold text-cyan-200 shadow-sm transition hover:border-cyan-400 hover:bg-cyan-500/25 hover:text-white">
            <Zap className="size-3.5 text-cyan-400 animate-pulse" />
            <span>V-LASER Grid</span>
          </button>
          <button
            type="button"
            onClick={() => onOpenHub("faculty")}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-1 text-xs font-semibold text-white/85 shadow-sm transition hover:border-white/30 hover:bg-white/10 hover:text-white">
            <Eye className="size-3.5 text-cyan-400" />
            <span>Smart CCTV Hub</span>
            {safeAlerts.length > 0 && (
              <span className="rounded-full bg-rose-500 px-1.5 py-0.2 text-[9.5px] font-bold text-white">
                {safeAlerts.length}
              </span>
            )}
          </button>
        </div>
      </div>

      {/* Real-Time CCTV Alerts Stack */}
      {safeAlerts.slice(0, 2).map((alert) => {
        const targetTab: SmartCctvTab =
          alert.alert_type === "unknown_student" ? "unknowns" : "faculty"
        const isCritical = alert.severity === "critical" || alert.alert_type === "quality_warning"
        return (
          <div
            key={`${alert.alert_type}-${alert.timestamp}`}
            className={`pointer-events-auto flex items-center justify-between gap-3 rounded-xl border px-3 py-2 text-xs shadow-2xl backdrop-blur-xl ${
              isCritical
                ? "border-rose-500/40 bg-rose-950/90 text-rose-100"
                : "border-amber-500/40 bg-amber-950/90 text-amber-100"
            }`}>
            <div className="flex items-center gap-2">
              {isCritical ? (
                <ShieldAlert className="size-4 shrink-0 text-rose-400" />
              ) : (
                <AlertTriangle className="size-4 shrink-0 text-amber-400" />
              )}
              <span className="font-medium">{alert.message}</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onOpenHub(targetTab)}
                className="rounded-lg border border-white/20 bg-white/15 px-2.5 py-0.5 text-[11px] font-semibold text-white hover:bg-white/25">
                Review
              </button>
              <button
                type="button"
                onClick={() => dismissCctvAlert(alert.timestamp)}
                aria-label="Dismiss CCTV alert"
                className="rounded-md p-1 text-white/60 hover:bg-white/10 hover:text-white">
                <X className="size-3.5" />
              </button>
            </div>
          </div>
        )
      })}
    </header>
  )
}
