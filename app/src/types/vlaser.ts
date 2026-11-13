export type LineType = "entry" | "exit" | "internal" | "restricted"

export type LineDirection = "bidirectional" | "forward" | "backward"

export type ZoneType =
  | "classroom_entrance"
  | "student_seating"
  | "teacher_area"
  | "front_teaching"
  | "restricted_area"
  | "custom"

export interface Point2D {
  x: number
  y: number
}

export interface VirtualLine {
  id: string
  name: string
  line_type: LineType
  direction: LineDirection
  p1: Point2D
  p2: Point2D
  color?: string | null
  enabled: boolean
}

export interface VirtualZone {
  id: string
  name: string
  zone_type: ZoneType
  polygon: Point2D[]
  color?: string | null
  opacity: number
  enabled: boolean
}

export interface VLaserConfig {
  camera_id: string
  classroom?: string | null
  grid_enabled: boolean
  grid_rows: number
  grid_cols: number
  grid_color: string
  grid_opacity: number
  lines: VirtualLine[]
  zones: VirtualZone[]
  is_active: boolean
}

export interface ValidationResponse {
  valid: boolean
  errors: string[]
  warnings: string[]
}

export interface CameraPreviewFrameResponse {
  camera_id: string
  width: number
  height: number
  image_data_url: string
}

export type SpatialEventType =
  | "entry"
  | "exit"
  | "zone_transition"
  | "restricted_violation"
  | "line_crossing"

export type IdentityState =
  | "identity_verified"
  | "face_processing"
  | "pending_verification"
  | "spatially_tracked"
  | "unknown_person"

export interface SpatialEvent {
  id: string
  camera_id: string
  track_id: number
  event_type: SpatialEventType
  line_id?: string | null
  line_name?: string | null
  line_type?: LineType | null
  from_zone_id?: string | null
  from_zone_name?: string | null
  to_zone_id?: string | null
  to_zone_name?: string | null
  direction?: string | null
  anchor?: Point2D | null
  confidence: number
  timestamp: number
}

export interface TrackedPersonSpatial {
  track_id: number
  anchor: Point2D
  current_zone_id: string | null
  current_zone_name: string | null
  frames_in_zone: number
  total_frames: number
  last_seen_seconds_ago: number
  trail?: Point2D[]
  is_occluded?: boolean
  candidate_student_name?: string | null
  occlusion_frames?: number
  identity_state?: IdentityState
  person_id?: string | null
  student_name?: string | null
  recognition_confidence?: number
  temporal_consistency?: number
  entered_classroom?: boolean
  attendance_eligible?: boolean
  attendance_marked?: boolean
}

export interface CameraSpatialStateResponse {
  camera_id: string
  active_tracks_count: number
  active_tracks: TrackedPersonSpatial[]
  zone_headcounts: Record<string, number>
  recent_events: SpatialEvent[]
}


