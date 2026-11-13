import { useCallback, useEffect, useState } from "react"
import {
  Activity,
  Camera,
  Cpu,
  Plus,
  RefreshCw,
  ShieldAlert,
  Trash2,
  Wrench,
  Zap,
} from "lucide-react"
import { VLaserEditorModal } from "./vlaser"
import {
  cctvService,
  type AdminOverviewResponse,
  type CctvCameraLogRecord,
  type CctvCameraRecord,
} from "@/services/cctvService"
import { vlaserService } from "@/services/vlaserService"
import type { SpatialEvent } from "@/types/vlaser"
import { useAttendanceStore, useDetectionStore } from "@/components/main/stores"

const CAM_STATUS_BADGE: Record<string, string> = {
  online: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  unstable: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  recovering: "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  offline: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  recording_failed: "bg-rose-500/20 text-rose-200 border-rose-500/40",
}

const QUALITY_DOT: Record<string, string> = {
  green: "bg-emerald-400",
  yellow: "bg-amber-400",
  red: "bg-rose-500",
}

export function AdminCctvDashboard() {
  const { attendanceGroups } = useAttendanceStore()
  const { activeCctvCameraId, setActiveCctvCameraId } = useDetectionStore()
  const [overview, setOverview] = useState<AdminOverviewResponse | null>(null)
  const [cameras, setCameras] = useState<CctvCameraRecord[]>([])
  const [logs, setLogs] = useState<CctvCameraLogRecord[]>([])
  const [spatialEvents, setSpatialEvents] = useState<SpatialEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [vlaserCamera, setVlaserCamera] = useState<{
    id: string
    name: string
    classroom?: string | null
  } | null>(null)

  // Filters
  const [deptFilter, setDeptFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState("")

  // New camera form
  const [showAdd, setShowAdd] = useState(false)
  const [name, setName] = useState("")
  const [code, setCode] = useState("")
  const [sourceType, setSourceType] = useState("simulated")
  const [sourceUri, setSourceUri] = useState("0")
  const [supportsIr, setSupportsIr] = useState(false)
  const [department, setDepartment] = useState("CSE")
  const [building, setBuilding] = useState("Academic Block A")
  const [classroom, setClassroom] = useState("LH-101")
  const [assignedGroupId, setAssignedGroupId] = useState("")
  const [backupCameraId, setBackupCameraId] = useState("")

  const loadAll = useCallback(async () => {
    setLoading(true)
    try {
      const filters: Record<string, string> = {}
      if (deptFilter.trim()) filters.department = deptFilter.trim()
      if (statusFilter) filters.status = statusFilter

      const [ov, cams, camLogs, recentSpatial] = await Promise.all([
        cctvService.getAdminOverview(),
        cctvService.listCameras(filters),
        cctvService.listCameraLogs(),
        vlaserService.getAllRecentEvents(30).catch(() => ({ count: 0, events: [] })),
      ])
      setOverview(ov)
      setCameras(cams)
      setLogs(camLogs)
      setSpatialEvents(recentSpatial.events || [])
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to load admin telemetry")
    } finally {
      setLoading(false)
    }
  }, [deptFilter, statusFilter])

  useEffect(() => {
    void loadAll()
    const interval = setInterval(() => {
      vlaserService
        .getAllRecentEvents(30)
        .then((res) => {
          if (res?.events) setSpatialEvents(res.events)
        })
        .catch(() => {})
    }, 3000)
    return () => clearInterval(interval)
  }, [loadAll])

  const handleCreateCamera = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim() || !code.trim()) return
    try {
      await cctvService.createCamera({
        name: name.trim(),
        camera_code: code.trim(),
        source_type: sourceType,
        source_uri: sourceUri.trim() || null,
        supports_ir: supportsIr,
        department: department.trim() || null,
        building: building.trim() || null,
        classroom: classroom.trim() || null,
        assigned_group_id: assignedGroupId || null,
        backup_camera_id: backupCameraId || null,
      })
      setShowAdd(false)
      setName("")
      setCode("")
      setMessage("Registered and probed camera successfully.")
      await loadAll()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Camera registration failed")
    }
  }

  const handleSimulate = async (camId: string, fault: string | null) => {
    try {
      await cctvService.simulateFault(camId, fault)
      setMessage(fault ? `Simulated fault "${fault}" applied.` : "Fault cleared & reconnected.")
      await loadAll()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Fault simulation failed")
    }
  }

  const handleProbe = async (camId: string) => {
    try {
      const res = await cctvService.probeCamera(camId)
      setMessage(`Probe complete: ${res.camera.status} (${res.camera.quality_status})`)
      await loadAll()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Probe failed")
    }
  }

  const handleReconnect = async (camId: string) => {
    try {
      const res = await cctvService.reconnectCamera(camId, true)
      setMessage(
        res.reconnected ? "Camera reconnected cleanly." : "Reconnection failed; check source.",
      )
      await loadAll()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Reconnect failed")
    }
  }

  const handleDeactivate = async (camId: string) => {
    try {
      await cctvService.deleteCamera(camId)
      if (activeCctvCameraId === camId) setActiveCctvCameraId(null)
      setMessage("Camera deactivated.")
      await loadAll()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : "Failed to deactivate camera")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      {/* KPI Cards */}
      {overview && (
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
          <div className="rounded-xl border border-white/10 bg-[#131620] p-3">
            <div className="flex items-center justify-between text-xs text-white/60">
              <span>Cameras Online</span>
              <Camera className="size-4 text-emerald-400" />
            </div>
            <div className="mt-1 text-xl font-bold text-white">
              {overview.cameras.online} / {overview.cameras.total}
            </div>
            <div className="mt-1 text-[11px] text-white/50">
              Offline: {overview.cameras.offline} • Unstable: {overview.cameras.unstable} • Backup:{" "}
              {overview.cameras.with_backup}
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-[#131620] p-3">
            <div className="flex items-center justify-between text-xs text-white/60">
              <span>Image Visibility</span>
              <Activity className="size-4 text-cyan-400" />
            </div>
            <div className="mt-1 flex items-center gap-3 text-sm font-bold">
              <span className="text-emerald-300">G: {overview.cameras.quality_green}</span>
              <span className="text-amber-300">Y: {overview.cameras.quality_yellow}</span>
              <span className="text-rose-300">R: {overview.cameras.quality_red}</span>
            </div>
            <div className="mt-1 text-[11px] text-white/50">
              Recording Failed: {overview.cameras.recording_failed}
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-[#131620] p-3">
            <div className="flex items-center justify-between text-xs text-white/60">
              <span>Active Incidents</span>
              <ShieldAlert className="size-4 text-amber-400" />
            </div>
            <div className="mt-1 text-xl font-bold text-amber-200">
              {overview.alerts.open_camera_incidents}
            </div>
            <div className="mt-1 text-[11px] text-white/50">
              Unknowns: {overview.alerts.pending_unknown_students} • Mismatches:{" "}
              {overview.alerts.open_section_mismatches}
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-[#131620] p-3">
            <div className="flex items-center justify-between text-xs text-white/60">
              <span>AI Recognition Stack</span>
              <Cpu className="size-4 text-indigo-400" />
            </div>
            <div className="mt-1 text-sm font-semibold text-white">
              {overview.model_health.detector_loaded && overview.model_health.recognizer_loaded ?
                "ONNX Pipeline Active"
              : "Warming / Standby"}
            </div>
            <div className="mt-1 text-[11px] text-white/50">
              Enrolled Faces: {overview.model_health.enrolled_embeddings} • Liveness:{" "}
              {overview.model_health.liveness_loaded ? "Ready" : "Off"}
            </div>
          </div>

          <div className="rounded-xl border border-white/10 bg-[#131620] p-3">
            <div className="flex items-center justify-between text-xs text-white/60">
              <span>V-LASER Spatial Grid</span>
              <Zap className="size-4 text-cyan-400" />
            </div>
            <div className="mt-1 text-sm font-bold text-cyan-200">
              {spatialEvents.length} Recent Events
            </div>
            <div className="mt-1 text-[11px] text-white/50">
              Entries: {spatialEvents.filter((e) => e.event_type === "entry").length} • Exits:{" "}
              {spatialEvents.filter((e) => e.event_type === "exit").length} • Violations:{" "}
              {spatialEvents.filter((e) => e.event_type === "restricted_violation").length}
            </div>
          </div>
        </div>
      )}

      {/* Toolbar & Filters */}
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={deptFilter}
            onChange={(e) => setDeptFilter(e.target.value)}
            placeholder="Filter department (e.g. CSE)"
            className="rounded-lg border border-white/15 bg-[#151821] px-2.5 py-1.5 text-xs text-white"
          />
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#151821] px-2.5 py-1.5 text-xs text-white">
            <option value="">All Statuses</option>
            <option value="online">Online</option>
            <option value="unstable">Unstable</option>
            <option value="offline">Offline</option>
            <option value="recording_failed">Recording Failed</option>
          </select>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void loadAll()}
            className="inline-flex items-center gap-1 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs text-white/80 hover:bg-white/10">
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setShowAdd((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-black hover:bg-cyan-400">
            <Plus className="size-3.5" />
            Add CCTV / Webcam
          </button>
        </div>
      </div>

      {message && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-950/40 px-3 py-2 text-xs text-cyan-100">
          {message}
        </div>
      )}

      {/* Add Camera Form */}
      {showAdd && (
        <form
          onSubmit={handleCreateCamera}
          className="grid grid-cols-1 gap-3 rounded-xl border border-cyan-500/30 bg-[#121722] p-4 sm:grid-cols-3 text-xs">
          <div>
            <label className="mb-1 block text-[11px] text-white/60">Camera Name</label>
            <input
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="CS Block LH-101 Front"
              className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-white/60">Camera Code</label>
            <input
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="CAM-101"
              className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-white/60">Source Type</label>
            <select
              value={sourceType}
              onChange={(e) => setSourceType(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white">
              <option value="simulated">Simulated CCTV Classroom</option>
              <option value="rtsp">RTSP IP Camera Stream</option>
              <option value="webcam">Local Webcam Index</option>
              <option value="video_file">Recorded Video File</option>
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-white/60">
              Stream URI / Device Index
            </label>
            <input
              value={sourceUri}
              onChange={(e) => setSourceUri(e.target.value)}
              placeholder="rtsp://... or 0"
              className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-white/60">Department / Building</label>
            <div className="flex gap-1.5">
              <input
                value={department}
                onChange={(e) => setDepartment(e.target.value)}
                placeholder="Dept"
                className="w-1/2 rounded-lg border border-white/15 bg-[#0e1118] px-2 py-1.5 text-white"
              />
              <input
                value={building}
                onChange={(e) => setBuilding(e.target.value)}
                placeholder="Building"
                className="w-1/2 rounded-lg border border-white/15 bg-[#0e1118] px-2 py-1.5 text-white"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-white/60">Classroom</label>
            <input
              value={classroom}
              onChange={(e) => setClassroom(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-white/60">Assigned Group</label>
            <select
              value={assignedGroupId}
              onChange={(e) => setAssignedGroupId(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white">
              <option value="">None</option>
              {attendanceGroups
                .filter((g) => g.id !== "all")
                .map((g) => (
                  <option key={g.id} value={g.id}>
                    {g.name}
                  </option>
                ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] text-white/60">Backup Camera</label>
            <select
              value={backupCameraId}
              onChange={(e) => setBackupCameraId(e.target.value)}
              className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white">
              <option value="">None</option>
              {cameras.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.camera_code} ({c.classroom ?? c.name})
                </option>
              ))}
            </select>
          </div>
          <div className="flex items-end justify-between gap-2">
            <label className="inline-flex items-center gap-2 text-white/80">
              <input
                type="checkbox"
                checked={supportsIr}
                onChange={(e) => setSupportsIr(e.target.checked)}
              />
              IR Night-Vision
            </label>
            <button
              type="submit"
              className="rounded-lg bg-emerald-500 px-4 py-1.5 font-semibold text-black hover:bg-emerald-400">
              Save Camera
            </button>
          </div>
        </form>
      )}

      {/* Camera Inventory & Fault Controls */}
      <div className="overflow-x-auto rounded-xl border border-white/10 bg-[#12141c]">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-white/10 bg-white/[0.02] text-white/55">
            <tr>
              <th className="p-2.5">Camera</th>
              <th className="p-2.5">Location & Source</th>
              <th className="p-2.5">Connectivity</th>
              <th className="p-2.5">Image Quality</th>
              <th className="p-2.5">Recovery & Fault Testing</th>
            </tr>
          </thead>
          <tbody>
            {cameras.length === 0 ?
              <tr>
                <td colSpan={5} className="p-6 text-center text-white/45">
                  No CCTV cameras registered yet. Click &ldquo;Add CCTV / Webcam&rdquo; to configure.
                </td>
              </tr>
            : cameras.map((cam) => (
                <tr key={cam.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="p-2.5">
                    <div className="font-semibold text-white">{cam.name}</div>
                    <div className="text-[11px] text-white/50">
                      {cam.camera_code} {cam.supports_ir ? "• IR Enabled" : ""}
                    </div>
                  </td>
                  <td className="p-2.5 text-[11px] text-white/75">
                    <div>
                      {cam.department ?? "—"} • {cam.classroom ?? "—"}
                    </div>
                    <div className="text-white/45">
                      {cam.source_type.toUpperCase()} ({cam.source_uri ?? "auto"})
                      {cam.backup_camera_code ? ` • Backup: ${cam.backup_camera_code}` : ""}
                    </div>
                  </td>
                  <td className="p-2.5">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-medium uppercase ${
                        CAM_STATUS_BADGE[cam.status] ?? "bg-white/10 text-white"
                      }`}>
                      {cam.status.replaceAll("_", " ")}
                    </span>
                    <div className="mt-0.5 text-[10px] text-white/50">
                      Reconnects: {cam.reconnect_attempts} • FPS: {cam.fps}
                    </div>
                  </td>
                  <td className="p-2.5">
                    <div className="inline-flex items-center gap-1.5">
                      <span
                        className={`size-2 rounded-full ${
                          QUALITY_DOT[cam.quality_status] ?? "bg-zinc-400"
                        }`}
                      />
                      <span className="capitalize text-white">{cam.quality_status}</span>
                      <span className="text-white/50">
                        ({Math.round(cam.quality_score * 100)}%)
                      </span>
                    </div>
                  </td>
                  <td className="p-2.5">
                    <div className="flex flex-wrap items-center gap-1 text-[11px]">
                      <button
                        type="button"
                        onClick={() =>
                          setActiveCctvCameraId(activeCctvCameraId === cam.id ? null : cam.id)
                        }
                        className={`rounded border px-2 py-1 ${
                          activeCctvCameraId === cam.id ?
                            "border-cyan-400 bg-cyan-500/25 text-cyan-100"
                          : "border-white/15 bg-white/5 text-white/75"
                        }`}>
                        {activeCctvCameraId === cam.id ? "Bound to Live" : "Bind Live"}
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleProbe(cam.id)}
                        className="rounded border border-white/15 bg-white/5 px-2 py-1 text-white/80 hover:bg-white/10">
                        Probe
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleReconnect(cam.id)}
                        className="inline-flex items-center gap-1 rounded border border-emerald-500/35 bg-emerald-500/15 px-2 py-1 text-emerald-200 hover:bg-emerald-500/25">
                        <Wrench className="size-3" />
                        Reconnect
                      </button>
                      <button
                        type="button"
                        onClick={() =>
                          setVlaserCamera({
                            id: cam.id,
                            name: cam.name,
                            classroom: cam.classroom,
                          })
                        }
                        className="inline-flex items-center gap-1 rounded border border-cyan-500/40 bg-cyan-500/15 px-2 py-1 text-cyan-200 hover:bg-cyan-500/25">
                        <Zap className="size-3" />
                        V-LASER Grid
                      </button>
                      <select
                        value={cam.simulated_fault ?? ""}
                        onChange={(e) => void handleSimulate(cam.id, e.target.value || null)}
                        className="rounded border border-amber-500/30 bg-[#1a1d28] px-1.5 py-1 text-[11px] text-amber-200">
                        <option value="">Simulate Fault…</option>
                        <option value="offline">Simulate Offline</option>
                        <option value="frozen">Simulate Frozen Feed</option>
                        <option value="darkness">Simulate Darkness</option>
                        <option value="blur">Simulate Blur / Opacity</option>
                        <option value="recording_failed">Simulate Rec Failure</option>
                      </select>
                      <button
                        type="button"
                        onClick={() => void handleDeactivate(cam.id)}
                        aria-label="Deactivate camera"
                        className="rounded p-1 text-white/45 hover:bg-rose-500/20 hover:text-rose-300">
                        <Trash2 className="size-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>

      {/* Camera Incident & Recovery Log */}
      <div className="rounded-xl border border-white/10 bg-[#12141c] p-3">
        <h4 className="mb-2 text-xs font-semibold text-white/85">
          Camera Error & Recovery History
        </h4>
        <div className="max-h-56 overflow-y-auto">
          <table className="w-full text-left text-[11px]">
            <thead className="border-b border-white/10 text-white/50">
              <tr>
                <th className="p-2">Camera</th>
                <th className="p-2">Category</th>
                <th className="p-2">Detected</th>
                <th className="p-2">Recovery Status</th>
                <th className="p-2">Corrective Action</th>
              </tr>
            </thead>
            <tbody>
              {logs.length === 0 ?
                <tr>
                  <td colSpan={5} className="p-4 text-center text-white/40">
                    No camera incidents logged.
                  </td>
                </tr>
              : logs.map((l) => (
                  <tr key={l.id} className="border-b border-white/5">
                    <td className="p-2 font-medium text-white">
                      {l.camera_code ?? l.camera_name}
                    </td>
                    <td className="p-2 text-amber-200">{l.error_category}</td>
                    <td className="p-2 text-white/60">
                      {l.detected_at ? new Date(l.detected_at).toLocaleString() : "—"}
                    </td>
                    <td className="p-2 uppercase text-cyan-200">{l.recovery_status}</td>
                    <td className="p-2 text-white/65">{l.corrective_action ?? l.message}</td>
                  </tr>
                ))
              }
            </tbody>
          </table>
        </div>
      </div>

      {/* V-LASER Real-Time Spatial Activity & Boundary Alerts Feed */}
      <div className="rounded-xl border border-white/10 bg-[#12141c] p-3">
        <div className="mb-2 flex items-center justify-between">
          <h4 className="text-xs font-semibold text-white/85 flex items-center gap-1.5">
            <Zap className="size-3.5 text-cyan-400" />
            V-LASER Live Spatial Event Feed & Boundary Alerts
          </h4>
          <span className="flex items-center gap-1 text-[10px] text-cyan-400">
            <span className="size-1.5 rounded-full bg-cyan-400 animate-ping" />
            Real-time Feed
          </span>
        </div>
        <div className="max-h-60 overflow-y-auto">
          <table className="w-full text-left text-[11px]">
            <thead className="border-b border-white/10 text-white/50">
              <tr>
                <th className="p-2">Event</th>
                <th className="p-2">Camera</th>
                <th className="p-2">Track ID</th>
                <th className="p-2">Details</th>
                <th className="p-2">Confidence</th>
                <th className="p-2">Time</th>
              </tr>
            </thead>
            <tbody>
              {spatialEvents.length === 0 ?
                <tr>
                  <td colSpan={6} className="p-4 text-center text-white/40 italic">
                    No spatial events detected yet across active CCTV feeds.
                  </td>
                </tr>
              : spatialEvents.map((ev) => (
                  <tr key={ev.id} className="border-b border-white/5">
                    <td className="p-2">
                      <span
                        className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-bold uppercase ${
                          ev.event_type === "entry" ?
                            "bg-emerald-500/20 text-emerald-400 border border-emerald-500/30"
                          : ev.event_type === "exit" ?
                            "bg-orange-500/20 text-orange-400 border border-orange-500/30"
                          : ev.event_type === "restricted_violation" ?
                            "bg-rose-500/20 text-rose-400 border border-rose-500/30"
                          : "bg-cyan-500/20 text-cyan-400 border border-cyan-500/30"
                        }`}>
                        {ev.event_type.replaceAll("_", " ").toUpperCase()}
                      </span>
                    </td>
                    <td className="p-2 font-mono text-white/80">{ev.camera_id}</td>
                    <td className="p-2 font-semibold text-white">Track #{ev.track_id}</td>
                    <td className="p-2 text-white/70">
                      {ev.line_name ?
                        `Line: ${ev.line_name}`
                      : ev.from_zone_name && ev.to_zone_name ?
                        `${ev.from_zone_name} → ${ev.to_zone_name}`
                      : ev.to_zone_name ?
                        `Zone: ${ev.to_zone_name}`
                      : "Boundary Crossing"}
                    </td>
                    <td className="p-2 text-cyan-300 font-mono">
                      {Math.round(ev.confidence * 100)}%
                    </td>
                    <td className="p-2 text-white/50">
                      {ev.timestamp ? new Date(ev.timestamp * 1000).toLocaleTimeString() : "—"}
                    </td>
                  </tr>
                ))
              }
            </tbody>
          </table>
        </div>
      </div>

      {/* V-LASER Virtual Grid & Zone Designer Modal */}
      {vlaserCamera && (
        <VLaserEditorModal
          cameraId={vlaserCamera.id}
          cameraName={vlaserCamera.name}
          classroom={vlaserCamera.classroom}
          isOpen={Boolean(vlaserCamera)}
          onClose={() => setVlaserCamera(null)}
          onSaved={() => void loadAll()}
        />
      )}
    </div>
  )
}

