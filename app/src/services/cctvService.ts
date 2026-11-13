import { HttpClient } from "./attendance/HttpClient"

const API_BASE_URL = "http://127.0.0.1:7400"

export interface CctvCameraRecord {
  id: string
  name: string
  camera_code: string
  source_type: "webcam" | "rtsp" | "video_file" | "simulated" | string
  source_uri: string | null
  supports_ir: boolean
  department: string | null
  building: string | null
  classroom: string | null
  assigned_group_id: string | null
  backup_camera_id: string | null
  backup_camera_code: string | null
  status: "online" | "unstable" | "offline" | "recording_failed" | "recovering" | string
  recording_status: string
  quality_status: "green" | "yellow" | "red" | string
  quality_score: number
  fps: number
  reconnect_attempts: number
  last_frame_at: string | null
  last_connected_at: string | null
  disconnected_at: string | null
  is_active: boolean
  simulated_fault: string | null
  stream_running: boolean
}

export interface CctvCameraLogRecord {
  id: string
  camera_id: string
  camera_name: string
  camera_code: string | null
  classroom: string | null
  error_category: string
  severity: string
  message: string
  detected_at: string | null
  resolved_at: string | null
  duration_seconds: number | null
  recovery_status: string
  corrective_action: string | null
}

export interface AcademicScheduleRecord {
  id: string
  group_id: string | null
  department: string
  semester: string
  section: string
  subject_code: string
  subject_name: string
  faculty_name: string
  classroom: string
  building: string | null
  camera_id: string | null
  day_of_week: string
  start_time: string
  end_time: string
  late_after_minutes: number
  early_exit_minutes: number
  min_presence_percent: number
  is_active: boolean
}

export interface StudentProfileRecord {
  member_id: string
  person_id: string
  name: string
  group_id: string
  role: string
  registration_number: string | null
  department: string | null
  semester: string | null
  section: string | null
  biometric_consent_granted: boolean
  non_biometric_opt_out: boolean
  consent_timestamp: string | null
}

export interface UnknownStudentRecord {
  id: string
  tracking_id: string
  camera_id: string | null
  schedule_id: string | null
  group_id: string | null
  classroom: string | null
  detected_at: string | null
  snapshot_data_url: string | null
  confidence_best_guess: number
  status: string
  resolved_member_id: string | null
  resolved_by: string | null
  resolved_at: string | null
  notes: string | null
}

export interface SmartEvaluationRecord {
  id: string
  schedule_id: string | null
  group_id: string | null
  camera_id: string | null
  date: string
  member_id: string | null
  person_id: string | null
  student_name: string | null
  registration_number: string | null
  student_section: string | null
  tracking_id: string | null
  expected_section: string | null
  detected_section: string | null
  classification: string
  attendance_rule_status: string
  recognition_confidence: number
  image_quality_score: number
  face_visibility_score: number
  temporal_consistency_score: number
  head_pose_ok: boolean
  duplicate_flagged: boolean
  first_seen_at: string | null
  last_seen_at: string | null
  estimated_duration_minutes: number
  observations_count: number
  reason: string | null
  verified_by: string | null
  verified_at: string | null
}

export interface FacultyMonitorResponse {
  date: string
  schedule: AcademicScheduleRecord | null
  camera: CctvCameraRecord | null
  backup_camera: CctvCameraRecord | null
  headcount: {
    enrolled: number
    unique_detected: number
    successfully_identified: number
    unknown_individuals: number
    pending_verification: number
    confirmed_present: number
    section_mismatches: number
    duplicate_alerts: number
  }
  evaluations: SmartEvaluationRecord[]
  open_mismatches: {
    id: string
    student_name: string
    registration_number: string | null
    actual_section: string
    scheduled_section: string
    detected_at: string | null
  }[]
  roster: {
    member_id: string
    person_id: string
    name: string
    registration_number: string | null
    section: string | null
    non_biometric_opt_out: boolean
    current_classification: string
    current_rule_status: string
  }[]
}

