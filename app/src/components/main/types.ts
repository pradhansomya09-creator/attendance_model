// Shared types for Main component

import type { AttendanceGroup, AttendanceMember, AttendanceRecord } from "@/types/recognition"
import type { ExtendedFaceRecognitionResponse } from "@/components/main/utils"

export interface DetectionResult {
  faces: {
    bbox: {
      x: number
      y: number
      width: number
      height: number
    }
    renderOpacity?: number
    confidence: number
    track_id?: number
    landmarks_5: number[][]
    low_light?: boolean
    liveness?: {
      is_real: boolean | null
      confidence?: number
      logit_diff?: number
      real_logit?: number
      spoof_logit?: number
      status:
        | "real"
        | "spoof"
        | "candidate_real"
        | "unknown"
        | "error"
        | "move_closer"
        | "center_face"
        | "glare"
        | "too_dark"
        | "look_at_camera"
      attack_type?: string
      message?: string
    }
    overlayGuidance?: {
      label: string
      subLabel?: string
      tone: "warning" | "failure"
      isLowLight?: boolean
    }
    recognition?: ExtendedFaceRecognitionResponse
  }[]
  model_used: string
}

export interface ImageQualityTelemetry {
  status: "green" | "yellow" | "red"
  score: number
  brightness: number
  contrast: number
  sharpness: number
  haze_score: number
  overexposed_ratio: number
  underexposed_ratio: number
  obstruction_score: number
  is_ir_mode: boolean
  recognition_reliable: boolean
  issues: string[]
  enhancements_applied: string[]
}

export interface HeadPoseTelemetry {
  yaw: number
  pitch: number
  roll: number
  pose_ok: boolean
  occlusion_suspected: boolean
  visibility_score: number
  clarity_score: number
}

export interface HeadcountSummaryTelemetry {
  enrolled: number
  unique_detected: number
  successfully_identified: number
  unknown_individuals: number
  pending_verification: number
  confirmed_present: number
  section_mismatches: number
  duplicate_alerts: number
}

export interface CctvAlertMessage {
  type: "cctv_alert"
  alert_type: "quality_warning" | "unknown_student" | "section_mismatch" | string
  severity: "info" | "warning" | "critical" | string
  camera_id?: string | null
  group_id?: string | null
  detection_id?: string | null
  tracking_id?: string | null
  person_id?: string | null
  student_name?: string | null
  actual_section?: string | null
  scheduled_section?: string | null
  quality_status?: string | null
  quality_score?: number | null
  issues?: string[]
  message: string
  timestamp: number
}

export interface WebSocketFaceData {
  bbox?: number[]
  confidence?: number
  track_id?: number
  landmarks_5?: number[][] // Required by our pipeline; validated at mapping time.
  low_light?: boolean
  head_pose?: HeadPoseTelemetry
  liveness?: {
    is_real?: boolean | null
    confidence?: number
    logit_diff?: number
    real_logit?: number
    spoof_logit?: number
    status?:
      | "real"
      | "spoof"
      | "candidate_real"
      | "unknown"
      | "error"
      | "move_closer"
      | "center_face"
      | "glare"
      | "too_dark"
      | "look_at_camera"
    attack_type?: string
    message?: string
  }
  recognition?: ExtendedFaceRecognitionResponse
}

export interface WebSocketDetectionResponse {
  faces?: WebSocketFaceData[]
  model_used?: string
  timestamp?: number
  frame_timestamp?: number
  frame_dropped?: boolean
  suggested_skip?: number
  image_quality?: ImageQualityTelemetry
  headcount_summary?: HeadcountSummaryTelemetry | null
  performance_metrics?: {
    actual_fps?: number
    overload_counter?: number
    samples_count?: number
    queue_size?: number
    dropped_frames?: number
    max_performance_mode?: boolean
  }
}

export interface AttendanceEvent {
  type: "attendance_event"
  person_id: string
  group_id: string
  event_type: "check_in" | "check_out"
  timestamp: string
  check_in_time?: string
  check_out_time?: string
  total_hours?: number
  time_health?: {
    warning_message?: string
    timezone_mismatch?: boolean
    device_time_zone_name?: string | null
    attendance_time_zone_name?: string | null
    timezone_warning_message?: string | null
    os_clock_warning?: string | null
    online_verification_status?: string
    online_drift_seconds?: number
  }
  member?: {
    name?: string
    role?: string
  }
  bbox?: {
    x?: number
    y?: number
    width?: number
    height?: number
  }
  track_id?: number
}

export interface WebSocketConnectionMessage {
  message?: string
  status?: string
}

export interface WebSocketErrorMessage {
  message?: string
  error?: string
}

export interface TrackedFace {
  id: string
  bbox: { x: number; y: number; width: number; height: number }
  confidence: number
  lastSeen: number
  trackingHistory: {
    timestamp: number
    bbox: { x: number; y: number; width: number; height: number }
    confidence: number
  }[]
  isLocked: boolean
  personId?: string
  occlusionCount: number
  angleConsistency: number
  livenessStatus?:
    | "real"
    | "spoof"
    | "candidate_real"
    | "unknown"
    | "error"
    | "move_closer"
    | "center_face"
    | "glare"
    | "too_dark"
    | "look_at_camera"
  unknownFramesCount?: number
}

export interface CooldownInfo {
  personId: string
  memberName?: string
  startTime: number
  lastKnownBbox?: { x: number; y: number; width: number; height: number }
  // Store the cooldown duration that was active when this cooldown was created
  // This prevents premature removal when the setting changes
  cooldownDurationSeconds: number
}

// Re-export needed types
export type { AttendanceGroup, AttendanceMember, AttendanceRecord }
