import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { CctvStatusHud } from "../CctvStatusHud"
import { SmartCctvHub } from "../SmartCctvHub"
import { useDetectionStore } from "@/components/main/stores/detectionStore"
import { useAttendanceStore } from "@/components/main/stores/attendanceStore"
import { cctvService } from "@/services/cctvService"

describe("Smart CCTV UI Components", () => {
  beforeEach(() => {
    useDetectionStore.getState().resetDetectionState()
    useAttendanceStore.setState({
      attendanceGroups: [{ id: "grp-1", name: "CSE 5-A" } as never],
      currentGroup: { id: "grp-1", name: "CSE 5-A" } as never,
    })
  })

  it("renders Green/Yellow/Red quality indicators, IR badge, headcount, and alerts in CctvStatusHud", () => {
    const onOpenHub = vi.fn()
    useDetectionStore.getState().setImageQuality({
      status: "red",
      score: 0.21,
      brightness: 12,
      contrast: 5,
      sharpness: 8,
      haze_score: 0.8,
      overexposed_ratio: 0,
      underexposed_ratio: 0.9,
      obstruction_score: 0.85,
      is_ir_mode: true,
      recognition_reliable: false,
      issues: ["severe_darkness"],
      enhancements_applied: ["infrared_clahe"],
    })
    useDetectionStore.getState().setHeadcountSummary({
      enrolled: 40,
      unique_detected: 36,
      successfully_identified: 32,
      unknown_individuals: 2,
      pending_verification: 2,
      confirmed_present: 32,
      section_mismatches: 1,
      duplicate_alerts: 0,
    })
    useDetectionStore.getState().pushCctvAlert({
      type: "cctv_alert",
      alert_type: "unknown_student",
      severity: "warning",
      message: "UNREGISTERED STUDENT DETECTED – Identity verification required.",
      timestamp: 123456,
    })

    render(<CctvStatusHud isStreaming={true} onOpenHub={onOpenHub} />)

    expect(screen.getByText(/Poor Visibility/i)).toBeInTheDocument()
    expect(screen.getByText("IR")).toBeInTheDocument()
    expect(screen.getByText("Enhanced")).toBeInTheDocument()
    expect(screen.getByText(/2 Unknown/i)).toBeInTheDocument()
    expect(screen.getByText(/1 Mismatch/i)).toBeInTheDocument()
    expect(
      screen.getByText(/UNREGISTERED STUDENT DETECTED – Identity verification required\./i),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByText("Review"))
    expect(onOpenHub).toHaveBeenCalledWith("unknowns")
  })

  it("switches roles and loads Faculty, Unknowns, HOD & Student portal views in SmartCctvHub", async () => {
    vi.spyOn(cctvService, "listSchedules").mockResolvedValue([
      {
        id: "sched-1",
        group_id: "grp-1",
        department: "CSE",
        semester: "5",
        section: "A",
        subject_code: "CS501",
        subject_name: "AI",
        faculty_name: "Dr. Rao",
        classroom: "LH-101",
        building: null,
        camera_id: "cam-1",
        day_of_week: "*",
        start_time: "09:00",
        end_time: "10:00",
        late_after_minutes: 10,
        early_exit_minutes: 10,
        min_presence_percent: 60,
        is_active: true,
      },
    ])
    vi.spyOn(cctvService, "getFacultyMonitor").mockResolvedValue({
      date: "2026-11-12",
      schedule: null,
      camera: {
        id: "cam-1",
        name: "LH-101 Main",
        camera_code: "CAM-101",
        source_type: "simulated",
        source_uri: null,
        supports_ir: true,
        department: "CSE",
        building: "A",
        classroom: "LH-101",
        assigned_group_id: "grp-1",
        backup_camera_id: "cam-2",
        backup_camera_code: "CAM-101-BK",
        status: "offline",
        recording_status: "failed",
        quality_status: "red",
        quality_score: 0.2,
        fps: 0,
        reconnect_attempts: 2,
        last_frame_at: null,
        last_connected_at: null,
        disconnected_at: null,
        is_active: true,
        simulated_fault: "offline",
        stream_running: false,
      },
      backup_camera: null,
      headcount: {
        enrolled: 30,
        unique_detected: 0,
        successfully_identified: 0,
        unknown_individuals: 0,
        pending_verification: 30,
        confirmed_present: 0,
        section_mismatches: 0,
        duplicate_alerts: 0,
      },
      evaluations: [],
      open_mismatches: [],
      roster: [
        {
          member_id: "m1",
          person_id: "p1",
          name: "Ananya",
          registration_number: "REG-01",
          section: "CSE 5-A",
          non_biometric_opt_out: false,
          current_classification: "pending_verification",
          current_rule_status: "pending_verification",
        },
      ],
    })
    vi.spyOn(cctvService, "listUnknownDetections").mockResolvedValue([])
    vi.spyOn(cctvService, "getHodReport").mockResolvedValue({
      date: "2026-11-12",
      totals: {
        total_classes: 1,
        cctv_verified: 25,
        manually_verified: 3,
        pending_verification: 2,
        absent: 0,
        section_mismatch: 0,
        late_or_partial: 1,
      },
      sections: [],
    })
    vi.spyOn(cctvService, "listAuditLogs").mockResolvedValue([])
    vi.spyOn(cctvService, "listStudentProfiles").mockResolvedValue([
      {
        member_id: "m1",
        person_id: "p1",
        name: "Ananya",
        group_id: "grp-1",
        role: "student",
        registration_number: "REG-01",
        department: "CSE",
        semester: "5",
        section: "A",
        biometric_consent_granted: true,
        non_biometric_opt_out: false,
        consent_timestamp: null,
      },
    ])
    vi.spyOn(cctvService, "getStudentSelfAttendance").mockResolvedValue({
      student: {
        member_id: "m1",
        name: "Ananya",
        registration_number: "REG-01",
        department: "CSE",
        semester: "5",
        section: "A",
        biometric_consent_granted: true,
        non_biometric_opt_out: false,
      },
      summary: {
        total_classes_recorded: 1,
        present: 1,
        pending_verification: 0,
        absent: 0,
        attendance_percentage: 100,
      },
      records: [],
    })

    render(<SmartCctvHub isOpen={true} initialTab="faculty" onClose={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText(/LH-101 Main/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/Open Manual Verification/i)).toBeInTheDocument()

    // Switch role to HOD
    fireEvent.click(screen.getByRole("button", { name: "HOD" }))
    await waitFor(() => {
      expect(screen.getByText(/CCTV Verified/i)).toBeInTheDocument()
    })

    // Switch role to Student
    fireEvent.click(screen.getByRole("button", { name: "student" }))
    await waitFor(() => {
      expect(screen.getByText(/Privacy-Isolated Student Self-View/i)).toBeInTheDocument()
    })
  })
})

