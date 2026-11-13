import { useCallback, useEffect, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  ClipboardCheck,
  RefreshCw,
  ShieldAlert,
  UserCheck,
  Wifi,
  WifiOff,
} from "lucide-react"
import {
  cctvService,
  type AcademicScheduleRecord,
  type FacultyMonitorResponse,
  type SmartEvaluationRecord,
} from "@/services/cctvService"
import { useAttendanceStore } from "@/components/main/stores"

const CLASSIFICATION_BADGES: Record<string, string> = {
  cctv_verified_present: "bg-emerald-500/20 text-emerald-300 border-emerald-500/30",
  manually_verified_present: "bg-cyan-500/20 text-cyan-300 border-cyan-500/30",
  pending_verification: "bg-amber-500/20 text-amber-300 border-amber-500/30",
  unknown_student: "bg-orange-500/20 text-orange-300 border-orange-500/30",
  section_mismatch: "bg-rose-500/20 text-rose-300 border-rose-500/30",
  absent: "bg-zinc-700/40 text-zinc-300 border-zinc-600/40",
}

const CLASSIFICATION_LABELS: Record<string, string> = {
  cctv_verified_present: "CCTV Verified",
  manually_verified_present: "Manually Verified",
  pending_verification: "Pending Verification",
  unknown_student: "Unknown Student",
  section_mismatch: "Section Mismatch",
  absent: "Absent",
}

