import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { FacultyPlaybackReview } from "../FacultyPlaybackReview"
import { recordingService } from "@/services/recordingService"
import type {
  ClassSessionRecordingItem,
  RecordingRosterResponse,
  RetentionPolicyStats,
  AuditTrailResponse,
} from "@/types/recordings"

const MOCK_RECORDINGS: ClassSessionRecordingItem[] = [
  {
    id: "rec-123",
    schedule_id: "sched-1",
    course_code: "CS501",
    course_name: "Artificial Intelligence",
    section: "A",
    session_date: "2026-11-13",
    start_time: "09:00",
    end_time: "10:00",
    classroom: "LH-101",
    camera_id: "cam-101",
    file_size_bytes: 104857600,
    duration_seconds: 1800,
    format: "mp4",
    status: "ready",
    retention_days: 30,
    created_at: "2026-11-13T09:00:00Z",
  },
]

const MOCK_ROSTER_RESP: RecordingRosterResponse = {
  recording: {
    id: "rec-123",
    course_code: "CS501",
    course_name: "Artificial Intelligence",
    section: "A",
    session_date: "2026-11-13",
    start_time: "09:00",
    end_time: "10:00",
    classroom: "LH-101",
    duration_seconds: 1800,
    file_size_bytes: 104857600,
  },
  total_students: 2,
  present_count: 1,
  late_count: 0,
  absent_count: 1,
  roster: [
    {
      member_id: "mem-1",
      person_id: "p1",
      name: "Somya Verma",
      status: "absent",
      cctv_detected: true,
      video_timestamp_seconds: 45,
      video_timestamp_formatted: "00:45",
      last_modified_by: "System CCTV",
      last_modified_at: "2026-11-13T09:05:00Z",
      latest_reason: "Initial absent",
    },
    {
      member_id: "mem-2",
      person_id: "p2",
      name: "Ashish Kumar",
      status: "present",
      cctv_detected: true,
      video_timestamp_seconds: 12,
      video_timestamp_formatted: "00:12",
      last_modified_by: "System CCTV",
      last_modified_at: "2026-11-13T09:02:00Z",
      latest_reason: "Entrance verified",
    },
  ],
}

const MOCK_AUDIT_RESP: AuditTrailResponse = {
  recording_id: "rec-123",
  course: "CS501",
  session_date: "2026-11-13",
  attendance_corrections: [],
  video_access_logs: [
    {
      id: "acc-1",
      accessed_by: "Dr. Faculty",
      access_type: "stream_video",
      ip_address: "100.64.0.5",
      timestamp: "2026-11-13T10:00:00Z",
    },
  ],
}

const MOCK_RETENTION_STATS: RetentionPolicyStats = {
  default_retention_days: 30,
  active_recordings_count: 12,
  storage_used_bytes: 524288000,
  storage_used_mb: 500,
  storage_directory: "storage/recordings",
}

describe("FacultyPlaybackReview Component", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(recordingService, "listRecordings").mockResolvedValue(MOCK_RECORDINGS)
    vi.spyOn(recordingService, "getRoster").mockResolvedValue(MOCK_ROSTER_RESP)
    vi.spyOn(recordingService, "submitAttendanceCorrection").mockResolvedValue({
      success: true,
      audit_id: "audit-999",
      student_name: "Somya Verma",
      previous_status: "absent",
      new_status: "present",
      corrected_by: "Dr. Faculty",
      corrected_at: "2026-11-13T10:30:00Z",
    })
    vi.spyOn(recordingService, "getAuditTrail").mockResolvedValue(MOCK_AUDIT_RESP)
    vi.spyOn(recordingService, "getRetentionSettings").mockResolvedValue(MOCK_RETENTION_STATS)
  })

  it("loads recordings and displays video player, roster bookmarks, and playback controls", async () => {
    render(<FacultyPlaybackReview />)

    await waitFor(() => {
      expect(screen.getByText("Class Video Playback & Attendance Review")).toBeInTheDocument()
      expect(screen.getByText("Somya Verma")).toBeInTheDocument()
      expect(screen.getByText("Ashish Kumar")).toBeInTheDocument()
    })

    // Verify timeline detection bookmark buttons exist
    expect(screen.getByText(/Seen at 00:45/i)).toBeInTheDocument()
    expect(screen.getByText(/Seen at 00:12/i)).toBeInTheDocument()
  })

  it("submits attendance correction with mandatory justification and updates audit trail", async () => {
    render(<FacultyPlaybackReview />)

    await waitFor(() => {
      expect(screen.getByText("Somya Verma")).toBeInTheDocument()
    })

    // Click "Present" button for Somya
    const presentButtons = screen.getAllByRole("button", { name: /^Present$/i })
    fireEvent.click(presentButtons[0])

    // Justification dialog should open
    await waitFor(() => {
      expect(screen.getByText(/Correct Student Attendance/i)).toBeInTheDocument()
    })

    // Fill justification
    const textarea = screen.getByPlaceholderText(/e\.g\. Verified student seated in Row 3/i)
    fireEvent.change(textarea, { target: { value: "Clearly identified sitting in second row" } })

    // Confirm correction
    const confirmBtn = screen.getByRole("button", { name: /Confirm & Log Correction/i })
    fireEvent.click(confirmBtn)

    await waitFor(() => {
      expect(recordingService.submitAttendanceCorrection).toHaveBeenCalledWith(
        "rec-123",
        expect.objectContaining({
          member_id: "mem-1",
          new_status: "present",
          reason: "Clearly identified sitting in second row",
        })
      )
    })
  })

  it("opens retention governance modal", async () => {
    render(<FacultyPlaybackReview />)

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Retention & Storage/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole("button", { name: /Retention & Storage/i }))

    await waitFor(() => {
      expect(screen.getByText(/Recording Retention & Deletion Governance/i)).toBeInTheDocument()
      expect(screen.getByText(/Configurable Retention Period/i)).toBeInTheDocument()
    })
  })
})