export interface AdminOverviewResponse {
  cameras: {
    total: number
    online: number
    unstable: number
    offline: number
    recording_failed: number
    quality_green: number
    quality_yellow: number
    quality_red: number
    with_backup: number
  }
  alerts: {
    open_camera_incidents: number
    pending_unknown_students: number
    open_section_mismatches: number
  }
  model_health: {
    detector_loaded: boolean
    recognizer_loaded: boolean
    liveness_loaded: boolean
    enrolled_embeddings: number
    similarity_threshold: number | null
  }
}

export interface SectionMismatchRecord {
  id: string
  member_id: string
  person_id: string
  student_name: string
  registration_number: string | null
  actual_section: string
  scheduled_section: string
  schedule_id: string | null
  camera_id: string | null
  classroom: string | null
  detected_at: string | null
  status: string
  resolved_by: string | null
  resolved_at: string | null
  notes: string | null
}

export interface CrossSectionExceptionRecord {
  id: string
  member_id: string
  person_id: string
  student_name: string | null
  from_section: string
  target_schedule_id: string
  target_section: string
  exception_type: string
  reason: string
  authorized_by: string
  valid_date: string
  status: string
}

export interface HodReportResponse {
  date: string
  totals: {
    total_classes: number
    cctv_verified: number
    manually_verified: number
    pending_verification: number
    absent: number
    section_mismatch: number
    late_or_partial: number
  }
  sections: {
    schedule_id: string
    department: string
    semester: string
    section: string
    subject_code: string
    subject_name: string
    faculty_name: string
    classroom: string
    enrolled: number
    cctv_verified: number
    manually_verified: number
    pending_verification: number
    absent: number
    section_mismatch: number
    late_or_partial: number
    attendance_percentage: number
  }[]
}

export interface StudentSelfAttendanceResponse {
  student: {
    member_id: string
    name: string
    registration_number: string | null
    department: string | null
    semester: string | null
    section: string | null
    biometric_consent_granted: boolean
    non_biometric_opt_out: boolean
  }
  summary: {
    total_classes_recorded: number
    present: number
    pending_verification: number
    absent: number
    attendance_percentage: number
  }
  records: {
    id: string
    date: string
    subject: string
    classroom: string | null
    verification_source: string
    classification: string
    attendance_rule_status: string
    estimated_duration_minutes: number
    first_seen_at: string | null
    last_seen_at: string | null
    reason: string | null
  }[]
}

export class CctvService {
  private client = new HttpClient(API_BASE_URL)

  // Cameras & Health
  listCameras(filters?: Record<string, string>) {
    return this.client.get<CctvCameraRecord[]>("/cctv/cameras", filters)
  }

  createCamera(data: Partial<CctvCameraRecord> & { name: string; camera_code: string }) {
    return this.client.post<CctvCameraRecord>("/cctv/cameras", data)
  }

  updateCamera(cameraId: string, data: Partial<CctvCameraRecord>) {
    return this.client.put<CctvCameraRecord>(`/cctv/cameras/${cameraId}`, data)
  }

  deleteCamera(cameraId: string) {
    return this.client.delete<{ success: boolean }>(`/cctv/cameras/${cameraId}`)
  }

  probeCamera(cameraId: string) {
    return this.client.post<{ camera: CctvCameraRecord; probe: Record<string, unknown> }>(
      `/cctv/cameras/${cameraId}/probe`,
    )
  }

  reconnectCamera(cameraId: string, clearFault = true) {
    return this.client.post<{ reconnected: boolean; status: string }>(
      `/cctv/cameras/${cameraId}/reconnect`,
      { clear_fault: clearFault },
    )
  }

  simulateFault(cameraId: string, fault: string | null) {
    return this.client.post<Record<string, unknown>>(`/cctv/cameras/${cameraId}/simulate`, {
      fault,
    })
  }

  listCameraLogs(cameraId?: string) {
    return this.client.get<CctvCameraLogRecord[]>(
      "/cctv/cameras/logs",
      cameraId ? { camera_id: cameraId } : undefined,
    )
  }

  getAdminOverview() {
    return this.client.get<AdminOverviewResponse>("/cctv/admin/overview")
  }

