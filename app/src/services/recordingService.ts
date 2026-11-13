import { HttpClient } from "./attendance/HttpClient"
import type {
  AttendanceCorrectionPayload,
  AttendanceCorrectionResponse,
  AuditTrailResponse,
  ClassSessionRecordingItem,
  RecordingRosterResponse,
  RetentionPolicyStats,
} from "@/types/recordings"

const API_BASE_URL = "http://127.0.0.1:7400"

export class RecordingService {
  private client = new HttpClient(API_BASE_URL)

  /** Fetch recordings matching course, section, date, and schedule filters */
  listRecordings(params?: {
    course?: string
    section?: string
    date?: string
    schedule_id?: string
  }) {
    const query: Record<string, string> = {}
    if (params?.course) query.course = params.course
    if (params?.section) query.section = params.section
    if (params?.date) query.date = params.date
    if (params?.schedule_id) query.schedule_id = params.schedule_id
    return this.client.get<ClassSessionRecordingItem[]>("/recordings", query)
  }

  /** Get metadata of a single recording */
  getRecording(recordingId: string) {
    return this.client.get<ClassSessionRecordingItem>(`/recordings/${recordingId}`)
  }

  /** Get direct video streaming URL with faculty authentication */
  getStreamUrl(recordingId: string, facultyName = "Faculty Reviewer"): string {
    return `${API_BASE_URL}/recordings/${recordingId}/stream?user=${encodeURIComponent(facultyName)}`
  }

  /** Fetch attendance roster, verification status, and video detection timeline bookmarks */
  getRoster(recordingId: string) {
    return this.client.get<RecordingRosterResponse>(`/recordings/${recordingId}/roster`)
  }

  /** Submit attendance correction with reviewer ID and audit reason */
  submitAttendanceCorrection(recordingId: string, payload: AttendanceCorrectionPayload) {
    return this.client.post<AttendanceCorrectionResponse>(
      `/recordings/${recordingId}/attendance`,
      payload,
    )
  }

  /** Fetch complete audit trail of video playback access and attendance changes */
  getAuditTrail(recordingId: string) {
    return this.client.get<AuditTrailResponse>(`/recordings/${recordingId}/audit-trail`)
  }

  /** Get configurable recording retention policies and disk storage stats */
  getRetentionSettings() {
    return this.client.get<RetentionPolicyStats>("/recordings/settings/retention")
  }

  /** Update retention period in days and trigger automated expiration pruning */
  updateRetentionPolicy(retentionDays: number) {
    return this.client.post<{ success: boolean; new_retention_days: number; pruned_recordings_count: number }>(
      "/recordings/settings/retention",
      { retention_days: retentionDays },
    )
  }

  /** Permanently delete recording file with audit log */
  deleteRecording(recordingId: string, deletedBy: string, reason: string) {
    return this.client.delete<{ success: boolean; message: string }>(
      `/recordings/${recordingId}`,
      { deleted_by: deletedBy, reason },
    )
  }
}

export const recordingService = new RecordingService()

