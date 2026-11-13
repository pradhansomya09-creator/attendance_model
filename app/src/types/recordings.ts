export interface ClassSessionRecordingItem {
  id: string
  schedule_id?: string | null
  course_code: string
  course_name: string
  section: string
  session_date: string // YYYY-MM-DD
  start_time: string // HH:MM
  end_time: string // HH:MM
  classroom?: string | null
  camera_id?: string | null
  file_size_bytes: number
  duration_seconds: number
  format: string
  status: "ready" | "processing" | "deleted"
  retention_days: number
  created_at?: string | null
}

export interface StudentSessionRosterItem {
  member_id: string
  person_id: string
  name: string
  status: "present" | "late" | "absent"
  cctv_detected: boolean
  video_timestamp_seconds: number
  video_timestamp_formatted: string // e.g. "00:15"
  last_modified_by: string
  last_modified_at?: string | null
  latest_reason: string
}

export interface RecordingRosterResponse {
  recording: {
    id: string
    course_code: string
    course_name: string
    section: string
    session_date: string
    start_time: string
    end_time: string
    classroom?: string | null
    duration_seconds: number
    file_size_bytes: number
  }
  roster: StudentSessionRosterItem[]
  total_students: number
  present_count: number
  late_count: number
  absent_count: number
}

export interface AttendanceCorrectionPayload {
  member_id: string
  new_status: "present" | "late" | "absent"
  reason: string
  corrected_by: string
}

export interface AttendanceCorrectionResponse {
  success: boolean
  audit_id: string
  student_name: string
  previous_status: string
  new_status: string
  corrected_by: string
  corrected_at: string
}

export interface AuditTrailResponse {
  recording_id: string
  course: string
  session_date: string
  attendance_corrections: {
    id: string
    student_name: string
    previous_status: string
    new_status: string
    reason: string
    corrected_by: string
    timestamp: string
  }[]
  video_access_logs: {
    id: string
    accessed_by: string
    access_type: string
    ip_address?: string | null
    timestamp: string
  }[]
}

export interface RetentionPolicyStats {
  default_retention_days: number
  active_recordings_count: number
  storage_used_bytes: number
  storage_used_mb: number
  storage_directory: string
}