  // Schedules & Profiles
  listSchedules(filters?: Record<string, string>) {
    return this.client.get<AcademicScheduleRecord[]>("/cctv/schedules", filters)
  }

  createSchedule(data: Partial<AcademicScheduleRecord>) {
    return this.client.post<AcademicScheduleRecord>("/cctv/schedules", data)
  }

  deleteSchedule(scheduleId: string) {
    return this.client.delete<{ success: boolean }>(`/cctv/schedules/${scheduleId}`)
  }

  listStudentProfiles(filters?: Record<string, string>) {
    return this.client.get<StudentProfileRecord[]>("/cctv/student-profiles", filters)
  }

  upsertStudentProfile(
    memberId: string,
    data: {
      registration_number: string
      department: string
      semester: string
      section: string
      biometric_consent_granted: boolean
      non_biometric_opt_out: boolean
    },
  ) {
    return this.client.put<StudentProfileRecord>(`/cctv/student-profiles/${memberId}`, data)
  }

  // Mismatches & Exceptions
  listSectionMismatches(status?: string) {
    return this.client.get<SectionMismatchRecord[]>(
      "/cctv/section-mismatches",
      status ? { status } : undefined,
    )
  }

  resolveSectionMismatch(
    alertId: string,
    data: {
      action: "approve_exception" | "confirmed_mismatch" | "dismiss"
      resolved_by: string
      notes?: string
      exception_type?: string
    },
  ) {
    return this.client.post<{ success: boolean; status: string }>(
      `/cctv/section-mismatches/${alertId}/resolve`,
      data,
    )
  }

  listExceptions() {
    return this.client.get<CrossSectionExceptionRecord[]>("/cctv/exceptions")
  }

  createException(data: {
    member_id: string
    target_schedule_id: string
    exception_type: string
    reason: string
    authorized_by: string
    valid_date?: string
  }) {
    return this.client.post<{ id: string; status: string }>("/cctv/exceptions", data)
  }

  revokeException(exceptionId: string) {
    return this.client.post<{ success: boolean }>(`/cctv/exceptions/${exceptionId}/revoke`)
  }

  // Unknown Students
  listUnknownDetections(status?: string) {
    return this.client.get<UnknownStudentRecord[]>(
      "/cctv/unknown-detections",
      status ? { status } : undefined,
    )
  }

  searchExistingStudents(query: string) {
    return this.client.get<
      {
        member_id: string
        person_id: string
        name: string
        group_id: string
        registration_number: string | null
        department: string | null
        semester: string | null
        section: string | null
      }[]
    >("/cctv/unknown-detections/search-students", { q: query })
  }

  actOnUnknownDetection(
    detectionId: string,
    data: {
      action: "verify_identity" | "register_student" | "mark_unverified" | "dismiss"
      resolved_by: string
      notes?: string
      member_id?: string
      name?: string
      group_id?: string
      registration_number?: string
      department?: string
      semester?: string
      section?: string
      enroll_captured_face?: boolean
    },
  ) {
    return this.client.post<{ success: boolean; status: string; resolved_member_id: string | null }>(
      `/cctv/unknown-detections/${detectionId}/action`,
      data,
    )
  }

  reconcileUnknowns() {
    return this.client.post<{ matched_count: number; matches: unknown[] }>(
      "/cctv/unknown-detections/reconcile",
    )
  }

  // Faculty Monitor & Manual Fallback
  getFacultyMonitor(params?: { schedule_id?: string; group_id?: string; date?: string }) {
    const cleanParams: Record<string, string> = {}
    if (params?.schedule_id) cleanParams.schedule_id = params.schedule_id
    if (params?.group_id) cleanParams.group_id = params.group_id
    if (params?.date) cleanParams.date = params.date
    return this.client.get<FacultyMonitorResponse>("/cctv/faculty/monitor", cleanParams)
  }

  verifyEvaluation(
    evaluationId: string,
    data: {
      classification: string
      attendance_rule_status?: string
      verified_by: string
      reason: string
    },
  ) {
    return this.client.post<{ success: boolean; classification: string }>(
      `/cctv/evaluations/${evaluationId}/verify`,
      data,
    )
  }

