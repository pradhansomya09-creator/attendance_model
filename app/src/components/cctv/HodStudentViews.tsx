import { useCallback, useEffect, useState } from "react"
import { BarChart3, Lock, RefreshCw, Shield, User } from "lucide-react"
import {
  cctvService,
  type HodReportResponse,
  type StudentProfileRecord,
  type StudentSelfAttendanceResponse,
} from "@/services/cctvService"

export function HodReportsPanel() {
  const [department, setDepartment] = useState("")
  const [section, setSection] = useState("")
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [report, setReport] = useState<HodReportResponse | null>(null)
  const [audits, setAudits] = useState<
    { id: string; timestamp: string | null; action: string; target_type: string | null; details: string | null }[]
  >([])

  const loadReport = useCallback(async () => {
    try {
      const [r, a] = await Promise.all([
        cctvService.getHodReport({
          department: department.trim() || undefined,
          section: section.trim() || undefined,
          date,
        }),
        cctvService.listAuditLogs(30),
      ])
      setReport(r)
      setAudits(a)
    } catch {
      // ignore initial error when empty
    }
  }, [date, department, section])

  useEffect(() => {
    void loadReport()
  }, [loadReport])

  return (
    <div className="flex flex-col gap-4 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-white/10 bg-white/[0.03] p-3">
        <div className="flex flex-wrap items-center gap-2">
          <input
            value={department}
            onChange={(e) => setDepartment(e.target.value)}
            placeholder="Department (e.g. CSE)"
            className="rounded-lg border border-white/15 bg-[#151821] px-2.5 py-1.5 text-white"
          />
          <input
            value={section}
            onChange={(e) => setSection(e.target.value)}
            placeholder="Section (e.g. A)"
            className="rounded-lg border border-white/15 bg-[#151821] px-2.5 py-1.5 text-white"
          />
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            className="rounded-lg border border-white/15 bg-[#151821] px-2.5 py-1.5 text-white"
          />
        </div>
        <button
          type="button"
          onClick={() => void loadReport()}
          className="inline-flex items-center gap-1.5 rounded-lg border border-white/15 bg-white/5 px-3 py-1.5 text-white/85 hover:bg-white/10">
          <RefreshCw className="size-3.5" />
          Refresh Report
        </button>
      </div>

      {report && (
        <>
          <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-6">
            {[
              { label: "Classes", val: report.totals.total_classes, color: "text-white" },
              {
                label: "CCTV Verified",
                val: report.totals.cctv_verified,
                color: "text-emerald-300",
              },
              {
                label: "Manual Verified",
                val: report.totals.manually_verified,
                color: "text-cyan-300",
              },
              {
                label: "Pending",
                val: report.totals.pending_verification,
                color: "text-amber-300",
              },
              {
                label: "Late / Partial",
                val: report.totals.late_or_partial,
                color: "text-orange-300",
              },
              {
                label: "Mismatches",
                val: report.totals.section_mismatch,
                color: "text-rose-300",
              },
            ].map((k) => (
              <div
                key={k.label}
                className="rounded-xl border border-white/10 bg-[#131620] p-2.5 text-center">
                <div className={`text-lg font-bold ${k.color}`}>{k.val}</div>
                <div className="text-[11px] text-white/55">{k.label}</div>
              </div>
            ))}
          </div>

          <div className="overflow-x-auto rounded-xl border border-white/10 bg-[#12141c]">
            <table className="w-full text-left text-[11px]">
              <thead className="border-b border-white/10 bg-white/[0.02] text-white/55">
                <tr>
                  <th className="p-2.5">Section & Subject</th>
                  <th className="p-2.5">Faculty</th>
                  <th className="p-2.5">Enrolled</th>
                  <th className="p-2.5">CCTV</th>
                  <th className="p-2.5">Manual</th>
                  <th className="p-2.5">Pending</th>
                  <th className="p-2.5">Attendance %</th>
                </tr>
              </thead>
              <tbody>
                {report.sections.length === 0 ?
                  <tr>
                    <td colSpan={7} className="p-6 text-center text-white/45">
                      No departmental class schedules matched this filter.
                    </td>
                  </tr>
                : report.sections.map((s) => (
                    <tr key={s.schedule_id} className="border-b border-white/5">
                      <td className="p-2.5">
                        <div className="font-semibold text-white">
                          {s.department} {s.semester}-{s.section} • {s.subject_code}
                        </div>
                        <div className="text-white/50">{s.subject_name}</div>
                      </td>
                      <td className="p-2.5 text-white/75">{s.faculty_name}</td>
                      <td className="p-2.5">{s.enrolled}</td>
                      <td className="p-2.5 text-emerald-300">{s.cctv_verified}</td>
                      <td className="p-2.5 text-cyan-300">{s.manually_verified}</td>
                      <td className="p-2.5 text-amber-300">{s.pending_verification}</td>
                      <td className="p-2.5 font-semibold text-white">{s.attendance_percentage}%</td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        </>
      )}

      {/* Governance & Immutable Audit Trail */}
      <div className="rounded-xl border border-white/10 bg-[#12141c] p-3">
        <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-white">
          <Shield className="size-3.5 text-cyan-400" />
          Data Privacy & Governance Audit Trail (Recent Actions)
        </div>
        <div className="max-h-44 overflow-y-auto">
          {audits.map((a) => (
            <div
              key={a.id}
              className="flex items-center justify-between gap-2 border-b border-white/5 py-1.5 text-[11px]">
              <div>
                <span className="font-semibold text-cyan-200">{a.action}</span>{" "}
                <span className="text-white/55">{a.details ?? ""}</span>
              </div>
              <span className="shrink-0 text-white/40">
                {a.timestamp ? new Date(a.timestamp).toLocaleString() : ""}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

export function StudentPortalPanel() {
  const [students, setStudents] = useState<StudentProfileRecord[]>([])
  const [selectedId, setSelectedId] = useState("")
  const [data, setData] = useState<StudentSelfAttendanceResponse | null>(null)

  useEffect(() => {
    void cctvService.listStudentProfiles().then((list) => {
      setStudents(list)
      if (list[0]) setSelectedId(list[0].member_id)
    })
  }, [])

  useEffect(() => {
    if (!selectedId) return
    void cctvService.getStudentSelfAttendance(selectedId).then(setData).catch(() => setData(null))
  }, [selectedId])

  return (
    <div className="flex flex-col gap-4 text-xs">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-cyan-500/25 bg-cyan-950/20 p-3">
        <div className="flex items-center gap-2 text-cyan-100">
          <Lock className="size-4 text-cyan-400" />
          <span>
            Privacy-Isolated Student Self-View: Displays strictly your own verified attendance and
            privacy consent status.
          </span>
        </div>
        <select
          value={selectedId}
          onChange={(e) => setSelectedId(e.target.value)}
          className="rounded-lg border border-white/15 bg-[#151821] px-3 py-1.5 text-white">
          {students.map((st) => (
            <option key={st.member_id} value={st.member_id}>
              {st.name} ({st.registration_number ?? st.person_id})
            </option>
          ))}
        </select>
      </div>

      {data && (
        <>
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-white/10 bg-[#131620] p-4">
            <div className="flex items-center gap-3">
              <div className="flex size-10 items-center justify-center rounded-full bg-cyan-500/20 text-cyan-300">
                <User className="size-5" />
              </div>
              <div>
                <div className="text-sm font-semibold text-white">{data.student.name}</div>
                <div className="text-[11px] text-white/60">
                  {data.student.registration_number ?? "Unregistered Reg"} •{" "}
                  {data.student.department ?
                    `${data.student.department} Sem ${data.student.semester}-${data.student.section}`
                  : "No Section Assigned"}
                </div>
                <div className="mt-0.5 text-[11px] text-white/55">
                  Biometric Mode:{" "}
                  {data.student.non_biometric_opt_out ?
                    "Non-Biometric Opt-Out Active"
                  : data.student.biometric_consent_granted ?
                    "Consent Active (Encrypted Facial Template)"
                  : "Consent Pending"}
                </div>
              </div>
            </div>

            <div className="flex gap-4 text-center">
              <div>
                <div className="text-lg font-bold text-emerald-300">{data.summary.present}</div>
                <div className="text-[11px] text-white/50">Present</div>
              </div>
              <div>
                <div className="text-lg font-bold text-amber-300">
                  {data.summary.pending_verification}
                </div>
                <div className="text-[11px] text-white/50">Pending</div>
              </div>
              <div>
                <div className="text-lg font-bold text-white">
                  {data.summary.attendance_percentage}%
                </div>
                <div className="text-[11px] text-white/50">Rate</div>
              </div>
            </div>
          </div>

          <div className="overflow-x-auto rounded-xl border border-white/10 bg-[#12141c]">
            <table className="w-full text-left text-[11px]">
              <thead className="border-b border-white/10 bg-white/[0.02] text-white/55">
                <tr>
                  <th className="p-2.5">Date</th>
                  <th className="p-2.5">Subject / Room</th>
                  <th className="p-2.5">Verification Source</th>
                  <th className="p-2.5">Status & Duration</th>
                  <th className="p-2.5">Notes</th>
                </tr>
              </thead>
              <tbody>
                {data.records.length === 0 ?
                  <tr>
                    <td colSpan={5} className="p-6 text-center text-white/45">
                      No verified attendance evaluations recorded for this student yet.
                    </td>
                  </tr>
                : data.records.map((r) => (
                    <tr key={r.id} className="border-b border-white/5">
                      <td className="p-2.5 text-white/80">{r.date}</td>
                      <td className="p-2.5">
                        <div className="font-medium text-white">{r.subject}</div>
                        <div className="text-white/50">{r.classroom ?? "General"}</div>
                      </td>
                      <td className="p-2.5 font-medium text-cyan-200">{r.verification_source}</td>
                      <td className="p-2.5 capitalize text-white/80">
                        {r.attendance_rule_status.replaceAll("_", " ")} (
                        {r.estimated_duration_minutes}m)
                      </td>
                      <td className="p-2.5 text-white/60">{r.reason ?? "—"}</td>
                    </tr>
                  ))
                }
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  )
}

