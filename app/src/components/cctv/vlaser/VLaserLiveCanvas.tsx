import { useEffect, useRef, useState } from "react"
import { Activity, Layers, ShieldAlert, ShieldCheck, Zap } from "lucide-react"
import { vlaserService } from "@/services/vlaserService"
import type { CameraSpatialStateResponse, VLaserConfig } from "@/types/vlaser"

interface VLaserLiveCanvasProps {
  cameraId: string
  cameraName?: string
  classroom?: string | null
  isStreaming?: boolean
  onOpenEditor?: () => void
  compact?: boolean
}

const LINE_TYPE_COLORS: Record<string, string> = {
  entry: "#10b981",
  exit: "#f97316",
  internal: "#3b82f6",
  restricted: "#ef4444",
}

const ZONE_TYPE_COLORS: Record<string, string> = {
  classroom_entrance: "#38bdf8",
  student_seating: "#22c55e",
  teacher_area: "#a855f7",
  front_teaching: "#eab308",
  restricted_area: "#ef4444",
  custom: "#06b6d4",
}

export function VLaserLiveCanvas({
  cameraId,
  classroom = "Classroom",
  onOpenEditor,
}: VLaserLiveCanvasProps) {
  const [config, setConfig] = useState<VLaserConfig | null>(null)
  const [spatialState, setSpatialState] = useState<CameraSpatialStateResponse | null>(null)
  const [fps, setFps] = useState(30)
  const lastPollRef = useRef(Date.now())

  // Load V-LASER Grid Configuration
  useEffect(() => {
    let isCancelled = false
    const loadConfig = async () => {
      try {
        const cfg = await vlaserService.getConfig(cameraId)
        if (!isCancelled) {
          setConfig(cfg)
        }
      } catch {
        // Fallback default config
        if (!isCancelled) {
          setConfig({
            camera_id: cameraId,
            classroom: classroom || "Classroom",
            grid_enabled: true,
            grid_rows: 10,
            grid_cols: 10,
            grid_color: "#00f3ff",
            grid_opacity: 0.25,
            lines: [],
            zones: [],
            is_active: true,
          })
        }
      }
    }

    void loadConfig()
    return () => {
      isCancelled = true
    }
  }, [cameraId, classroom])

  // Real-time spatial tracking polling (350ms)
  useEffect(() => {
    let isCancelled = false

    const pollSpatial = async () => {
      try {
        const res = await vlaserService.getSpatialState(cameraId)
        if (!isCancelled) {
          const now = Date.now()
          const delta = (now - lastPollRef.current) / 1000
          lastPollRef.current = now
          if (delta > 0) {
            setFps(Math.min(60, Math.round(1 / delta)))
          }
          setSpatialState(res)
        }
      } catch {
        // Non-critical background polling
      }
    }

    void pollSpatial()
    const interval = setInterval(pollSpatial, 350)

    return () => {
      isCancelled = true
      clearInterval(interval)
    }
  }, [cameraId])

  const activeTracks = spatialState?.active_tracks ?? []
  const headcounts = spatialState?.zone_headcounts ?? {}

  return (
    <div className="relative flex h-full w-full flex-col overflow-hidden rounded-xl border border-cyan-500/25 bg-[#080b11] select-none">
      {/* Top AI Command Header Bar */}
      <div className="flex items-center justify-between border-b border-white/10 bg-[#0d111a]/95 px-3 py-2 text-xs backdrop-blur-md">
        <div className="flex items-center gap-2.5">
          <div className="flex items-center gap-1.5 rounded-lg border border-cyan-500/30 bg-cyan-950/40 px-2.5 py-1 text-[11px] font-semibold text-cyan-200">
            <Zap className="size-3 text-cyan-400 animate-pulse" />
            <span>V-LASER Digital Twin</span>
          </div>
          <span className="text-white/20">•</span>
          <span className="inline-flex items-center gap-1 rounded bg-white/5 px-2 py-0.5 font-mono text-[11px] text-white/80 border border-white/10">
            <strong className="text-cyan-300">{activeTracks.length}</strong> Tracked
          </span>
          {activeTracks.some((t) => t.is_occluded) && (
            <span className="inline-flex items-center gap-1 rounded bg-amber-500/15 px-2 py-0.5 text-[10px] font-bold text-amber-300 border border-amber-500/30">
              <ShieldAlert className="size-2.5" />
              Tracking Through Overlap
            </span>
          )}
        </div>

        <div className="flex items-center gap-2.5">
          <span className="inline-flex items-center gap-1 font-mono text-[10.5px] text-emerald-400/90 rounded bg-emerald-950/40 px-2 py-0.5 border border-emerald-500/25">
            <span className="size-1.5 rounded-full bg-emerald-400 animate-pulse" />
            {fps} FPS
          </span>
          {onOpenEditor && (
            <button
              type="button"
              onClick={onOpenEditor}
              className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/35 bg-cyan-500/15 px-2.5 py-1 text-[11px] font-semibold text-cyan-200 shadow-sm transition hover:border-cyan-400 hover:bg-cyan-500/25 hover:text-white">
              <Layers className="size-3 text-cyan-300" />
              <span>Calibrate Grid</span>
            </button>
          )}
        </div>
      </div>

      {/* Main 2D Spatial SVG Canvas Viewport */}
      <div className="relative flex-1 overflow-hidden bg-black/95">
        <svg
          viewBox="0 0 1000 1000"
          preserveAspectRatio="none"
          className="absolute inset-0 size-full">
          <defs>
            {/* Subtle Laser Beam Glow */}
            <filter id="live-laser-glow" x="-20%" y="-20%" width="140%" height="140%">
              <feGaussianBlur stdDeviation="3.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
            {/* Targeted Person Reticle Glow */}
            <filter id="track-reticle-glow" x="-40%" y="-40%" width="180%" height="180%">
              <feGaussianBlur stdDeviation="2.5" result="blur" />
              <feMerge>
                <feMergeNode in="blur" />
                <feMergeNode in="SourceGraphic" />
              </feMerge>
            </filter>
          </defs>

          {/* 1. Virtual Grid Mesh */}
          {config?.grid_enabled && (
            <g opacity={config.grid_opacity || 0.18}>
              {Array.from({ length: (config.grid_cols || 10) + 1 }).map((_, i) => {
                const x = (i / (config.grid_cols || 10)) * 1000
                return (
                  <line
                    key={`live-gv-${i}`}
                    x1={x}
                    y1={0}
                    x2={x}
                    y2={1000}
                    stroke={config.grid_color || "#00f3ff"}
                    strokeWidth="0.8"
                    strokeDasharray="2 4"
                  />
                )
              })}
              {Array.from({ length: (config.grid_rows || 10) + 1 }).map((_, i) => {
                const y = (i / (config.grid_rows || 10)) * 1000
                return (
                  <line
                    key={`live-gh-${i}`}
                    x1={0}
                    y1={y}
                    x2={1000}
                    y2={y}
                    stroke={config.grid_color || "#00f3ff"}
                    strokeWidth="0.8"
                    strokeDasharray="2 4"
                  />
                )
              })}
            </g>
          )}

          {/* 2. Configured Polygon Zones */}
          {(config?.zones ?? []).map((zone) => {
            if (!zone.enabled) return null
            const pts = zone.polygon.map((p) => `${p.x * 1000},${p.y * 1000}`).join(" ")
            const color = zone.color || ZONE_TYPE_COLORS[zone.zone_type] || "#06b6d4"

            // Compute center coordinates for badge positioning
            const centerX =
              zone.polygon.length > 0
                ? (zone.polygon.reduce((acc, p) => acc + p.x, 0) / zone.polygon.length) * 1000
                : 500
            const centerY =
              zone.polygon.length > 0
                ? (zone.polygon.reduce((acc, p) => acc + p.y, 0) / zone.polygon.length) * 1000
                : 500

            const zoneCount = headcounts[zone.id] ?? 0
            const labelText = `${zone.name} (${zoneCount})`
            const badgeWidth = Math.max(120, labelText.length * 8.5)

            return (
              <g key={`live-zone-${zone.id}`}>
                {/* Zone Polygon Boundary */}
                <polygon
                  points={pts}
                  fill={color}
                  fillOpacity={zone.opacity || 0.18}
                  stroke={color}
                  strokeWidth={1.5}
                  filter="url(#live-laser-glow)"
                />

                {/* HUD Pill Badge (Non-overlapping, High Contrast) */}
                {zone.polygon.length >= 3 && (
                  <g transform={`translate(${centerX}, ${centerY})`}>
                    <rect
                      x={-badgeWidth / 2}
                      y="-12"
                      width={badgeWidth}
                      height="24"
                      rx="4"
                      fill="rgba(10, 14, 22, 0.88)"
                      stroke={color}
                      strokeWidth="1"
                    />
                    <circle
                      cx={-badgeWidth / 2 + 10}
                      cy="0"
                      r="3.5"
                      fill={color}
                    />
                    <text
                      x="4"
                      y="4"
                      textAnchor="middle"
                      fill="#ffffff"
                      fontSize="11.5"
                      fontWeight="bold"
                      letterSpacing="0.3"
                      className="pointer-events-none select-none">
                      {zone.name}{" "}
                      <tspan fill="#67e8f9" fontWeight="bold">
                        ({zoneCount})
                      </tspan>
                    </text>
                  </g>
                )}
              </g>
            )
          })}

          {/* 3. Virtual Laser Boundary Lines */}
          {(config?.lines ?? []).map((line) => {
            if (!line.enabled) return null
            const color = line.color || LINE_TYPE_COLORS[line.line_type] || "#3b82f6"
            const x1 = line.p1.x * 1000
            const y1 = line.p1.y * 1000
            const x2 = line.p2.x * 1000
            const y2 = line.p2.y * 1000

            const midX = (x1 + x2) / 2
            const midY = (y1 + y2) / 2
            const isEntry = line.line_type === "entry"
            const isExit = line.line_type === "exit"
            const dirArrow = isEntry ? "ENTRY ➔" : isExit ? "⬅ EXIT" : line.line_type.toUpperCase()
            const lineLabel = `${line.name} (${dirArrow})`
            const pillWidth = Math.max(110, lineLabel.length * 8)

            return (
              <g key={`live-line-${line.id}`}>
                {/* Glow Laser Beam */}
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke={color}
                  strokeWidth={3.5}
                  strokeLinecap="round"
                  filter="url(#live-laser-glow)"
                />
                {/* Core White Filament */}
                <line
                  x1={x1}
                  y1={y1}
                  x2={x2}
                  y2={y2}
                  stroke="#ffffff"
                  strokeWidth={1.2}
                  strokeLinecap="round"
                />

                {/* Laser Line Badge (Offset cleanly above the line to avoid clipping) */}
                <g transform={`translate(${midX}, ${midY - 14})`}>
                  <rect
                    x={-pillWidth / 2}
                    y="-10"
                    width={pillWidth}
                    height="20"
                    rx="3"
                    fill="rgba(8, 11, 18, 0.92)"
                    stroke={color}
                    strokeWidth="0.8"
                  />
                  <text
                    x="0"
                    y="3.5"
                    textAnchor="middle"
                    fill={color}
                    fontSize="10.5"
                    fontWeight="bold"
                    letterSpacing="0.4"
                    className="pointer-events-none select-none">
                    {lineLabel}
                  </text>
                </g>
              </g>
            )
          })}

          {/* 4. Real-time Movement Trails */}
          {activeTracks.map((track) => {
            const trail = track.trail ?? []
            if (trail.length < 2) return null

            const isVerified = track.identity_state === "identity_verified"
            const trailColor =
              isVerified ? "#10b981"
              : track.is_occluded ? "#f59e0b"
              : track.identity_state === "unknown_person" ? "#f43f5e"
              : "#00f3ff"

            const polyPoints = trail.map((pt) => `${pt.x * 1000},${pt.y * 1000}`).join(" ")

            return (
              <polyline
                key={`trail-${track.track_id}`}
                points={polyPoints}
                fill="none"
                stroke={trailColor}
                strokeWidth={2}
                strokeDasharray="3 3"
                opacity={0.65}
                className="transition-all duration-150"
              />
            )
          })}

          {/* 5. Live Spatial Persons & Reticles at Foot Anchor */}
          {activeTracks.map((track, trackIdx) => {
            const isVerified = track.identity_state === "identity_verified"
            const isPending = track.identity_state === "pending_verification"
            const isUnknown = track.identity_state === "unknown_person"
            const isOccluded = Boolean(track.is_occluded)

            const color =
              isVerified ? "#10b981"
              : isOccluded ? "#f59e0b"
              : isUnknown ? "#f43f5e"
              : isPending ? "#eab308"
              : "#00f3ff"

            const displayName =
              isVerified ?
                `Track #${track.track_id} • ${track.student_name || "Verified"}`
              : isOccluded ?
                `Track #${track.track_id} • ${track.candidate_student_name ? `${track.candidate_student_name} (Overlapped)` : "Face Occluded (Tracking)"}`
              : isPending ?
                `Track #${track.track_id} • Identity Pending (Not Guessed)`
              : isUnknown ?
                `Track #${track.track_id} • Unknown Person`
              : `Track #${track.track_id} • Spatially Tracked (Awaiting Face)`

            const cx = track.anchor.x * 1000
            const cy = track.anchor.y * 1000

            // Stagger badge height alternately to prevent overlapping tags when people are close
            const badgeYOffset = -22 - (trackIdx % 2) * 16
            const badgeWidth = Math.min(180, Math.max(120, displayName.length * 6.8))

            return (
              <g key={`live-track-${track.track_id}`}>
                {/* Outer Reticle Ring */}
                <circle
                  cx={cx}
                  cy={cy}
                  r={isOccluded ? 16 : 13}
                  fill="none"
                  stroke={color}
                  strokeWidth={1.8}
                  strokeDasharray={isOccluded ? "3 3" : undefined}
                  className={isOccluded ? "animate-spin origin-center" : "animate-pulse"}
                  opacity={0.85}
                />

                {/* Laser Targeting Core */}
                <circle
                  cx={cx}
                  cy={cy}
                  r={5}
                  fill={color}
                  stroke="#ffffff"
                  strokeWidth={1.5}
                  filter="url(#track-reticle-glow)"
                />

                {/* Reticle Crosshair Ticks */}
                <line x1={cx - 10} y1={cy} x2={cx - 5} y2={cy} stroke="#ffffff" strokeWidth="1.2" />
                <line x1={cx + 5} y1={cy} x2={cx + 10} y2={cy} stroke="#ffffff" strokeWidth="1.2" />
                <line x1={cx} y1={cy - 10} x2={cx} y2={cy - 5} stroke="#ffffff" strokeWidth="1.2" />
                <line x1={cx} y1={cy + 5} x2={cx} y2={cy + 10} stroke="#ffffff" strokeWidth="1.2" />

                {/* Floating HUD Tag Above Tracked Person */}
                <g transform={`translate(${cx}, ${cy + badgeYOffset})`}>
                  <rect
                    x={-badgeWidth / 2}
                    y="-10"
                    width={badgeWidth}
                    height="20"
                    rx="4"
                    fill="rgba(6, 9, 15, 0.92)"
                    stroke={color}
                    strokeWidth="1"
                    filter="drop-shadow(0 2px 4px rgba(0,0,0,0.8))"
                  />
                  <text
                    x="0"
                    y="3"
                    textAnchor="middle"
                    fill={color}
                    fontSize="9.5"
                    fontWeight="bold"
                    className="select-none">
                    {displayName.length > 25 ? `${displayName.slice(0, 25)}…` : displayName}
                  </text>
                </g>
              </g>
            )
          })}
        </svg>

        {activeTracks.length === 0 && (
          <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center text-center text-white/40">
            <Activity className="size-7 animate-pulse text-cyan-400/50 mb-2" />
            <p className="text-xs font-semibold text-white/70">V-LASER Spatial Grid Active</p>
            <p className="text-[11px] text-white/40">
              Awaiting person movement and laser boundary interaction
            </p>
          </div>
        )}
      </div>

      {/* Footer: Live Modular Zone Telemetry Dock */}
      <div className="flex flex-wrap items-center justify-between gap-2 border-t border-white/10 bg-[#0c1017]/95 px-3 py-1.5 text-xs backdrop-blur-md">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-white/40 uppercase text-[9.5px] tracking-wider">
            ZONES:
          </span>
          {(config?.zones ?? []).map((z) => {
            const zColor = z.color || ZONE_TYPE_COLORS[z.zone_type] || "#06b6d4"
            return (
              <div
                key={`cnt-${z.id}`}
                className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-white/80">
                <span className="size-2 rounded-full" style={{ backgroundColor: zColor }} />
                <span>{z.name}:</span>
                <strong className="text-cyan-300 font-mono">{headcounts[z.id] ?? 0}</strong>
              </div>
            )
          })}
          {headcounts["unassigned"] !== undefined && (
            <div className="inline-flex items-center gap-1.5 rounded-md border border-white/10 bg-white/5 px-2 py-0.5 text-[10.5px] text-white/70">
              <span className="size-2 rounded-full bg-white/40" />
              <span>Transit Area:</span>
              <strong className="text-white font-mono">{headcounts["unassigned"]}</strong>
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5 text-white/50 text-[10.5px]">
          <ShieldCheck className="size-3 text-emerald-400" />
          <span>Track Buffer: Continuous Overlap Recovery</span>
        </div>
      </div>
    </div>
  )
}
