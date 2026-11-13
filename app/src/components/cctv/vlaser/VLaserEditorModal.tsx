import { useCallback, useEffect, useRef, useState } from "react"
import {
  AlertTriangle,
  Check,
  ChevronDown,
  Eye,
  EyeOff,
  Grid3X3,
  Layers,
  Magnet,
  Maximize2,
  Minimize2,
  Move,
  Plus,
  RefreshCw,
  RotateCcw,
  Save,
  ShieldAlert,
  Trash2,
  X,
  Zap,
} from "lucide-react"
import { vlaserService } from "@/services/vlaserService"
import type {
  CameraSpatialStateResponse,
  LineDirection,
  LineType,
  Point2D,
  SpatialEvent,
  VLaserConfig,
  VirtualLine,
  VirtualZone,
  ZoneType,
} from "@/types/vlaser"

interface VLaserEditorModalProps {
  cameraId: string
  cameraName: string
  classroom?: string | null
  isOpen: boolean
  onClose: () => void
  onSaved?: (config: VLaserConfig) => void
}

type EditorMode = "select" | "draw_line" | "draw_zone"

const LINE_TYPE_COLORS: Record<LineType, string> = {
  entry: "#10b981",      // Emerald green
  exit: "#f97316",       // Orange
  internal: "#3b82f6",   // Blue
  restricted: "#ef4444", // Red
}

const ZONE_TYPE_COLORS: Record<ZoneType, string> = {
  classroom_entrance: "#38bdf8",
  student_seating: "#22c55e",
  teacher_area: "#a855f7",
  front_teaching: "#eab308",
  restricted_area: "#ef4444",
  custom: "#06b6d4",
}

const ZONE_TYPE_LABELS: Record<ZoneType, string> = {
  classroom_entrance: "Classroom Entrance",
  student_seating: "Student Seating",
  teacher_area: "Teacher Area",
  front_teaching: "Front Teaching Area",
  restricted_area: "Restricted Area",
  custom: "Custom Zone",
}