  submitManualFallback(data: {
    schedule_id?: string
    group_id?: string
    date?: string
    verified_by: string
    reason: string
    entries: { member_id: string; status: "present" | "absent" | "late_entry" }[]
  }) {
    return this.client.post<{ success: boolean; processed: number; label: string }>(
      "/cctv/manual-fallback",
      data,
    )
  }

  finalizeSchedule(scheduleId: string, verifiedBy: string, date?: string) {
    return this.client.post<{
      schedule_id: string
      camera_blocked: boolean
      marked_absent: number
      kept_pending: number
    }>(`/cctv/schedules/${scheduleId}/finalize`, { verified_by: verifiedBy, date })
  }

  // HOD & Student Portal + Audit Logs
  getHodReport(params?: { department?: string; section?: string; date?: string }) {
    const cleanParams: Record<string, string> = {}
    if (params?.department) cleanParams.department = params.department
    if (params?.section) cleanParams.section = params.section
    if (params?.date) cleanParams.date = params.date
    return this.client.get<HodReportResponse>("/cctv/hod/department-report", cleanParams)
  }

  getStudentSelfAttendance(memberId: string) {
    return this.client.get<StudentSelfAttendanceResponse>(`/cctv/student/${memberId}/attendance`)
  }

  listAuditLogs(limit = 50) {
    return this.client.get<
      {
        id: string
        timestamp: string | null
        action: string
        target_type: string | null
        target_id: string | null
        details: string | null
      }[]
    >("/cctv/audit-logs", { limit: String(limit) })
  }

  async probeIpStream(url: string) {
    try {
      return await this.client.post<{
        ok: boolean
        resolved_url: string
        width: number
        height: number
        mode: string
        message: string
      }>("/cctv/ip-stream/probe", { url })
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err)
      if (msg === "Not Found" || msg.includes("404")) {
        throw new Error(
          "Mobile IP camera route not found (404). The Facenox backend needs to be restarted — close and reopen the app, then try again.",
        )
      }
      throw err
    }
  }

  async getIpStreamDiagnostics(url: string): Promise<IpCameraDiagnostics> {
    return this.client.get<IpCameraDiagnostics>("/cctv/ip-stream/diagnostics", { url })
  }

  async reconnectIpStream(url: string): Promise<IpCameraDiagnostics> {
    return this.client.post<IpCameraDiagnostics>("/cctv/ip-stream/reconnect", { url })
  }

  async getIpStreamMjpegUrl(resolvedUrl: string): Promise<string> {
    let baseUrl = this.client.getBaseUrl()
    let token = ""
    try {
      const electronUrl = await window.electronAPI?.backend?.getUrl?.()
      if (typeof electronUrl === "string" && electronUrl.trim()) {
        baseUrl = electronUrl.trim()
      }
      const electronToken = await window.electronAPI?.backend?.getToken?.()
      if (typeof electronToken === "string") {
        token = electronToken
      }
    } catch {
      // Fallback to default local URL in non-Electron environments
    }

    const params = new URLSearchParams({
      url: resolvedUrl,
      _t: String(Date.now()),
    })
    if (token) {
      params.set("token", token)
    }
    return `${baseUrl}/cctv/ip-stream/mjpeg?${params.toString()}`
  }
}

export interface IpCameraDiagnostics {
  camera_id?: string | null
  raw_url: string
  resolved_url?: string | null
  status:
    | "CONNECTED"
    | "CONNECTING"
    | "DISCONNECTED"
    | "NO_FRAMES_RECEIVED"
    | "STREAM_FROZEN"
    | "LOW_FRAME_RATE"
    | "RECONNECTING"
    | "CAMERA_ERROR"
    | string
  camera_ip?: string
  camera_port?: number
  host_ips?: string[]
  subnet_compatible?: boolean
  fps?: number
  latency_ms?: number
  last_frame_age_seconds?: number | null
  reconnect_attempts?: number
  last_error?: string | null
  is_frozen?: boolean
  safe_for_attendance?: boolean
}

export const cctvService = new CctvService()