export function FacultyDashboard() {
  const { currentGroup, attendanceGroups } = useAttendanceStore()
  const [schedules, setSchedules] = useState<AcademicScheduleRecord[]>([])
  const [selectedScheduleId, setSelectedScheduleId] = useState<string>("")
  const [selectedDate, setSelectedDate] = useState<string>(() =>
    new Date().toISOString().slice(0, 10),
  )
  const [monitor, setMonitor] = useState<FacultyMonitorResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [statusMessage, setStatusMessage] = useState<string | null>(null)

  // Manual verify dialog state
  const [editingEval, setEditingEval] = useState<SmartEvaluationRecord | null>(null)
  const [verifyClass, setVerifyClass] = useState("manually_verified_present")
  const [verifyRule, setVerifyRule] = useState("full_attendance")
  const [verifyReason, setVerifyReason] = useState("")

  // Manual offline fallback drawer state
  const [showFallback, setShowFallback] = useState(false)
  const [fallbackReason, setFallbackReason] = useState(
    "CCTV footage unavailable / poor lighting verification",
  )
  const [fallbackBy, setFallbackBy] = useState("Faculty")
  const [fallbackMap, setFallbackMap] = useState<Record<string, "present" | "absent" | "late_entry">>(
    {},
  )

  const loadData = useCallback(async () => {
    setLoading(true)
    try {
      const schedList = await cctvService.listSchedules()
      setSchedules(schedList)
      const activeSchedId = selectedScheduleId || schedList[0]?.id || ""
      if (!selectedScheduleId && activeSchedId) {
        setSelectedScheduleId(activeSchedId)
      }
      const data = await cctvService.getFacultyMonitor({
        schedule_id: activeSchedId || undefined,
        group_id: !activeSchedId && currentGroup?.id && currentGroup.id !== "all" ? currentGroup.id : undefined,
        date: selectedDate,
      })
      setMonitor(data)
      const nextMap: Record<string, "present" | "absent" | "late_entry"> = {}
      for (const r of data.roster) {
        nextMap[r.member_id] =
          r.current_classification === "absent" ? "absent" : "present"
      }
      setFallbackMap(nextMap)
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to load faculty monitor")
    } finally {
      setLoading(false)
    }
  }, [currentGroup?.id, selectedDate, selectedScheduleId])

  useEffect(() => {
    void loadData()
  }, [loadData])

  const handleSubmitVerify = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editingEval || verifyReason.trim().length < 3) return
    try {
      await cctvService.verifyEvaluation(editingEval.id, {
        classification: verifyClass,
        attendance_rule_status: verifyRule,
        verified_by: fallbackBy || "Faculty",
        reason: verifyReason.trim(),
      })
      setEditingEval(null)
      setVerifyReason("")
      setStatusMessage("Attendance evaluation updated and recorded in audit trail.")
      await loadData()
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to update evaluation")
    }
  }

  const handleSubmitFallback = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!monitor || fallbackReason.trim().length < 3) return
    const entries = monitor.roster.map((r) => ({
      member_id: r.member_id,
      status: fallbackMap[r.member_id] ?? "present",
    }))
    try {
      const res = await cctvService.submitManualFallback({
        schedule_id: monitor.schedule?.id,
        group_id:
          monitor.schedule?.group_id ??
          (currentGroup?.id && currentGroup.id !== "all" ? currentGroup.id : attendanceGroups[0]?.id),
        date: selectedDate,
        verified_by: fallbackBy || "Faculty",
        reason: fallbackReason.trim(),
        entries,
      })
      setShowFallback(false)
      setStatusMessage(`Submitted ${res.processed} records labeled "${res.label}".`)
      await loadData()
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to submit manual attendance")
    }
  }

  const handleFinalizeClass = async () => {
    if (!monitor?.schedule) return
    try {
      const res = await cctvService.finalizeSchedule(
        monitor.schedule.id,
        fallbackBy || "Faculty",
        selectedDate,
      )
      setStatusMessage(
        res.camera_blocked ?
          `Camera offline/poor: ${res.kept_pending} records safely held as Pending Verification (0 auto-absents).`
        : `Class finalized: ${res.marked_absent} absent, ${res.kept_pending} pending verification.`,
      )
      await loadData()
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Finalization failed")
    }
  }

  const handleResolveMismatch = async (
    alertId: string,
    action: "approve_exception" | "dismiss",
  ) => {
    try {
      await cctvService.resolveSectionMismatch(alertId, {
        action,
        resolved_by: fallbackBy || "Faculty",
        notes:
          action === "approve_exception" ?
            "Faculty approved inter-section attendance exception"
          : "Dismissed by faculty",
      })
      setStatusMessage(
        action === "approve_exception" ?
          "Approved cross-section exception."
        : "Section mismatch dismissed.",
      )
      await loadData()
    } catch (err) {
      setStatusMessage(err instanceof Error ? err.message : "Failed to resolve mismatch")
    }
  }

  const cam = monitor?.camera
  const cameraNeedsManual =
    !cam ||
    cam.status === "offline" ||
    cam.status === "recording_failed" ||
    cam.quality_status === "red"

  return (
    <div className="flex flex-col gap-4">
      {/* Filter Header */}
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <div className="flex flex-wrap items-center gap-3">
          <div>
            <label className="mb-1 block text-[11px] font-medium text-white/50">
              Scheduled Class
            </label>
            <select
              value={selectedScheduleId}
              onChange={(e) => setSelectedScheduleId(e.target.value)}
              className="rounded-lg border border-white/15 bg-[#151821] px-3 py-1.5 text-xs text-white focus:border-cyan-500 focus:outline-none">
              <option value="">Active Group Session ({currentGroup?.name ?? "Default"})</option>
              {schedules.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.department} {s.semester}-{s.section} • {s.subject_code} ({s.classroom})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-white/50">Date</label>
            <input
              type="date"
              value={selectedDate}
              onChange={(e) => setSelectedDate(e.target.value)}
              className="rounded-lg border border-white/15 bg-[#151821] px-3 py-1.5 text-xs text-white focus:border-cyan-500 focus:outline-none"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => void loadData()}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-xs font-medium text-white/85 hover:bg-white/10">
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setShowFallback((v) => !v)}
            className="inline-flex items-center gap-1.5 rounded-lg border border-amber-500/40 bg-amber-500/15 px-3 py-1.5 text-xs font-semibold text-amber-200 hover:bg-amber-500/25">
            <ClipboardCheck className="size-3.5" />
            Manual Attendance Fallback
          </button>
          {monitor?.schedule && (
            <button
              type="button"
              onClick={() => void handleFinalizeClass()}
              className="inline-flex items-center gap-1.5 rounded-lg border border-emerald-500/40 bg-emerald-500/15 px-3 py-1.5 text-xs font-semibold text-emerald-200 hover:bg-emerald-500/25">
              <CheckCircle2 className="size-3.5" />
              Finalize Class
            </button>
          )}
        </div>
      </div>

      {statusMessage && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-950/40 px-3 py-2 text-xs text-cyan-100">
          {statusMessage}
        </div>
      )}

      {/* Camera Health & Quality Banner */}
      <div
        className={`flex flex-wrap items-center justify-between gap-3 rounded-xl border p-3 ${
          cameraNeedsManual ?
            "border-rose-500/40 bg-rose-950/30"
          : "border-emerald-500/25 bg-emerald-950/20"
        }`}>
        <div className="flex items-center gap-3">
          {cam?.status === "online" ?
            <Wifi className="size-5 text-emerald-400" />
          : <WifiOff className="size-5 text-rose-400" />}
          <div>
            <div className="text-xs font-semibold text-white">
              {cam ? `${cam.name} (${cam.camera_code})` : "No CCTV Camera Assigned"}
            </div>
            <div className="text-[11px] text-white/65">
              {cam ?
                `Connectivity: ${cam.status.toUpperCase()} • Recording: ${cam.recording_status} • Visibility: ${cam.quality_status.toUpperCase()} (${Math.round(cam.quality_score * 100)}%)`
              : "Using manual verification or local webcam scanner."}
            </div>
            {monitor?.backup_camera && (
              <div className="mt-1 text-[11px] font-medium text-cyan-300">
                Backup Failover Ready: {monitor.backup_camera.name} (
                {monitor.backup_camera.camera_code})
              </div>
            )}
          </div>
        </div>

        {cameraNeedsManual && (
          <button
            type="button"
            onClick={() => setShowFallback(true)}
            className="rounded-lg border border-rose-400/50 bg-rose-500/20 px-3 py-1.5 text-xs font-semibold text-rose-100 hover:bg-rose-500/30">
            Open Manual Verification (Camera Fail-Safe Active)
          </button>
        )}
      </div>

      {/* Headcount Reconciliation Matrix */}
      {monitor && (
        <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-4 lg:grid-cols-7">
          {[
            { label: "Enrolled", val: monitor.headcount.enrolled, color: "text-white" },
            {
              label: "Unique Detected",
              val: monitor.headcount.unique_detected,
              color: "text-cyan-300",
            },
            {
              label: "Identified",
              val: monitor.headcount.successfully_identified,
              color: "text-emerald-300",
            },
            {
              label: "Unknown Faces",
              val: monitor.headcount.unknown_individuals,
              color: "text-orange-300",
            },
            {
              label: "Pending Review",
              val: monitor.headcount.pending_verification,
              color: "text-amber-300",
            },
            {
              label: "Section Mismatch",
              val: monitor.headcount.section_mismatches,
              color: "text-rose-300",
            },
            {
              label: "Duplicate Flags",
              val: monitor.headcount.duplicate_alerts,
              color: "text-fuchsia-300",
            },
          ].map((stat) => (
            <div
              key={stat.label}
              className="rounded-xl border border-white/10 bg-[#141720] p-2.5 text-center">
              <div className={`text-lg font-bold tabular-nums ${stat.color}`}>{stat.val}</div>
              <div className="text-[11px] text-white/55">{stat.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Alternative Manual Fallback Drawer */}
      {showFallback && monitor && (
        <form
          onSubmit={handleSubmitFallback}
          className="flex flex-col gap-3 rounded-xl border border-amber-500/35 bg-amber-950/20 p-4">
          <div className="flex items-center justify-between">
            <h4 className="text-sm font-semibold text-amber-200">
              Alternative Manual Attendance Interface (Labeled "Manually Verified")
            </h4>
            <button
              type="button"
              onClick={() => setShowFallback(false)}
              className="text-xs text-white/60 hover:text-white">
              Close
            </button>
          </div>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-[11px] text-white/60">Faculty Name</label>
              <input
                value={fallbackBy}
                onChange={(e) => setFallbackBy(e.target.value)}
                required
                className="w-full rounded-lg border border-white/15 bg-[#12151d] px-3 py-1.5 text-xs text-white"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-white/60">
                Reason for Manual Attendance (Mandatory Audit Field)
              </label>
              <input
                value={fallbackReason}
                onChange={(e) => setFallbackReason(e.target.value)}
                required
                minLength={3}
                className="w-full rounded-lg border border-white/15 bg-[#12151d] px-3 py-1.5 text-xs text-white"
              />
            </div>
          </div>

          <div className="max-h-56 overflow-y-auto rounded-lg border border-white/10 bg-[#11131a]">
            {monitor.roster.length === 0 ?
              <p className="p-4 text-center text-xs text-white/50">
                No enrolled students found in this schedule or group.
              </p>
            : <table className="w-full text-left text-xs">
                <thead className="border-b border-white/10 text-white/50">
                  <tr>
                    <th className="p-2">Student</th>
                    <th className="p-2">Reg No / Section</th>
                    <th className="p-2">Opt-Out</th>
                    <th className="p-2">Manual Status</th>
                  </tr>
                </thead>
                <tbody>
                  {monitor.roster.map((st) => (
                    <tr key={st.member_id} className="border-b border-white/5">
                      <td className="p-2 font-medium text-white">{st.name}</td>
                      <td className="p-2 text-white/60">
                        {st.registration_number ?? "—"} {st.section ? `(${st.section})` : ""}
                      </td>
                      <td className="p-2 text-white/60">
                        {st.non_biometric_opt_out ? "Non-Biometric" : "Biometric"}
                      </td>
                      <td className="p-2">
                        <select
                          value={fallbackMap[st.member_id] ?? "present"}
                          onChange={(e) =>
                            setFallbackMap((prev) => ({
                              ...prev,
                              [st.member_id]: e.target.value as "present" | "absent" | "late_entry",
                            }))
                          }
                          className="rounded border border-white/15 bg-[#181c26] px-2 py-1 text-xs text-white">
                          <option value="present">Present (Full)</option>
                          <option value="late_entry">Present (Late Entry)</option>
                          <option value="absent">Absent</option>
                        </select>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            }
          </div>

          <div className="flex justify-end">
            <button
              type="submit"
              className="rounded-lg bg-amber-500 px-4 py-1.5 text-xs font-semibold text-black hover:bg-amber-400">
              Submit Manual Verification
            </button>
          </div>
        </form>
      )}

      {/* Open Cross-Section Mismatches */}
      {monitor && monitor.open_mismatches.length > 0 && (
        <div className="rounded-xl border border-rose-500/30 bg-rose-950/20 p-3">
          <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-rose-200">
            <ShieldAlert className="size-4 text-rose-400" />
            Unassigned Section Detections ({monitor.open_mismatches.length})
          </div>
          <div className="flex flex-col gap-2">
            {monitor.open_mismatches.map((mm) => (
              <div
                key={mm.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-black/30 px-3 py-2 text-xs">
                <div>
                  <span className="font-semibold text-white">{mm.student_name}</span>{" "}
                  <span className="text-white/55">({mm.registration_number ?? "No Reg"})</span> —
                  Registered in <strong className="text-amber-300">{mm.actual_section}</strong>,
                  detected in <strong className="text-cyan-300">{mm.scheduled_section}</strong>
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => void handleResolveMismatch(mm.id, "approve_exception")}
                    className="rounded bg-emerald-500/20 px-2.5 py-1 text-[11px] font-medium text-emerald-200 hover:bg-emerald-500/30">
                    Approve Combined/Substitute Exception
                  </button>
                  <button
                    type="button"
                    onClick={() => void handleResolveMismatch(mm.id, "dismiss")}
                    className="rounded bg-white/10 px-2.5 py-1 text-[11px] text-white/80 hover:bg-white/20">
                    Dismiss
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Centralized Verification Table */}
      <div className="overflow-x-auto rounded-xl border border-white/10 bg-[#12141c]">
        <table className="w-full text-left text-xs">
          <thead className="border-b border-white/10 bg-white/[0.02] text-white/55">
            <tr>
              <th className="p-2.5">Student / Tracking</th>
              <th className="p-2.5">Classification</th>
              <th className="p-2.5">Rule Status & Duration</th>
              <th className="p-2.5">10-Factor Telemetry</th>
              <th className="p-2.5">Reason / Audit</th>
              <th className="p-2.5 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {!monitor || monitor.evaluations.length === 0 ?
              <tr>
                <td colSpan={6} className="p-6 text-center text-white/45">
                  No smart evaluation records recorded yet for this class/date. Start live scan or
                  use Manual Fallback above.
                </td>
              </tr>
            : monitor.evaluations.map((ev) => (
                <tr key={ev.id} className="border-b border-white/5 hover:bg-white/[0.02]">
                  <td className="p-2.5">
                    <div className="font-semibold text-white">
                      {ev.student_name ?? ev.tracking_id ?? "Unidentified"}
                    </div>
                    <div className="text-[11px] text-white/50">
                      {ev.registration_number ?? ev.student_section ?? "No Academic Profile"}
                    </div>
                  </td>
                  <td className="p-2.5">
                    <span
                      className={`inline-block rounded-full border px-2 py-0.5 text-[11px] font-medium ${
                        CLASSIFICATION_BADGES[ev.classification] ?? "bg-white/10 text-white"
                      }`}>
                      {CLASSIFICATION_LABELS[ev.classification] ?? ev.classification}
                    </span>
                    {ev.duplicate_flagged && (
                      <span className="ml-1 inline-flex items-center gap-0.5 text-[10px] text-fuchsia-300">
                        <AlertTriangle className="size-3" /> Dup
                      </span>
                    )}
                  </td>
                  <td className="p-2.5 text-white/80">
                    <div className="capitalize">
                      {ev.attendance_rule_status.replaceAll("_", " ")}
                    </div>
                    <div className="text-[11px] text-white/50">
                      {ev.estimated_duration_minutes.toFixed(1)} mins ({ev.observations_count} obs)
                    </div>
                  </td>
                  <td className="p-2.5 text-[11px] text-white/70">
                    <div>
                      Conf: {Math.round(ev.recognition_confidence * 100)}% • Qual:{" "}
                      {Math.round(ev.image_quality_score * 100)}%
                    </div>
                    <div>
                      Vis: {Math.round(ev.face_visibility_score * 100)}% • Pose:{" "}
                      {ev.head_pose_ok ? "OK" : "Turned/Occluded"}
                    </div>
                  </td>
                  <td className="max-w-xs p-2.5 text-[11px] text-white/65">
                    <div className="line-clamp-2">{ev.reason ?? "—"}</div>
                  </td>
                  <td className="p-2.5 text-right">
                    <button
                      type="button"
                      onClick={() => {
                        setEditingEval(ev)
                        setVerifyClass("manually_verified_present")
                        setVerifyRule("full_attendance")
                        setVerifyReason("")
                      }}
                      className="inline-flex items-center gap-1 rounded border border-cyan-500/35 bg-cyan-500/10 px-2.5 py-1 text-[11px] font-medium text-cyan-200 hover:bg-cyan-500/20">
                      <UserCheck className="size-3" />
                      Verify
                    </button>
                  </td>
                </tr>
              ))
            }
          </tbody>
        </table>
      </div>

      {/* Manual Verify / Override Modal */}
      {editingEval && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <form
            onSubmit={handleSubmitVerify}
            className="w-full max-w-md rounded-xl border border-white/15 bg-[#151822] p-4 shadow-2xl">
            <h4 className="mb-1 text-sm font-semibold text-white">
              Manual Attendance Verification
            </h4>
            <p className="mb-3 text-xs text-white/60">
              {editingEval.student_name ?? editingEval.tracking_id} — changes are permanently audited.
            </p>
            <div className="flex flex-col gap-3">
              <div>
                <label className="mb-1 block text-[11px] text-white/60">Classification</label>
                <select
                  value={verifyClass}
                  onChange={(e) => setVerifyClass(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-xs text-white">
                  <option value="manually_verified_present">Manually Verified Present</option>
                  <option value="absent">Absent</option>
                  <option value="pending_verification">Pending Verification</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-white/60">Rule Status</label>
                <select
                  value={verifyRule}
                  onChange={(e) => setVerifyRule(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-xs text-white">
                  <option value="full_attendance">Full Attendance</option>
                  <option value="late_entry">Late Entry</option>
                  <option value="early_departure">Early Departure</option>
                  <option value="partial_attendance">Partial Attendance</option>
                  <option value="absent">Absent</option>
                </select>
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-white/60">
                  Reason (Required, min 3 chars)
                </label>
                <textarea
                  rows={2}
                  required
                  minLength={3}
                  value={verifyReason}
                  onChange={(e) => setVerifyReason(e.target.value)}
                  placeholder="e.g., Confirmed student physically present during roll check"
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-xs text-white"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditingEval(null)}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/75">
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-black hover:bg-cyan-400">
                Save Verification
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