export function VLaserEditorModal({
  cameraId,
  cameraName,
  classroom,
  isOpen,
  onClose,
  onSaved,
}: VLaserEditorModalProps) {
  const [config, setConfig] = useState<VLaserConfig | null>(null)
  const [initialConfig, setInitialConfig] = useState<VLaserConfig | null>(null)
  const [previewImage, setPreviewImage] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [errorMessage, setErrorMessage] = useState<string | null>(null)
  const [successMessage, setSuccessMessage] = useState<string | null>(null)
  const [spatialState, setSpatialState] = useState<CameraSpatialStateResponse | null>(null)

  // Visibility toggles
  const [showGrid, setShowGrid] = useState(true)
  const [showLines, setShowLines] = useState(true)
  const [showZones, setShowZones] = useState(true)
  const [snapToGrid, setSnapToGrid] = useState(true)

  // Interaction State
  const [mode, setMode] = useState<EditorMode>("select")
  const [selectedElement, setSelectedElement] = useState<{
    type: "line" | "zone"
    id: string
  } | null>(null)
  const [dragTarget, setDragTarget] = useState<{
    type: "line_p1" | "line_p2" | "zone_vertex"
    id: string
    vertexIndex?: number
  } | null>(null)

  // In-progress creation state
  const [tempLineStart, setTempLineStart] = useState<Point2D | null>(null)
  const [tempZoneVertices, setTempZoneVertices] = useState<Point2D[]>([])
  const [cursorPoint, setCursorPoint] = useState<Point2D | null>(null)

  const svgRef = useRef<SVGSVGElement | null>(null)

  // Check for unsaved changes
  const hasUnsavedChanges =
    JSON.stringify(config) !== JSON.stringify(initialConfig)

  // Load config & preview frame
  const loadData = useCallback(async () => {
    setLoading(true)
    setErrorMessage(null)
    try {
      const [cfg, frameRes] = await Promise.all([
        vlaserService.getConfig(cameraId),
        vlaserService.getPreviewFrame(cameraId).catch(() => null),
      ])
      setConfig(cfg)
      setInitialConfig(JSON.parse(JSON.stringify(cfg)))
      if (frameRes?.image_data_url) {
        setPreviewImage(frameRes.image_data_url)
      }
    } catch (err) {
      // Create resilient fallback config so user can always edit
      const fallbackCfg: VLaserConfig = {
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
      }
      setConfig(fallbackCfg)
      setInitialConfig(JSON.parse(JSON.stringify(fallbackCfg)))
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to load V-LASER configuration.",
      )
    } finally {
      setLoading(false)
    }
  }, [cameraId, classroom])

  useEffect(() => {
    if (isOpen) {
      void loadData()
      setMode("select")
      setSelectedElement(null)
      setTempLineStart(null)
      setTempZoneVertices([])

      // Poll live spatial tracking state every 2 seconds
      const pollSpatial = async () => {
        try {
          const res = await vlaserService.getSpatialState(cameraId)
          setSpatialState(res)
        } catch {
          // Non-critical background polling
        }
      }
      const interval = setInterval(pollSpatial, 2000)
      void pollSpatial()
      return () => clearInterval(interval)
    }
  }, [isOpen, cameraId, loadData])

  // Coordinate helper: mouse event -> normalized [0.0, 1.0]
  const getNormalizedPoint = useCallback(
    (e: React.MouseEvent<SVGSVGElement>): Point2D => {
      if (!svgRef.current) return { x: 0, y: 0 }
      const rect = svgRef.current.getBoundingClientRect()
      let x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width))
      let y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height))

      if (snapToGrid && config?.grid_cols && config?.grid_rows) {
        const stepX = 1 / config.grid_cols
        const stepY = 1 / config.grid_rows
        x = Math.round(x / stepX) * stepX
        y = Math.round(y / stepY) * stepY
        x = Math.max(0, Math.min(1, x))
        y = Math.max(0, Math.min(1, y))
      }

      return { x: Number(x.toFixed(4)), y: Number(y.toFixed(4)) }
    },
    [config?.grid_cols, config?.grid_rows, snapToGrid],
  )

  // Mouse Move: update cursor point and handle dragging
  const handleMouseMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const pt = getNormalizedPoint(e)
    setCursorPoint(pt)

    if (!dragTarget || !config) return

    if (dragTarget.type === "line_p1") {
      setConfig((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          lines: prev.lines.map((l) =>
            l.id === dragTarget.id ? { ...l, p1: pt } : l,
          ),
        }
      })
    } else if (dragTarget.type === "line_p2") {
      setConfig((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          lines: prev.lines.map((l) =>
            l.id === dragTarget.id ? { ...l, p2: pt } : l,
          ),
        }
      })
    } else if (
      dragTarget.type === "zone_vertex" &&
      dragTarget.vertexIndex !== undefined
    ) {
      const vIdx = dragTarget.vertexIndex
      setConfig((prev) => {
        if (!prev) return prev
        return {
          ...prev,
          zones: prev.zones.map((z) => {
            if (z.id !== dragTarget.id) return z
            const newPoly = [...z.polygon]
            newPoly[vIdx] = pt
            return { ...z, polygon: newPoly }
          }),
        }
      })
    }
  }

  const handleMouseUp = () => {
    setDragTarget(null)
  }

  // Click on Canvas
  const handleCanvasClick = (e: React.MouseEvent<SVGSVGElement>) => {
    const pt = getNormalizedPoint(e)

    if (mode === "draw_line") {
      if (!tempLineStart) {
        setTempLineStart(pt)
      } else {
        // Complete line
        const newLine: VirtualLine = {
          id: `line-${Date.now()}`,
          name: `Virtual Line ${(config?.lines?.length ?? 0) + 1}`,
          line_type: "entry",
          direction: "forward",
          p1: tempLineStart,
          p2: pt,
          color: LINE_TYPE_COLORS.entry,
          enabled: true,
        }
        setConfig((prev) =>
          prev ? { ...prev, lines: [...prev.lines, newLine] } : prev,
        )
        setTempLineStart(null)
        setMode("select")
        setSelectedElement({ type: "line", id: newLine.id })
      }
    } else if (mode === "draw_zone") {
      // Check if clicking near first vertex to close polygon
      if (tempZoneVertices.length >= 3) {
        const first = tempZoneVertices[0]
        const dist = Math.hypot(pt.x - first.x, pt.y - first.y)
        if (dist < 0.04) {
          finishZoneCreation()
          return
        }
      }
      setTempZoneVertices((prev) => [...prev, pt])
    }
  }

  const finishZoneCreation = () => {
    if (tempZoneVertices.length < 3 || !config) {
      setTempZoneVertices([])
      setMode("select")
      return
    }

    const newZone: VirtualZone = {
      id: `zone-${Date.now()}`,
      name: `Classroom Zone ${(config?.zones?.length ?? 0) + 1}`,
      zone_type: "student_seating",
      polygon: tempZoneVertices,
      color: ZONE_TYPE_COLORS.student_seating,
      opacity: 0.25,
      enabled: true,
    }

    setConfig((prev) =>
      prev ? { ...prev, zones: [...prev.zones, newZone] } : prev,
    )
    setTempZoneVertices([])
    setMode("select")
    setSelectedElement({ type: "zone", id: newZone.id })
  }

  // Save handler
  const handleSave = async () => {
    if (!config) return
    setSaving(true)
    setErrorMessage(null)
    setSuccessMessage(null)

    try {
      // Validate with server
      const val = await vlaserService.validateGeometry(config.lines, config.zones)
      if (!val.valid) {
        setErrorMessage(val.errors.join("; "))
        setSaving(false)
        return
      }

      const saved = await vlaserService.saveConfig(cameraId, config)
      setConfig(saved)
      setInitialConfig(JSON.parse(JSON.stringify(saved)))
      setSuccessMessage("V-LASER configuration saved successfully!")
      onSaved?.(saved)
      setTimeout(() => setSuccessMessage(null), 3500)
    } catch (err) {
      setErrorMessage(
        err instanceof Error ? err.message : "Failed to save configuration.",
      )
    } finally {
      setSaving(false)
    }
  }

  // Reset to default
  const handleReset = async () => {
    if (
      !window.confirm(
        "Reset V-LASER configuration to standard classroom default template?",
      )
    )
      return
    setSaving(true)
    try {
      const res = await vlaserService.resetConfig(cameraId)
      setConfig(res.config)
      setInitialConfig(JSON.parse(JSON.stringify(res.config)))
      setSelectedElement(null)
      setSuccessMessage("Reset to factory template successfully.")
      setTimeout(() => setSuccessMessage(null), 3000)
    } catch (err) {
      setErrorMessage(err instanceof Error ? err.message : "Reset failed.")
    } finally {
      setSaving(false)
    }
  }

  // Delete line / zone
  const handleDeleteSelected = () => {
    if (!selectedElement || !config) return
    if (selectedElement.type === "line") {
      setConfig({
        ...config,
        lines: config.lines.filter((l) => l.id !== selectedElement.id),
      })
    } else {
      setConfig({
        ...config,
        zones: config.zones.filter((z) => z.id !== selectedElement.id),
      })
    }
    setSelectedElement(null)
  }

  if (!isOpen) return null

  const activeLine =
    selectedElement?.type === "line" ?
      config?.lines?.find((l) => l.id === selectedElement.id)
    : null

  const activeZone =
    selectedElement?.type === "zone" ?
      config?.zones?.find((z) => z.id === selectedElement.id)
    : null

  return (
    <div
      role="dialog"
      aria-label="V-LASER Virtual Grid Manager"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/85 p-3 backdrop-blur-md sm:p-5">
      <div className="flex h-[94vh] w-full max-w-7xl flex-col overflow-hidden rounded-2xl border border-cyan-500/30 bg-[#0a0c10] text-white shadow-[0_0_50px_rgba(6,182,212,0.15)]">
        {/* Top Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-cyan-500/20 bg-[#0e1118] px-5 py-3">
          <div className="flex items-center gap-3">
            <div className="flex size-9 items-center justify-center rounded-lg border border-cyan-400/40 bg-cyan-500/10 text-cyan-400 shadow-[0_0_15px_rgba(6,182,212,0.4)]">
              <Zap className="size-5 animate-pulse" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold tracking-wider text-white uppercase">
                  V-LASER • Virtual Grid & Boundary Manager
                </h2>
                {hasUnsavedChanges && (
                  <span className="rounded bg-amber-500/20 px-2 py-0.5 text-[10px] font-bold text-amber-300 border border-amber-500/40">
                    Unsaved Changes
                  </span>
                )}
              </div>
              <p className="text-[11px] text-white/55">
                Camera: <span className="font-semibold text-cyan-300">{cameraName}</span> •{" "}
                {classroom || "Classroom"} • Software Laser Grid System
              </p>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={handleReset}
              disabled={saving || loading}
              className="flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/75 hover:bg-white/10 hover:text-white transition">
              <RotateCcw className="size-3.5" />
              Reset Default
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || loading}
              className="flex items-center gap-1.5 rounded-lg border border-cyan-400/50 bg-cyan-500 px-4 py-1.5 text-xs font-semibold text-black shadow-[0_0_15px_rgba(6,182,212,0.4)] hover:bg-cyan-400 active:scale-95 transition">
              {saving ?
                <RefreshCw className="size-3.5 animate-spin" />
              : <Save className="size-3.5" />}
              Save Configuration
            </button>
            <button
              type="button"
              onClick={() => {
                if (hasUnsavedChanges && !window.confirm("Discard unsaved V-LASER changes?")) {
                  return
                }
                onClose()
              }}
              className="rounded-lg border border-white/15 bg-white/5 p-1.5 text-white/70 hover:bg-white/15 hover:text-white">
              <X className="size-4" />
            </button>
          </div>
        </div>

        {/* Status Banners */}
        {errorMessage && (
          <div className="flex items-center gap-2 border-b border-rose-500/30 bg-rose-500/10 px-5 py-2 text-xs text-rose-300">
            <AlertTriangle className="size-4 shrink-0 text-rose-400" />
            <span>{errorMessage}</span>
          </div>
        )}
        {successMessage && (
          <div className="flex items-center gap-2 border-b border-emerald-500/30 bg-emerald-500/10 px-5 py-2 text-xs text-emerald-300">
            <Check className="size-4 shrink-0 text-emerald-400" />
            <span>{successMessage}</span>
          </div>
        )}

        {/* Main Body */}
        <div className="flex flex-1 overflow-hidden">
          {/* Left Canvas Preview Area */}
          <div className="relative flex flex-1 flex-col items-center justify-start overflow-hidden bg-black/95 p-4 gap-2.5">
            {/* Toolbar Header - Positioned cleanly above viewport to prevent obscuring zones */}
            <div className="z-20 flex flex-wrap items-center justify-between w-full max-w-5xl rounded-xl border border-white/10 bg-[#0f131c]/95 p-1.5 shadow-xl backdrop-blur-md">
              <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => {
                  setMode("select")
                  setTempLineStart(null)
                  setTempZoneVertices([])
                }}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                  mode === "select" ?
                    "bg-cyan-500 text-black font-semibold shadow-sm"
                  : "text-white/70 hover:bg-white/10 hover:text-white"
                }`}>
                <Move className="size-3.5" />
                Select / Move
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode("draw_line")
                  setTempLineStart(null)
                  setTempZoneVertices([])
                  setSelectedElement(null)
                }}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                  mode === "draw_line" ?
                    "bg-cyan-500 text-black font-semibold shadow-sm"
                  : "text-white/70 hover:bg-white/10 hover:text-white"
                }`}>
                <Plus className="size-3.5" />
                Draw Line
              </button>
              <button
                type="button"
                onClick={() => {
                  setMode("draw_zone")
                  setTempLineStart(null)
                  setTempZoneVertices([])
                  setSelectedElement(null)
                }}
                className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                  mode === "draw_zone" ?
                    "bg-cyan-500 text-black font-semibold shadow-sm"
                  : "text-white/70 hover:bg-white/10 hover:text-white"
                }`}>
                <Layers className="size-3.5" />
                Draw Polygon Zone
              </button>
            </div>

            <div className="flex items-center gap-1.5">
              {/* Snap toggle */}
              <button
                type="button"
                onClick={() => setSnapToGrid(!snapToGrid)}
                title="Snap coordinates to virtual grid intersections"
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition ${
                  snapToGrid ?
                    "bg-cyan-500/20 text-cyan-300 border border-cyan-500/40"
                  : "text-white/50 hover:text-white"
                }`}>
                <Magnet className="size-3.5" />
                Snap
              </button>

              <div className="mx-1 h-3.5 w-px bg-white/15" />

              {/* Layer Visibility Toggles */}
              <button
                type="button"
                onClick={() => setShowGrid(!showGrid)}
                title="Toggle Virtual Grid"
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition ${
                  showGrid ? "text-cyan-400 font-semibold" : "text-white/40 hover:text-white"
                }`}>
                <Grid3X3 className="size-3.5" />
                Grid
              </button>
              <button
                type="button"
                onClick={() => setShowLines(!showLines)}
                title="Toggle Virtual Laser Lines"
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition ${
                  showLines ? "text-cyan-400 font-semibold" : "text-white/40 hover:text-white"
                }`}>
                Lines
              </button>
              <button
                type="button"
                onClick={() => setShowZones(!showZones)}
                title="Toggle Virtual Zones"
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-xs transition ${
                  showZones ? "text-cyan-400 font-semibold" : "text-white/40 hover:text-white"
                }`}>
                Zones
              </button>
            </div>
          </div>

            {/* In-progress status pill */}
            {mode === "draw_line" && (
              <div className="absolute bottom-6 left-6 z-20 rounded-lg border border-cyan-500/40 bg-black/80 px-3 py-1.5 text-xs text-cyan-300 backdrop-blur-md">
                {!tempLineStart ?
                  "Click canvas to set Line Start point (P1)"
                : "Click canvas to set Line End point (P2)"}
              </div>
            )}
            {mode === "draw_zone" && (
              <div className="absolute bottom-6 left-6 z-20 flex items-center gap-2 rounded-lg border border-cyan-500/40 bg-black/80 px-3 py-1.5 text-xs text-cyan-300 backdrop-blur-md">
                <span>
                  Click vertices ({tempZoneVertices.length} placed). Click near 1st vertex or click Finish:
                </span>
                {tempZoneVertices.length >= 3 && (
                  <button
                    type="button"
                    onClick={finishZoneCreation}
                    className="rounded bg-cyan-500 px-2 py-0.5 font-bold text-black hover:bg-cyan-400">
                    Finish Zone
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setTempZoneVertices([])
                    setMode("select")
                  }}
                  className="rounded bg-white/10 px-2 py-0.5 text-white/70 hover:bg-white/20">
                  Cancel
                </button>
              </div>
            )}

            {/* 16:9 Aspect Ratio Display Viewport */}
            <div className="relative aspect-video max-h-[82vh] w-full max-w-5xl overflow-hidden rounded-xl border border-white/20 bg-neutral-950 shadow-2xl">
              {/* CCTV Reference Video / Image */}
              {previewImage ?
                <img
                  src={previewImage}
                  alt="Camera Live Snapshot"
                  className="absolute inset-0 size-full object-cover"
                />
              : <div className="absolute inset-0 flex items-center justify-center bg-zinc-950 text-white/40">
                  <p className="text-xs">Connecting to camera preview...</p>
                </div>
              }

              {/* Interactive SVG Layer (Normalized 0 0 1000 1000) */}
              <svg
                ref={svgRef}
                viewBox="0 0 1000 1000"
                preserveAspectRatio="none"
                onClick={handleCanvasClick}
                onMouseMove={handleMouseMove}
                onMouseUp={handleMouseUp}
                className="absolute inset-0 size-full cursor-crosshair select-none">
                <defs>
                  {/* Laser Beam Glow Filter */}
                  <filter id="vlaser-glow" x="-30%" y="-30%" width="160%" height="160%">
                    <feGaussianBlur stdDeviation="6" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                  <filter id="laser-dot-glow">
                    <feGaussianBlur stdDeviation="3" result="blur" />
                    <feMerge>
                      <feMergeNode in="blur" />
                      <feMergeNode in="SourceGraphic" />
                    </feMerge>
                  </filter>
                  <marker
                    id="arrow-entry"
                    viewBox="0 0 10 10"
                    refX="5"
                    refY="5"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto-start-reverse">
                    <path d="M 0 1 L 10 5 L 0 9 z" fill="#10b981" />
                  </marker>
                  <marker
                    id="arrow-exit"
                    viewBox="0 0 10 10"
                    refX="5"
                    refY="5"
                    markerWidth="6"
                    markerHeight="6"
                    orient="auto-start-reverse">
                    <path d="M 0 1 L 10 5 L 0 9 z" fill="#f97316" />
                  </marker>
                </defs>

                {/* 1. Virtual Grid Layer */}
                {showGrid && config?.grid_enabled && (
                  <g opacity={config.grid_opacity || 0.25}>
                    {/* Vertical Grid Lines */}
                    {Array.from({ length: (config.grid_cols || 10) + 1 }).map((_, i) => {
                      const x = (i / (config.grid_cols || 10)) * 1000
                      return (
                        <line
                          key={`gv-${i}`}
                          x1={x}
                          y1={0}
                          x2={x}
                          y2={1000}
                          stroke={config.grid_color || "#00f3ff"}
                          strokeWidth="1"
                          strokeDasharray="2 4"
                        />
                      )
                    })}
                    {/* Horizontal Grid Lines */}
                    {Array.from({ length: (config.grid_rows || 10) + 1 }).map((_, i) => {
                      const y = (i / (config.grid_rows || 10)) * 1000
                      return (
                        <line
                          key={`gh-${i}`}
                          x1={0}
                          y1={y}
                          x2={1000}
                          y2={y}
                          stroke={config.grid_color || "#00f3ff"}
                          strokeWidth="1"
                          strokeDasharray="2 4"
                        />
                      )
                    })}
                  </g>
                )}

                {/* 2. Virtual Zones (Polygons) */}
                {showZones &&
                  (config?.zones ?? []).map((zone) => {
                    if (!zone.enabled && selectedElement?.id !== zone.id) return null
                    const pts = zone.polygon
                      .map((p) => `${p.x * 1000},${p.y * 1000}`)
                      .join(" ")
                    const isSelected =
                      selectedElement?.type === "zone" && selectedElement.id === zone.id
                    const color =
                      zone.color || ZONE_TYPE_COLORS[zone.zone_type] || "#06b6d4"

                    return (
                      <g key={zone.id}>
                        <polygon
                          points={pts}
                          fill={color}
                          fillOpacity={zone.opacity || 0.25}
                          stroke={color}
                          strokeWidth={isSelected ? 3 : 1.5}
                          strokeDasharray={isSelected ? "6 3" : undefined}
                          filter="url(#vlaser-glow)"
                          className="transition-all hover:fill-opacity-40"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedElement({ type: "zone", id: zone.id })
                          }}
                        />

                        {/* Zone Center HUD Pill Badge */}
                        {zone.polygon.length >= 3 && (() => {
                          const cx =
                            (zone.polygon.reduce((acc, p) => acc + p.x, 0) / zone.polygon.length) *
                            1000
                          const cy =
                            (zone.polygon.reduce((acc, p) => acc + p.y, 0) / zone.polygon.length) *
                            1000
                          const badgeW = Math.max(90, zone.name.length * 8.5)
                          return (
                            <g transform={`translate(${cx}, ${cy})`}>
                              <rect
                                x={-badgeW / 2}
                                y="-12"
                                width={badgeW}
                                height="24"
                                rx="4"
                                fill="rgba(10, 14, 22, 0.9)"
                                stroke={color}
                                strokeWidth={isSelected ? 1.5 : 1}
                              />
                              <circle cx={-badgeW / 2 + 10} cy="0" r="3.5" fill={color} />
                              <text
                                x="4"
                                y="4"
                                textAnchor="middle"
                                fill="#ffffff"
                                fontSize="11.5"
                                fontWeight="bold"
                                letterSpacing="0.3"
                                className="pointer-events-none select-none">
                                {zone.name}
                              </text>
                            </g>
                          )
                        })()}

                        {/* Draggable Vertex Handles for Selected Zone */}
                        {isSelected &&
                          zone.polygon.map((p, vIdx) => (
                            <circle
                              key={`v-${zone.id}-${vIdx}`}
                              cx={p.x * 1000}
                              cy={p.y * 1000}
                              r={8}
                              fill="#ffffff"
                              stroke={color}
                              strokeWidth={3}
                              className="cursor-pointer transition-transform hover:scale-125"
                              onMouseDown={(e) => {
                                e.stopPropagation()
                                setDragTarget({
                                  type: "zone_vertex",
                                  id: zone.id,
                                  vertexIndex: vIdx,
                                })
                              }}
                            />
                          ))}
                      </g>
                    )
                  })}

                {/* 3. Virtual Laser Lines */}
                {showLines &&
                  (config?.lines ?? []).map((line) => {
                    if (!line.enabled && selectedElement?.id !== line.id) return null
                    const isSelected =
                      selectedElement?.type === "line" && selectedElement.id === line.id
                    const color =
                      line.color || LINE_TYPE_COLORS[line.line_type] || "#3b82f6"
                    const x1 = line.p1.x * 1000
                    const y1 = line.p1.y * 1000
                    const x2 = line.p2.x * 1000
                    const y2 = line.p2.y * 1000

                    return (
                      <g key={line.id}>
                        {/* Glow Beam */}
                        <line
                          x1={x1}
                          y1={y1}
                          x2={x2}
                          y2={y2}
                          stroke={color}
                          strokeWidth={isSelected ? 6 : 3.5}
                          strokeLinecap="round"
                          filter="url(#vlaser-glow)"
                          className="cursor-pointer"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedElement({ type: "line", id: line.id })
                          }}
                        />
                        {/* Inner Bright Laser Filament */}
                        <line
                          x1={x1}
                          y1={y1}
                          x2={x2}
                          y2={y2}
                          stroke="#ffffff"
                          strokeWidth={1.5}
                          strokeLinecap="round"
                          className="pointer-events-none"
                        />

                        {/* Midpoint HUD Pill Badge & Direction */}
                        {(() => {
                          const labelText = `${line.name} (${line.line_type.toUpperCase()})`
                          const pillW = Math.max(100, labelText.length * 8)
                          return (
                            <g transform={`translate(${(x1 + x2) / 2}, ${(y1 + y2) / 2 - 14})`}>
                              <rect
                                x={-pillW / 2}
                                y="-10"
                                width={pillW}
                                height="20"
                                rx="3"
                                fill="rgba(8, 11, 18, 0.92)"
                                stroke={color}
                                strokeWidth={isSelected ? 1.2 : 0.8}
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
                                {labelText}
                              </text>
                            </g>
                          )
                        })()}

                        {/* Line End Points Handles */}
                        {isSelected && (
                          <>
                            <circle
                              cx={x1}
                              cy={y1}
                              r={8}
                              fill="#ffffff"
                              stroke={color}
                              strokeWidth={3}
                              className="cursor-pointer hover:scale-125"
                              onMouseDown={(e) => {
                                e.stopPropagation()
                                setDragTarget({ type: "line_p1", id: line.id })
                              }}
                            />
                            <circle
                              cx={x2}
                              cy={y2}
                              r={8}
                              fill="#ffffff"
                              stroke={color}
                              strokeWidth={3}
                              className="cursor-pointer hover:scale-125"
                              onMouseDown={(e) => {
                                e.stopPropagation()
                                setDragTarget({ type: "line_p2", id: line.id })
                              }}
                            />
                          </>
                        )}
                      </g>
                    )
                  })}

                {/* 4. Active In-Progress Line Drawing */}
                {mode === "draw_line" && tempLineStart && cursorPoint && (
                  <line
                    x1={tempLineStart.x * 1000}
                    y1={tempLineStart.y * 1000}
                    x2={cursorPoint.x * 1000}
                    y2={cursorPoint.y * 1000}
                    stroke="#00f3ff"
                    strokeWidth={3}
                    strokeDasharray="8 4"
                    filter="url(#vlaser-glow)"
                  />
                )}

                {/* 5. Active In-Progress Zone Drawing */}
                {mode === "draw_zone" && tempZoneVertices.length > 0 && (
                  <g>
                    {tempZoneVertices.map((p, idx) => (
                      <circle
                        key={`tz-${idx}`}
                        cx={p.x * 1000}
                        cy={p.y * 1000}
                        r={6}
                        fill="#00f3ff"
                        stroke="#ffffff"
                        strokeWidth={2}
                      />
                    ))}
                    <polyline
                      points={[
                        ...tempZoneVertices.map((p) => `${p.x * 1000},${p.y * 1000}`),
                        cursorPoint ? `${cursorPoint.x * 1000},${cursorPoint.y * 1000}` : "",
                      ]
                        .filter(Boolean)
                        .join(" ")}
                      fill="none"
                      stroke="#00f3ff"
                      strokeWidth={2.5}
                      strokeDasharray="6 3"
                    />
                  </g>
                )}

                {/* 6. Active Live Tracked Persons (Laser Targeting Reticle at Bottom-Center) */}
                {(spatialState?.active_tracks ?? []).map((track) => {
                  const isVerified = track.identity_state === "identity_verified"
                  const isPending = track.identity_state === "pending_verification"
                  const isUnknown = track.identity_state === "unknown_person"
                  const color =
                    isVerified ? "#10b981"
                    : isUnknown ? "#f43f5e"
                    : isPending ? "#eab308"
                    : "#00f3ff"
                  const label =
                    isVerified ?
                      `Track #${track.track_id} • ${track.student_name || "Verified"}`
                    : isPending ?
                      `Track #${track.track_id} • Pending Face`
                    : isUnknown ?
                      `Track #${track.track_id} • Unknown`
                    : `Track #${track.track_id} (${track.current_zone_name || "Unassigned"})`

                  return (
                    <g key={`track-dot-${track.track_id}`}>
                      <circle
                        cx={track.anchor.x * 1000}
                        cy={track.anchor.y * 1000}
                        r={14}
                        fill="none"
                        stroke={color}
                        strokeWidth={1.5}
                        strokeDasharray="4 2"
                        opacity={0.85}
                      />
                      <circle
                        cx={track.anchor.x * 1000}
                        cy={track.anchor.y * 1000}
                        r={5}
                        fill={color}
                        filter="url(#laser-dot-glow)"
                      />
                      {/* Floating HUD Tag Above Tracked Person */}
                      {(() => {
                        const badgeW = Math.min(160, Math.max(90, label.length * 7))
                        return (
                          <g transform={`translate(${track.anchor.x * 1000}, ${track.anchor.y * 1000 - 22})`}>
                            <rect
                              x={-badgeW / 2}
                              y="-9"
                              width={badgeW}
                              height="18"
                              rx="3"
                              fill="rgba(6, 9, 15, 0.92)"
                              stroke={color}
                              strokeWidth="1"
                            />
                            <text
                              x="0"
                              y="3"
                              textAnchor="middle"
                              fill={color}
                              fontSize="9.5"
                              fontWeight="bold"
                              className="pointer-events-none select-none">
                              {label.length > 22 ? `${label.slice(0, 22)}…` : label}
                            </text>
                          </g>
                        )
                      })()}
                    </g>
                  )
                })}
              </svg>
            </div>
          </div>

          {/* Right Properties & Inspector Panel */}
          <div className="w-80 border-l border-white/10 bg-[#0c0e14] p-4 overflow-y-auto">
            <h3 className="text-xs font-bold uppercase tracking-wider text-white/50 mb-3">
              Configuration & Inspector
            </h3>

            {/* Selected Element Editor */}
            {activeLine ?
              <div className="rounded-xl border border-white/10 bg-white/5 p-3.5 mb-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-cyan-300">Virtual Line Settings</span>
                  <button
                    type="button"
                    onClick={handleDeleteSelected}
                    title="Delete Line"
                    className="rounded p-1 text-rose-400 hover:bg-rose-500/20">
                    <Trash2 className="size-4" />
                  </button>
                </div>

                <div>
                  <label className="text-[11px] text-white/60">Line Name</label>
                  <input
                    type="text"
                    value={activeLine.name}
                    onChange={(e) => {
                      const name = e.target.value
                      setConfig((prev) =>
                        prev ?
                          {
                            ...prev,
                            lines: prev.lines.map((l) =>
                              l.id === activeLine.id ? { ...l, name } : l,
                            ),
                          }
                        : prev,
                      )
                    }}
                    className="mt-1 w-full rounded border border-white/15 bg-black/50 px-2 py-1 text-xs text-white"
                  />
                </div>

                <div>
                  <label className="text-[11px] text-white/60">Line Type</label>
                  <select
                    value={activeLine.line_type}
                    onChange={(e) => {
                      const line_type = e.target.value as LineType
                      setConfig((prev) =>
                        prev ?
                          {
                            ...prev,
                            lines: prev.lines.map((l) =>
                              l.id === activeLine.id ?
                                {
                                  ...l,
                                  line_type,
                                  color: LINE_TYPE_COLORS[line_type],
                                }
                              : l,
                            ),
                          }
                        : prev,
                      )
                    }}
                    className="mt-1 w-full rounded border border-white/15 bg-black/50 px-2 py-1 text-xs text-white">
                    <option value="entry">Entry Line</option>
                    <option value="exit">Exit Line</option>
                    <option value="internal">Internal Movement Line</option>
                    <option value="restricted">Restricted Boundary</option>
                  </select>
                </div>

                <div>
                  <label className="text-[11px] text-white/60">Crossing Direction</label>
                  <select
                    value={activeLine.direction}
                    onChange={(e) => {
                      const direction = e.target.value as LineDirection
                      setConfig((prev) =>
                        prev ?
                          {
                            ...prev,
                            lines: prev.lines.map((l) =>
                              l.id === activeLine.id ? { ...l, direction } : l,
                            ),
                          }
                        : prev,
                      )
                    }}
                    className="mt-1 w-full rounded border border-white/15 bg-black/50 px-2 py-1 text-xs text-white">
                    <option value="bidirectional">Bidirectional (Both Ways)</option>
                    <option value="forward">Forward (P1 → P2)</option>
                    <option value="backward">Backward (P2 → P1)</option>
                  </select>
                </div>
              </div>
            : activeZone ?
              <div className="rounded-xl border border-white/10 bg-white/5 p-3.5 mb-4 space-y-3">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold text-cyan-300">Classroom Zone Settings</span>
                  <button
                    type="button"
                    onClick={handleDeleteSelected}
                    title="Delete Zone"
                    className="rounded p-1 text-rose-400 hover:bg-rose-500/20">
                    <Trash2 className="size-4" />
                  </button>
                </div>

                <div>
                  <label className="text-[11px] text-white/60">Zone Name</label>
                  <input
                    type="text"
                    value={activeZone.name}
                    onChange={(e) => {
                      const name = e.target.value
                      setConfig((prev) =>
                        prev ?
                          {
                            ...prev,
                            zones: prev.zones.map((z) =>
                              z.id === activeZone.id ? { ...z, name } : z,
                            ),
                          }
                        : prev,
                      )
                    }}
                    className="mt-1 w-full rounded border border-white/15 bg-black/50 px-2 py-1 text-xs text-white"
                  />
                </div>

                <div>
                  <label className="text-[11px] text-white/60">Zone Type</label>
                  <select
                    value={activeZone.zone_type}
                    onChange={(e) => {
                      const zone_type = e.target.value as ZoneType
                      setConfig((prev) =>
                        prev ?
                          {
                            ...prev,
                            zones: prev.zones.map((z) =>
                              z.id === activeZone.id ?
                                {
                                  ...z,
                                  zone_type,
                                  color: ZONE_TYPE_COLORS[zone_type],
                                }
                              : z,
                            ),
                          }
                        : prev,
                      )
                    }}
                    className="mt-1 w-full rounded border border-white/15 bg-black/50 px-2 py-1 text-xs text-white">
                    {Object.entries(ZONE_TYPE_LABELS).map(([k, v]) => (
                      <option key={k} value={k}>
                        {v}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="text-[11px] text-white/60">Opacity: {activeZone.opacity}</label>
                  <input
                    type="range"
                    min="0.1"
                    max="0.8"
                    step="0.05"
                    value={activeZone.opacity}
                    onChange={(e) => {
                      const opacity = parseFloat(e.target.value)
                      setConfig((prev) =>
                        prev ?
                          {
                            ...prev,
                            zones: prev.zones.map((z) =>
                              z.id === activeZone.id ? { ...z, opacity } : z,
                            ),
                          }
                        : prev,
                      )
                    }}
                    className="w-full"
                  />
                </div>
              </div>
            : <div className="rounded-xl border border-dashed border-white/15 p-4 text-center text-xs text-white/40 mb-4">
                Click any line or zone on the canvas to inspect and edit its properties.
              </div>
            }

            {/* Global Grid Settings */}
            <div className="rounded-xl border border-white/10 bg-white/5 p-3.5 mb-4 space-y-3">
              <span className="text-xs font-bold text-white/80">Grid Dimension & Style</span>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-[10px] text-white/60">Cols (X)</label>
                  <input
                    type="number"
                    min="2"
                    max="40"
                    value={config?.grid_cols || 10}
                    onChange={(e) => {
                      const grid_cols = Math.max(2, parseInt(e.target.value) || 10)
                      setConfig((prev) => (prev ? { ...prev, grid_cols } : prev))
                    }}
                    className="w-full rounded border border-white/15 bg-black/50 px-2 py-1 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="text-[10px] text-white/60">Rows (Y)</label>
                  <input
                    type="number"
                    min="2"
                    max="40"
                    value={config?.grid_rows || 10}
                    onChange={(e) => {
                      const grid_rows = Math.max(2, parseInt(e.target.value) || 10)
                      setConfig((prev) => (prev ? { ...prev, grid_rows } : prev))
                    }}
                    className="w-full rounded border border-white/15 bg-black/50 px-2 py-1 text-xs text-white"
                  />
                </div>
              </div>

              <div>
                <label className="text-[10px] text-white/60">
                  Grid Opacity: {config?.grid_opacity ?? 0.25}
                </label>
                <input
                  type="range"
                  min="0.05"
                  max="0.8"
                  step="0.05"
                  value={config?.grid_opacity ?? 0.25}
                  onChange={(e) => {
                    const grid_opacity = parseFloat(e.target.value)
                    setConfig((prev) => (prev ? { ...prev, grid_opacity } : prev))
                  }}
                  className="w-full"
                />
              </div>
            </div>

            {/* Configured Entities List */}
            <div className="space-y-2">
              <span className="text-[11px] font-bold text-white/60 uppercase">
                Lines ({(config?.lines?.length ?? 0)})
              </span>
              <div className="space-y-1">
                {(config?.lines ?? []).map((l) => (
                  <div
                    key={l.id}
                    onClick={() => setSelectedElement({ type: "line", id: l.id })}
                    className={`flex cursor-pointer items-center justify-between rounded-lg border px-2.5 py-1.5 text-xs transition ${
                      selectedElement?.id === l.id ?
                        "border-cyan-400 bg-cyan-500/15 text-cyan-200"
                      : "border-white/10 bg-black/30 text-white/75 hover:bg-white/5"
                    }`}>
                    <div className="flex items-center gap-2">
                      <span
                        className="size-2 rounded-full"
                        style={{ backgroundColor: l.color || LINE_TYPE_COLORS[l.line_type] }}
                      />
                      <span className="font-medium">{l.name}</span>
                    </div>
                    <span className="text-[10px] uppercase text-white/45">
                      {l.line_type}
                    </span>
                  </div>
                ))}
              </div>

              <span className="text-[11px] font-bold text-white/60 uppercase pt-2 block">
                Zones ({(config?.zones?.length ?? 0)})
              </span>
              <div className="space-y-1">
                {(config?.zones ?? []).map((z) => (
                  <div
                    key={z.id}
                    onClick={() => setSelectedElement({ type: "zone", id: z.id })}
                    className={`flex cursor-pointer items-center justify-between rounded-lg border px-2.5 py-1.5 text-xs transition ${
                      selectedElement?.id === z.id ?
                        "border-cyan-400 bg-cyan-500/15 text-cyan-200"
                      : "border-white/10 bg-black/30 text-white/75 hover:bg-white/5"
                    }`}>
                    <div className="flex items-center gap-2">
                      <span
                        className="size-2 rounded-full"
                        style={{ backgroundColor: z.color || ZONE_TYPE_COLORS[z.zone_type] }}
                      />
                      <span className="font-medium">{z.name}</span>
                    </div>
                    <span className="text-[10px] uppercase text-white/45">
                      {z.polygon.length} pts
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Live Spatial Telemetry & Event Feed */}
            <div className="mt-4 pt-3 border-t border-white/10 space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[11px] font-bold text-cyan-300 uppercase tracking-wider flex items-center gap-1.5">
                  <span className="size-2 rounded-full bg-cyan-400 animate-ping" />
                  Live Spatial Tracking
                </span>
                <span className="rounded bg-cyan-500/20 px-1.5 py-0.5 text-[10px] font-bold text-cyan-300 border border-cyan-500/30">
                  {spatialState?.active_tracks_count ?? 0} active
                </span>
              </div>

              {/* Zone Headcounts */}
              {spatialState?.zone_headcounts && (
                <div className="rounded-lg border border-white/10 bg-black/40 p-2 text-[11px] space-y-1">
                  <div className="text-[10px] text-white/50 uppercase font-semibold">Zone Headcounts</div>
                  {Object.entries(spatialState.zone_headcounts).map(([zid, count]) => {
                    const zoneObj = config?.zones?.find((z) => z.id === zid)
                    const label = zoneObj?.name || (zid === "unassigned" ? "Unassigned Area" : zid)
                    return (
                      <div key={zid} className="flex items-center justify-between text-white/80">
                        <span className="truncate pr-2">{label}</span>
                        <span className="font-mono font-bold text-cyan-300">{count}</span>
                      </div>
                    )
                  })}
                </div>
              )}

              {/* Active Tracks & Identity States */}
              {spatialState?.active_tracks && spatialState.active_tracks.length > 0 && (
                <div className="rounded-lg border border-white/10 bg-black/40 p-2 text-[11px] space-y-1.5">
                  <div className="text-[10px] text-white/50 uppercase font-semibold">Active Tracks & Identity</div>
                  {spatialState.active_tracks.map((tr) => (
                    <div key={`track-meta-${tr.track_id}`} className="flex flex-col gap-0.5 rounded border border-white/5 bg-white/5 p-1.5">
                      <div className="flex items-center justify-between">
                        <span className="font-bold text-white/90">Track #{tr.track_id}</span>
                        <span
                          className={`rounded px-1 py-0.2 text-[9px] font-bold uppercase ${
                            tr.identity_state === "identity_verified" ? "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                            : tr.identity_state === "unknown_person" ? "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                            : tr.identity_state === "pending_verification" ? "bg-amber-500/20 text-amber-400 border border-amber-500/30"
                            : tr.identity_state === "face_processing" ? "bg-sky-500/20 text-sky-400 border border-sky-500/30"
                            : "bg-cyan-500/20 text-cyan-400 border border-cyan-500/30"
                          }`}>
                          {tr.identity_state === "identity_verified" ? "Verified"
                          : tr.identity_state === "unknown_person" ? "Unknown"
                          : tr.identity_state === "pending_verification" ? "Pending"
                          : tr.identity_state === "face_processing" ? "Face Proc"
                          : "Spatial Only"}
                        </span>
                      </div>
                      {tr.student_name && (
                        <div className="text-emerald-300 font-medium truncate">{tr.student_name}</div>
                      )}
                      <div className="flex items-center justify-between text-[9.5px] text-white/50">
                        <span>Zone: {tr.current_zone_name || "Unassigned"}</span>
                        <span>{tr.attendance_eligible ? "Attendance Ready" : "Tracking"}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Recent Spatial Events Stream */}
              <div className="space-y-1.5">
                <div className="text-[10px] text-white/50 uppercase font-semibold">Recent Events</div>
                {!spatialState?.recent_events?.length ?
                  <div className="text-[11px] text-white/35 italic">No spatial events detected yet.</div>
                : spatialState.recent_events.slice(0, 5).map((ev) => (
                    <div
                      key={ev.id}
                      className="rounded border border-white/10 bg-black/50 p-1.5 text-[10.5px] text-white/75">
                      <div className="flex items-center justify-between font-semibold">
                        <span
                          className={
                            ev.event_type === "entry" ? "text-emerald-400"
                            : ev.event_type === "exit" ? "text-orange-400"
                            : ev.event_type === "restricted_violation" ? "text-rose-400"
                            : "text-cyan-300"
                          }>
                          {ev.event_type.toUpperCase().replaceAll("_", " ")}
                        </span>
                        <span className="font-mono text-[9px] text-white/40">
                          Track #{ev.track_id}
                        </span>
                      </div>
                      <div className="text-white/60 truncate">
                        {ev.line_name ?
                          `Line: ${ev.line_name}`
                        : ev.to_zone_name ?
                          `Zone: ${ev.to_zone_name}`
                        : "Boundary crossed"}
                      </div>
                    </div>
                  ))
                }
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
