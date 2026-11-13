import { useCallback, useEffect, useState } from "react"
import {
  AlertOctagon,
  Check,
  RefreshCw,
  Search,
  UserPlus,
  XCircle,
} from "lucide-react"
import { cctvService, type UnknownStudentRecord } from "@/services/cctvService"
import { useAttendanceStore } from "@/components/main/stores"

export function UnknownStudentsPanel() {
  const { attendanceGroups, currentGroup } = useAttendanceStore()
  const [detections, setDetections] = useState<UnknownStudentRecord[]>([])
  const [statusFilter, setStatusFilter] = useState<string>("pending")
  const [loading, setLoading] = useState(false)
  const [feedback, setFeedback] = useState<string | null>(null)

  // Search existing modal state
  const [activeDet, setActiveDet] = useState<UnknownStudentRecord | null>(null)
  const [mode, setMode] = useState<"search" | "register" | null>(null)
  const [searchTerm, setSearchTerm] = useState("")
  const [searchResults, setSearchResults] = useState<
    {
      member_id: string
      person_id: string
      name: string
      registration_number: string | null
      department: string | null
      semester: string | null
      section: string | null
    }[]
  >([])

  // Register Student form state
  const [regName, setRegName] = useState("")
  const [regGroupId, setRegGroupId] = useState(
    () => (currentGroup?.id && currentGroup.id !== "all" ? currentGroup.id : attendanceGroups[0]?.id ?? ""),
  )
  const [regNo, setRegNo] = useState("")
  const [regDept, setRegDept] = useState("CSE")
  const [regSem, setRegSem] = useState("5")
  const [regSec, setRegSec] = useState("A")

  const loadDetections = useCallback(async () => {
    setLoading(true)
    try {
      const items = await cctvService.listUnknownDetections(statusFilter || undefined)
      setDetections(items)
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Failed to load unknown detections")
    } finally {
      setLoading(false)
    }
  }, [statusFilter])

  useEffect(() => {
    void loadDetections()
  }, [loadDetections])

  const handleSearch = async (query: string) => {
    setSearchTerm(query)
    try {
      const res = await cctvService.searchExistingStudents(query)
      setSearchResults(res)
    } catch {
      setSearchResults([])
    }
  }

  const handleAction = async (
    detId: string,
    action: "verify_identity" | "mark_unverified" | "dismiss",
    memberId?: string,
  ) => {
    try {
      await cctvService.actOnUnknownDetection(detId, {
        action,
        resolved_by: "Admin",
        member_id: memberId,
      })
      setMode(null)
      setActiveDet(null)
      setFeedback(`Detection updated (${action.replaceAll("_", " ")}).`)
      await loadDetections()
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Action failed")
    }
  }

  const handleRegisterSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!activeDet || !regName.trim() || !regGroupId) return
    try {
      await cctvService.actOnUnknownDetection(activeDet.id, {
        action: "register_student",
        resolved_by: "Admin",
        name: regName.trim(),
        group_id: regGroupId,
        registration_number: regNo.trim() || undefined,
        department: regDept.trim(),
        semester: regSem.trim(),
        section: regSec.trim(),
        enroll_captured_face: true,
      })
      setMode(null)
      setActiveDet(null)
      setRegName("")
      setRegNo("")
      setFeedback("Registered student with encrypted facial embedding and resolved pending record.")
      await loadDetections()
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Registration failed")
    }
  }

  const handleReconcile = async () => {
    try {
      const res = await cctvService.reconcileUnknowns()
      setFeedback(`Retroactive check matched ${res.matched_count} pending unknown record(s).`)
      await loadDetections()
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Reconciliation failed")
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-amber-500/30 bg-amber-950/25 p-3">
        <div className="flex items-center gap-2.5 text-xs text-amber-100">
          <AlertOctagon className="size-4 text-amber-400" />
          <span className="font-semibold">
            UNREGISTERED STUDENT DETECTED – Identity verification required before attendance
            assignment.
          </span>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#151821] px-2.5 py-1.5 text-xs text-white">
            <option value="pending">Pending Verification</option>
            <option value="verified">Verified</option>
            <option value="unverified">Unverified</option>
            <option value="dismissed">Dismissed</option>
            <option value="">All</option>
          </select>
          <button
            type="button"
            onClick={() => void handleReconcile()}
            className="inline-flex items-center gap-1.5 rounded-lg border border-cyan-500/35 bg-cyan-500/15 px-3 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-cyan-500/25">
            <RefreshCw className="size-3.5" />
            Reconcile New Profiles
          </button>
          <button
            type="button"
            onClick={() => void loadDetections()}
            className="rounded-lg border border-white/15 bg-white/5 px-2.5 py-1.5 text-xs text-white/80 hover:bg-white/10">
            <RefreshCw className={`size-3.5 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {feedback && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-950/40 px-3 py-2 text-xs text-cyan-100">
          {feedback}
        </div>
      )}

      {detections.length === 0 ?
        <div className="rounded-xl border border-white/10 bg-[#12141c] p-8 text-center text-xs text-white/50">
          No unknown student detections matching filter &ldquo;{statusFilter || "all"}&rdquo;.
        </div>
      : <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
          {detections.map((det) => (
            <div
              key={det.id}
              className="flex flex-col gap-3 rounded-xl border border-white/10 bg-[#131620] p-3">
              <div className="flex gap-3">
                <div className="size-20 shrink-0 overflow-hidden rounded-lg border border-white/15 bg-black/50">
                  {det.snapshot_data_url ?
                    <img
                      src={det.snapshot_data_url}
                      alt={det.tracking_id}
                      className="size-full object-cover"
                    />
                  : <div className="flex size-full items-center justify-center text-[10px] text-white/40">
                      Encrypted
                    </div>
                  }
                </div>
                <div className="min-w-0 flex-1 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="truncate font-semibold text-white">{det.tracking_id}</span>
                    <span className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] uppercase text-white/80">
                      {det.status}
                    </span>
                  </div>
                  <div className="mt-1 text-[11px] text-white/60">
                    Classroom: {det.classroom ?? "Live Feed"} • Camera:{" "}
                    {det.camera_id ?? "Webcam"}
                  </div>
                  <div className="text-[11px] text-white/50">
                    Detected: {det.detected_at ? new Date(det.detected_at).toLocaleString() : "—"}
                  </div>
                  {det.notes && <div className="mt-1 text-[11px] text-cyan-200">{det.notes}</div>}
                </div>
              </div>

              {/* 5 Mandatory Admin Actions */}
              <div className="flex flex-wrap gap-1.5 border-t border-white/10 pt-2.5 text-[11px]">
                <button
                  type="button"
                  onClick={() => {
                    setActiveDet(det)
                    setMode("search")
                    void handleSearch("")
                  }}
                  className="inline-flex items-center gap-1 rounded border border-emerald-500/35 bg-emerald-500/15 px-2 py-1 font-medium text-emerald-200 hover:bg-emerald-500/25">
                  <Check className="size-3" />
                  1. Verify Identity / 2. Search Existing
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setActiveDet(det)
                    setMode("register")
                  }}
                  className="inline-flex items-center gap-1 rounded border border-cyan-500/35 bg-cyan-500/15 px-2 py-1 font-medium text-cyan-200 hover:bg-cyan-500/25">
                  <UserPlus className="size-3" />
                  3. Register Student
                </button>
                <button
                  type="button"
                  onClick={() => void handleAction(det.id, "mark_unverified")}
                  className="rounded border border-amber-500/30 bg-amber-500/10 px-2 py-1 text-amber-200 hover:bg-amber-500/20">
                  4. Mark Unverified
                </button>
                <button
                  type="button"
                  onClick={() => void handleAction(det.id, "dismiss")}
                  className="inline-flex items-center gap-1 rounded border border-white/15 bg-white/5 px-2 py-1 text-white/75 hover:bg-rose-500/20 hover:text-rose-200">
                  <XCircle className="size-3" />
                  5. Dismiss
                </button>
              </div>
            </div>
          ))}
        </div>
      }

      {/* Modal: Search Existing & Verify Identity */}
      {activeDet && mode === "search" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <div className="w-full max-w-lg rounded-xl border border-white/15 bg-[#151822] p-4">
            <h4 className="mb-2 text-sm font-semibold text-white">
              Verify Identity — Search Existing Students
            </h4>
            <div className="relative mb-3">
              <Search className="absolute top-2 left-2.5 size-3.5 text-white/40" />
              <input
                value={searchTerm}
                onChange={(e) => void handleSearch(e.target.value)}
                placeholder="Search by student name, person ID, or registration number..."
                className="w-full rounded-lg border border-white/15 bg-[#10131a] py-1.5 pr-3 pl-8 text-xs text-white"
              />
            </div>
            <div className="max-h-60 overflow-y-auto rounded-lg border border-white/10 bg-[#10131a]">
              {searchResults.map((st) => (
                <div
                  key={st.member_id}
                  className="flex items-center justify-between border-b border-white/5 px-3 py-2 text-xs">
                  <div>
                    <div className="font-medium text-white">{st.name}</div>
                    <div className="text-[11px] text-white/50">
                      {st.registration_number ?? st.person_id}{" "}
                      {st.department ? `• ${st.department} ${st.semester}-${st.section}` : ""}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => void handleAction(activeDet.id, "verify_identity", st.member_id)}
                    className="rounded bg-emerald-500/20 px-2.5 py-1 text-[11px] font-semibold text-emerald-200 hover:bg-emerald-500/30">
                    Link & Verify
                  </button>
                </div>
              ))}
            </div>
            <div className="mt-3 flex justify-end">
              <button
                type="button"
                onClick={() => {
                  setMode(null)
                  setActiveDet(null)
                }}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/75">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Register New Student */}
      {activeDet && mode === "register" && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <form
            onSubmit={handleRegisterSubmit}
            className="w-full max-w-md rounded-xl border border-white/15 bg-[#151822] p-4">
            <h4 className="mb-3 text-sm font-semibold text-white">
              Register Unknown Student & Enroll Face
            </h4>
            <div className="grid grid-cols-2 gap-2.5 text-xs">
              <div className="col-span-2">
                <label className="mb-1 block text-[11px] text-white/60">Full Name</label>
                <input
                  required
                  value={regName}
                  onChange={(e) => setRegName(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-white"
                />
              </div>
              <div className="col-span-2">
                <label className="mb-1 block text-[11px] text-white/60">Target Group</label>
                <select
                  required
                  value={regGroupId}
                  onChange={(e) => setRegGroupId(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-white">
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
                <label className="mb-1 block text-[11px] text-white/60">Registration No</label>
                <input
                  value={regNo}
                  onChange={(e) => setRegNo(e.target.value)}
                  placeholder="REG-2026-01"
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-white/60">Department</label>
                <input
                  value={regDept}
                  onChange={(e) => setRegDept(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-white/60">Semester</label>
                <input
                  value={regSem}
                  onChange={(e) => setRegSem(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-white/60">Section</label>
                <input
                  value={regSec}
                  onChange={(e) => setRegSec(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#10131a] px-3 py-1.5 text-white"
                />
              </div>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => {
                  setMode(null)
                  setActiveDet(null)
                }}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-xs text-white/75">
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-cyan-500 px-3 py-1.5 text-xs font-semibold text-black hover:bg-cyan-400">
                Register & Verify
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

