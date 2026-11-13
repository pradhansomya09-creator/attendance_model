import { useCallback, useEffect, useState } from "react"
import { CalendarClock, Plus, ShieldCheck, Trash2, Users } from "lucide-react"
import {
  cctvService,
  type AcademicScheduleRecord,
  type CctvCameraRecord,
  type CrossSectionExceptionRecord,
  type StudentProfileRecord,
} from "@/services/cctvService"
import { useAttendanceStore } from "@/components/main/stores"

export function TimetableSectionsPanel() {
  const { attendanceGroups } = useAttendanceStore()
  const [schedules, setSchedules] = useState<AcademicScheduleRecord[]>([])
  const [cameras, setCameras] = useState<CctvCameraRecord[]>([])
  const [profiles, setProfiles] = useState<StudentProfileRecord[]>([])
  const [exceptions, setExceptions] = useState<CrossSectionExceptionRecord[]>([])
  const [feedback, setFeedback] = useState<string | null>(null)

  // Schedule form
  const [dept, setDept] = useState("CSE")
  const [sem, setSem] = useState("5")
  const [section, setSection] = useState("A")
  const [subCode, setSubCode] = useState("CS501")
  const [subName, setSubName] = useState("Machine Learning")
  const [faculty, setFaculty] = useState("Dr. Sharma")
  const [classroom, setClassroom] = useState("LH-101")
  const [groupId, setGroupId] = useState(() => attendanceGroups.find((g) => g.id !== "all")?.id ?? "")
  const [cameraId, setCameraId] = useState("")
  const [startTime, setStartTime] = useState("09:00")
  const [endTime, setEndTime] = useState("10:00")

  // Profile editor state
  const [editMember, setEditMember] = useState<StudentProfileRecord | null>(null)
  const [regNo, setRegNo] = useState("")
  const [pDept, setPDept] = useState("CSE")
  const [pSem, setPSem] = useState("5")
  const [pSec, setPSec] = useState("A")
  const [consent, setConsent] = useState(true)
  const [optOut, setOptOut] = useState(false)

  // Exception form
  const [excMemberId, setExcMemberId] = useState("")
  const [excSchedId, setExcSchedId] = useState("")
  const [excType, setExcType] = useState("combined_lecture")
  const [excReason, setExcReason] = useState("Approved combined lecture attendance")

  const loadAll = useCallback(async () => {
    try {
      const [s, c, p, e] = await Promise.all([
        cctvService.listSchedules(),
        cctvService.listCameras(),
        cctvService.listStudentProfiles(),
        cctvService.listExceptions(),
      ])
      setSchedules(s)
      setCameras(c)
      setProfiles(p)
      setExceptions(e)
      if (!excMemberId && p[0]) setExcMemberId(p[0].member_id)
      if (!excSchedId && s[0]) setExcSchedId(s[0].id)
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Failed loading timetable data")
    }
  }, [excMemberId, excSchedId])

  useEffect(() => {
    void loadAll()
  }, [loadAll])

  const handleCreateSchedule = async (e: React.FormEvent) => {
    e.preventDefault()
    try {
      await cctvService.createSchedule({
        group_id: groupId || null,
        department: dept,
        semester: sem,
        section,
        subject_code: subCode,
        subject_name: subName,
        faculty_name: faculty,
        classroom,
        camera_id: cameraId || null,
        start_time: startTime,
        end_time: endTime,
      })
      setFeedback("Academic timetable schedule created.")
      await loadAll()
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Failed to create schedule")
    }
  }

  const handleSaveProfile = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!editMember) return
    try {
      await cctvService.upsertStudentProfile(editMember.member_id, {
        registration_number: regNo,
        department: pDept,
        semester: pSem,
        section: pSec,
        biometric_consent_granted: consent,
        non_biometric_opt_out: optOut,
      })
      setEditMember(null)
      setFeedback("Updated student academic section & biometric privacy preference.")
      await loadAll()
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Failed saving student profile")
    }
  }

  const handleCreateException = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!excMemberId || !excSchedId) return
    try {
      await cctvService.createException({
        member_id: excMemberId,
        target_schedule_id: excSchedId,
        exception_type: excType,
        reason: excReason,
        authorized_by: "Admin / Faculty",
      })
      setFeedback("Authorized cross-section attendance exception recorded.")
      await loadAll()
    } catch (err) {
      setFeedback(err instanceof Error ? err.message : "Failed creating exception")
    }
  }

  return (
    <div className="flex flex-col gap-5 text-xs">
      {feedback && (
        <div className="rounded-lg border border-cyan-500/30 bg-cyan-950/40 px-3 py-2 text-cyan-100">
          {feedback}
        </div>
      )}

      {/* 1. Timetable Builder */}
      <div className="rounded-xl border border-white/10 bg-[#12141c] p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
          <CalendarClock className="size-4 text-cyan-400" />
          Official Timetable & Section Schedule Binding
        </div>
        <form onSubmit={handleCreateSchedule} className="mb-4 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
          <input
            required
            value={dept}
            onChange={(e) => setDept(e.target.value)}
            placeholder="Department"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <input
            required
            value={sem}
            onChange={(e) => setSem(e.target.value)}
            placeholder="Semester"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <input
            required
            value={section}
            onChange={(e) => setSection(e.target.value)}
            placeholder="Section (e.g. A)"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <input
            required
            value={classroom}
            onChange={(e) => setClassroom(e.target.value)}
            placeholder="Classroom"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <input
            required
            value={subCode}
            onChange={(e) => setSubCode(e.target.value)}
            placeholder="Subject Code"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <input
            required
            value={subName}
            onChange={(e) => setSubName(e.target.value)}
            placeholder="Subject Name"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <input
            required
            value={faculty}
            onChange={(e) => setFaculty(e.target.value)}
            placeholder="Assigned Faculty"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <select
            value={groupId}
            onChange={(e) => setGroupId(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white">
            <option value="">Linked Group…</option>
            {attendanceGroups
              .filter((g) => g.id !== "all")
              .map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name}
                </option>
              ))}
          </select>
          <select
            value={cameraId}
            onChange={(e) => setCameraId(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white">
            <option value="">Camera (optional)</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.camera_code} • {c.classroom ?? c.name}
              </option>
            ))}
          </select>
          <input
            type="time"
            value={startTime}
            onChange={(e) => setStartTime(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <input
            type="time"
            value={endTime}
            onChange={(e) => setEndTime(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <button
            type="submit"
            className="inline-flex items-center justify-center gap-1 rounded-lg bg-cyan-500 px-3 py-1.5 font-semibold text-black hover:bg-cyan-400">
            <Plus className="size-3.5" /> Add Schedule
          </button>
        </form>

        <div className="max-h-48 overflow-y-auto rounded-lg border border-white/10">
          <table className="w-full text-left text-[11px]">
            <thead className="border-b border-white/10 bg-white/[0.02] text-white/55">
              <tr>
                <th className="p-2">Dept / Sem / Sec</th>
                <th className="p-2">Subject</th>
                <th className="p-2">Faculty & Room</th>
                <th className="p-2">Window</th>
                <th className="p-2 text-right">Remove</th>
              </tr>
            </thead>
            <tbody>
              {schedules.map((s) => (
                <tr key={s.id} className="border-b border-white/5">
                  <td className="p-2 font-semibold text-white">
                    {s.department} Sem {s.semester} - {s.section}
                  </td>
                  <td className="p-2 text-cyan-200">
                    {s.subject_code} ({s.subject_name})
                  </td>
                  <td className="p-2 text-white/70">
                    {s.faculty_name} • {s.classroom}
                  </td>
                  <td className="p-2 text-white/60">
                    {s.start_time} – {s.end_time}
                  </td>
                  <td className="p-2 text-right">
                    <button
                      type="button"
                      onClick={() => void cctvService.deleteSchedule(s.id).then(loadAll)}
                      className="rounded p-1 text-white/40 hover:bg-rose-500/20 hover:text-rose-300">
                      <Trash2 className="size-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 2. Student Academic Sections & Non-Biometric Privacy Consent */}
      <div className="rounded-xl border border-white/10 bg-[#12141c] p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
          <Users className="size-4 text-emerald-400" />
          Student Registration Numbers, Sections & Biometric Consent
        </div>
        <div className="max-h-56 overflow-y-auto rounded-lg border border-white/10">
          <table className="w-full text-left text-[11px]">
            <thead className="border-b border-white/10 bg-white/[0.02] text-white/55">
              <tr>
                <th className="p-2">Student</th>
                <th className="p-2">Reg No</th>
                <th className="p-2">Assigned Section</th>
                <th className="p-2">Privacy / Opt-Out</th>
                <th className="p-2 text-right">Configure</th>
              </tr>
            </thead>
            <tbody>
              {profiles.map((p) => (
                <tr key={p.member_id} className="border-b border-white/5">
                  <td className="p-2 font-medium text-white">{p.name}</td>
                  <td className="p-2 text-white/70">{p.registration_number ?? "Unassigned"}</td>
                  <td className="p-2 text-white/70">
                    {p.department ? `${p.department} Sem ${p.semester}-${p.section}` : "Unassigned"}
                  </td>
                  <td className="p-2">
                    {p.non_biometric_opt_out ?
                      <span className="rounded bg-amber-500/20 px-1.5 py-0.5 text-amber-200">
                        Non-Biometric Opt-Out
                      </span>
                    : <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-emerald-200">
                        Consent Granted
                      </span>
                    }
                  </td>
                  <td className="p-2 text-right">
                    <button
                      type="button"
                      onClick={() => {
                        setEditMember(p)
                        setRegNo(p.registration_number ?? `REG-${p.person_id.slice(0, 6)}`)
                        setPDept(p.department ?? "CSE")
                        setPSem(p.semester ?? "5")
                        setPSec(p.section ?? "A")
                        setConsent(p.biometric_consent_granted)
                        setOptOut(p.non_biometric_opt_out)
                      }}
                      className="rounded border border-white/15 bg-white/5 px-2 py-0.5 text-white/80 hover:bg-white/15">
                      Edit
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* 3. Cross-Section Exceptions */}
      <div className="rounded-xl border border-white/10 bg-[#12141c] p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
          <ShieldCheck className="size-4 text-amber-400" />
          Authorized Cross-Section Attendance Exceptions
        </div>
        <form onSubmit={handleCreateException} className="mb-3 grid grid-cols-1 gap-2 sm:grid-cols-5">
          <select
            value={excMemberId}
            onChange={(e) => setExcMemberId(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white">
            {profiles.map((p) => (
              <option key={p.member_id} value={p.member_id}>
                {p.name}
              </option>
            ))}
          </select>
          <select
            value={excSchedId}
            onChange={(e) => setExcSchedId(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white">
            {schedules.map((s) => (
              <option key={s.id} value={s.id}>
                {s.department}-{s.section} • {s.subject_code}
              </option>
            ))}
          </select>
          <select
            value={excType}
            onChange={(e) => setExcType(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white">
            <option value="combined_lecture">Combined Lecture</option>
            <option value="substitute_class">Substitute Class</option>
            <option value="inter_section">Inter-Section Approval</option>
          </select>
          <input
            required
            value={excReason}
            onChange={(e) => setExcReason(e.target.value)}
            placeholder="Authorization reason"
            className="rounded-lg border border-white/15 bg-[#0e1118] px-2.5 py-1.5 text-white"
          />
          <button
            type="submit"
            className="rounded-lg bg-amber-500 px-3 py-1.5 font-semibold text-black hover:bg-amber-400">
            Grant Exception
          </button>
        </form>
        {exceptions.length > 0 && (
          <div className="flex flex-col gap-1.5">
            {exceptions.map((ex) => (
              <div
                key={ex.id}
                className="flex items-center justify-between rounded-lg border border-white/10 bg-black/25 px-3 py-1.5 text-[11px]">
                <div>
                  <strong className="text-white">{ex.student_name ?? ex.person_id}</strong> (
                  {ex.from_section}) → <span className="text-cyan-300">{ex.target_section}</span> •{" "}
                  {ex.exception_type} • {ex.valid_date} ({ex.status})
                </div>
                {ex.status === "approved" && (
                  <button
                    type="button"
                    onClick={() => void cctvService.revokeException(ex.id).then(loadAll)}
                    className="text-rose-300 hover:underline">
                    Revoke
                  </button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Edit Student Profile Modal */}
      {editMember && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
          <form
            onSubmit={handleSaveProfile}
            className="w-full max-w-md rounded-xl border border-white/15 bg-[#151822] p-4">
            <h4 className="mb-3 text-sm font-semibold text-white">
              Academic & Biometric Profile: {editMember.name}
            </h4>
            <div className="grid grid-cols-2 gap-2.5">
              <div className="col-span-2">
                <label className="mb-1 block text-[11px] text-white/60">Registration Number</label>
                <input
                  required
                  value={regNo}
                  onChange={(e) => setRegNo(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-white/60">Department</label>
                <input
                  required
                  value={pDept}
                  onChange={(e) => setPDept(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-white/60">Semester</label>
                <input
                  required
                  value={pSem}
                  onChange={(e) => setPSem(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
                />
              </div>
              <div className="col-span-2">
                <label className="mb-1 block text-[11px] text-white/60">Section</label>
                <input
                  required
                  value={pSec}
                  onChange={(e) => setPSec(e.target.value)}
                  className="w-full rounded-lg border border-white/15 bg-[#0e1118] px-3 py-1.5 text-white"
                />
              </div>
              <label className="col-span-2 flex items-center gap-2 text-white/85">
                <input
                  type="checkbox"
                  checked={consent}
                  onChange={(e) => setConsent(e.target.checked)}
                />
                Biometric Facial Recognition Consent Granted
              </label>
              <label className="col-span-2 flex items-center gap-2 text-amber-200">
                <input
                  type="checkbox"
                  checked={optOut}
                  onChange={(e) => setOptOut(e.target.checked)}
                />
                Non-Biometric Opt-Out (Require Manual / Alternate Verification)
              </label>
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditMember(null)}
                className="rounded-lg border border-white/15 px-3 py-1.5 text-white/75">
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-cyan-500 px-3 py-1.5 font-semibold text-black hover:bg-cyan-400">
                Save Profile
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}

