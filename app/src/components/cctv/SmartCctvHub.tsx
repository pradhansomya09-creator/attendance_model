import { useState } from "react"
import {
  BarChart3,
  CalendarClock,
  Camera,
  ClipboardCheck,
  Film,
  GraduationCap,
  ShieldAlert,
  X,
} from "lucide-react"
import type { SmartCctvTab } from "./CctvStatusHud"
import { FacultyDashboard } from "./FacultyDashboard"
import { FacultyPlaybackReview } from "./FacultyPlaybackReview"
import { UnknownStudentsPanel } from "./UnknownStudentsPanel"
import { AdminCctvDashboard } from "./AdminCctvDashboard"
import { TimetableSectionsPanel } from "./TimetableSectionsPanel"
import { HodReportsPanel, StudentPortalPanel } from "./HodStudentViews"

type UserRole = "faculty" | "admin" | "hod" | "student"

interface SmartCctvHubProps {
  isOpen: boolean
  initialTab?: SmartCctvTab
  onClose: () => void
}

const ROLE_DEFAULT_TAB: Record<UserRole, SmartCctvTab> = {
  faculty: "faculty",
  admin: "admin",
  hod: "hod",
  student: "student",
}

const TABS: {
  id: SmartCctvTab
  label: string
  roles: UserRole[]
  icon: typeof Camera
}[] = [
  { id: "faculty", label: "Faculty Monitor", roles: ["faculty", "admin"], icon: ClipboardCheck },
  { id: "playback", label: "Class Playback & Review", roles: ["faculty", "admin"], icon: Film },
  { id: "unknowns", label: "Unknown Students", roles: ["faculty", "admin"], icon: ShieldAlert },
  { id: "admin", label: "CCTV & V-LASER Grid", roles: ["admin"], icon: Camera },
  { id: "timetable", label: "Timetable & Profiles", roles: ["admin", "faculty"], icon: CalendarClock },
  { id: "hod", label: "HOD Reports & Audit", roles: ["hod", "admin"], icon: BarChart3 },
  { id: "student", label: "Student Self-View", roles: ["student", "admin"], icon: GraduationCap },
]

export function SmartCctvHub({ isOpen, initialTab = "faculty", onClose }: SmartCctvHubProps) {
  const [role, setRole] = useState<UserRole>("admin")
  const [activeTab, setActiveTab] = useState<SmartCctvTab>(initialTab)

  if (!isOpen) return null

  const visibleTabs = TABS.filter((t) => t.roles.includes(role))
  const currentTab = visibleTabs.some((t) => t.id === activeTab) ? activeTab : visibleTabs[0].id

  return (
    <div
      role="dialog"
      aria-label="APNA CAMPUS Smart CCTV Attendance Hub"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 p-3 backdrop-blur-sm sm:p-5">
      <div className="flex h-[92vh] w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-white/15 bg-[#0c0e14] text-white shadow-2xl">
        {/* Header */}
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-[#11141d] px-4 py-3">
          <div>
            <h2 className="text-sm font-bold tracking-wide text-white">
              APNA CAMPUS ERP • Smart CCTV Attendance & Recovery Hub
            </h2>
            <p className="text-[11px] text-white/55">
              Centralized 10-Factor Biometric Verification, Camera Fault Recovery & Governance
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* Role Switcher */}
            <div className="flex items-center rounded-lg border border-white/10 bg-black/40 p-0.5 text-[11px]">
              {(["faculty", "admin", "hod", "student"] as UserRole[]).map((r) => (
                <button
                  key={r}
                  type="button"
                  onClick={() => {
                    setRole(r)
                    setActiveTab(ROLE_DEFAULT_TAB[r])
                  }}
                  className={`rounded-md px-2.5 py-1 font-medium capitalize transition ${
                    role === r ?
                      "bg-cyan-500 text-black font-semibold"
                    : "text-white/65 hover:text-white"
                  }`}>
                  {r === "hod" ? "HOD" : r}
                </button>
              ))}
            </div>

            <button
              type="button"
              onClick={onClose}
              aria-label="Close Smart CCTV Hub"
              className="rounded-lg border border-white/15 bg-white/5 p-1.5 text-white/70 hover:bg-white/15 hover:text-white">
              <X className="size-4" />
            </button>
          </div>
        </div>

        {/* Sub-navigation */}
        <div className="flex flex-wrap gap-1.5 border-b border-white/10 bg-[#0f1219] px-4 py-2">
          {visibleTabs.map((tab) => {
            const Icon = tab.icon
            const isSelected = currentTab === tab.id
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                  isSelected ?
                    "border border-cyan-500/40 bg-cyan-500/15 text-cyan-200"
                  : "border border-transparent text-white/65 hover:bg-white/5 hover:text-white"
                }`}>
                <Icon className="size-3.5" />
                {tab.label}
              </button>
            )
          })}
        </div>

        {/* Active Panel Content */}
        <div className="min-h-0 flex-1 overflow-y-auto p-4">
          {currentTab === "faculty" && <FacultyDashboard />}
          {currentTab === "playback" && <FacultyPlaybackReview />}
          {currentTab === "unknowns" && <UnknownStudentsPanel />}
          {currentTab === "admin" && <AdminCctvDashboard />}
          {currentTab === "timetable" && <TimetableSectionsPanel />}
          {currentTab === "hod" && <HodReportsPanel />}
          {currentTab === "student" && <StudentPortalPanel />}
        </div>
      </div>
    </div>
  )
}

