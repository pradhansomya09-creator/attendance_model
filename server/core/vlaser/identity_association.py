"""V-LASER Conservative Identity Association and Attendance Gatekeeper Engine.

Strictly decouples kinematic spatial tracking from biometric identification:
- Evaluates 5 distinct identity states.
- Applies conservative association rules (Case A: Clear face, Case B: Small/low quality, Case C: Face not visible).
- Prohibits inferring student identity from clothing, shape, or appearance.
- Enforces that spatial entry/presence alone NEVER automatically marks attendance.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class IdentityState(str, Enum):
    IDENTITY_VERIFIED = "identity_verified"
    FACE_PROCESSING = "face_processing"
    PENDING_VERIFICATION = "pending_verification"
    SPATIALLY_TRACKED = "spatially_tracked"
    UNKNOWN_PERSON = "unknown_person"


@dataclass
class TrackIdentityBinding:
    """Maintains conservative identity association state for a single spatial track."""

    track_id: int
    identity_state: IdentityState = IdentityState.SPATIALLY_TRACKED
    person_id: Optional[str] = None
    student_name: Optional[str] = None
    registration_number: Optional[str] = None
    department: Optional[str] = None
    section: Optional[str] = None
    recognition_confidence: float = 0.0
    temporal_consistency: float = 0.0
    quality_score: float = 1.0
    liveness_status: str = "pending"
    head_pose_ok: bool = True
    verified_at: Optional[float] = None
    first_seen_at: float = field(default_factory=time.time)
    last_seen_at: float = field(default_factory=time.time)
    entered_classroom: bool = False
    entry_line_crossed_at: Optional[float] = None
    time_in_seating_zone_seconds: float = 0.0
    attendance_eligible: bool = False
    attendance_marked: bool = False

    # Overlap, occlusion recovery & candidate retention buffer
    candidate_person_id: Optional[str] = None
    candidate_name: Optional[str] = None
    candidate_similarity: float = 0.0
    is_occluded: bool = False
    occlusion_frames: int = 0
    last_face_seen_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "track_id": self.track_id,
            "identity_state": self.identity_state.value,
            "person_id": self.person_id,
            "student_name": self.student_name,
            "registration_number": self.registration_number,
            "department": self.department,
            "section": self.section,
            "recognition_confidence": round(self.recognition_confidence, 3),
            "temporal_consistency": round(self.temporal_consistency, 3),
            "quality_score": round(self.quality_score, 3),
            "liveness_status": self.liveness_status,
            "head_pose_ok": self.head_pose_ok,
            "verified_at": round(self.verified_at, 2) if self.verified_at else None,
            "entered_classroom": self.entered_classroom,
            "attendance_eligible": self.attendance_eligible,
            "attendance_marked": self.attendance_marked,
            "is_occluded": self.is_occluded,
            "candidate_name": self.candidate_name,
            "occlusion_frames": self.occlusion_frames,
        }


class VLaserIdentityAssociationManager:
    """Manages conservative biometric-to-spatial track identity bindings."""

    MIN_FACE_SIZE_FOR_RECOGNITION = 48
    MIN_QUALITY_SCORE_FOR_CONFIRM = 0.38
    MAX_YAW_DEGREES_FOR_CONFIRM = 25.0
    MAX_PITCH_DEGREES_FOR_CONFIRM = 25.0
    MIN_RECOGNITION_SIMILARITY = 0.36
    MIN_TEMPORAL_CONSISTENCY = 0.55

    def __init__(self, camera_id: str):
        self.camera_id = camera_id
        self._bindings: Dict[int, TrackIdentityBinding] = {}

    def clear(self) -> None:
        self._bindings.clear()

    def get_binding(self, track_id: int) -> Optional[TrackIdentityBinding]:
        return self._bindings.get(track_id)

    def get_all_bindings(self) -> List[TrackIdentityBinding]:
        return list(self._bindings.values())

    def record_spatial_entry(self, track_id: int, timestamp: Optional[float] = None) -> None:
        """Record when a track crosses a virtual Entry line."""
        now = timestamp if timestamp is not None else time.time()
        binding = self._bindings.setdefault(track_id, TrackIdentityBinding(track_id=track_id, first_seen_at=now))
        binding.entered_classroom = True
        binding.entry_line_crossed_at = now
        binding.last_seen_at = now
        self._recompute_attendance_eligibility(binding)

    def update_zone_residence(
        self, track_id: int, current_zone_type: Optional[str], delta_seconds: float = 0.2
    ) -> None:
        """Update residence duration inside student seating or classroom area."""
        binding = self._bindings.get(track_id)
        if not binding:
            return

        if current_zone_type in ("student_seating", "classroom_entrance", "front_teaching"):
            binding.time_in_seating_zone_seconds += delta_seconds
            self._recompute_attendance_eligibility(binding)

    def evaluate_track_identity(
        self,
        *,
        track_id: int,
        face_detected: bool,
        face_dict: Optional[Dict[str, Any]],
        quality_score: float,
        quality_status: str,
        now: Optional[float] = None,
    ) -> TrackIdentityBinding:
        """Evaluate biometric observations for a spatial track according to Cases A, B, and C."""
        ts = now if now is not None else time.time()
        binding = self._bindings.setdefault(
            track_id, TrackIdentityBinding(track_id=track_id, first_seen_at=ts)
        )
        binding.last_seen_at = ts
        binding.quality_score = float(quality_score)

        # If already verified, retain verified state during transit and zone movements
        if binding.identity_state == IdentityState.IDENTITY_VERIFIED:
            if not face_detected or not face_dict:
                binding.is_occluded = True
                binding.occlusion_frames += 1
            else:
                binding.is_occluded = False
                binding.occlusion_frames = 0
                binding.last_face_seen_at = ts
            self._recompute_attendance_eligibility(binding)
            return binding

        # -------------------------------------------------------------------
        # Case C: Face Not Visible / Occluded / Overlapped
        # -------------------------------------------------------------------
        if not face_detected or not face_dict:
            binding.is_occluded = True
            binding.occlusion_frames += 1

            # If student had candidate face in flight within last 4.0s, hold candidate state during overlap
            if binding.candidate_person_id and binding.last_face_seen_at and (ts - binding.last_face_seen_at) <= 4.0:
                binding.identity_state = IdentityState.FACE_PROCESSING
                self._recompute_attendance_eligibility(binding)
                return binding

            # Person is tracked spatially, waiting for face to turn or clear
            binding.identity_state = IdentityState.SPATIALLY_TRACKED
            self._recompute_attendance_eligibility(binding)
            return binding

        # Face is visible
        binding.is_occluded = False
        binding.occlusion_frames = 0
        binding.last_face_seen_at = ts

        bbox = face_dict.get("bbox") or {}
        w = float(bbox.get("width", 0)) if isinstance(bbox, dict) else (bbox[2] if len(bbox) >= 4 else 0)
        h = float(bbox.get("height", 0)) if isinstance(bbox, dict) else (bbox[3] if len(bbox) >= 4 else 0)
        face_size = max(w, h)

        pose = face_dict.get("head_pose") or {}
        yaw = abs(float(pose.get("yaw", 0.0)))
        pitch = abs(float(pose.get("pitch", 0.0)))
        pose_ok = bool(pose.get("pose_ok", True))
        binding.head_pose_ok = pose_ok

        liveness = face_dict.get("liveness") or {}
        liveness_status = str(liveness.get("status", "pending"))
        is_real = bool(liveness.get("is_real", False))
        binding.liveness_status = liveness_status

        rec = face_dict.get("recognition") or {}
        person_id = rec.get("person_id")
        student_name = rec.get("name")
        similarity = float(rec.get("similarity", 0.0))
        consistency = float(rec.get("temporal_consistency", 0.0))

        # -------------------------------------------------------------------
        # Case B: Small or Low-Quality Face / Severe Angle
        # -------------------------------------------------------------------
        is_small = face_size < self.MIN_FACE_SIZE_FOR_RECOGNITION
        is_low_quality = quality_status == "red" or quality_score < self.MIN_QUALITY_SCORE_FOR_CONFIRM
        is_turned = yaw > self.MAX_YAW_DEGREES_FOR_CONFIRM or pitch > self.MAX_PITCH_DEGREES_FOR_CONFIRM

        if is_small or is_low_quality or is_turned:
            # Maintain spatial tracking, wait for a clearer observation, do NOT force recognition
            binding.identity_state = IdentityState.PENDING_VERIFICATION
            self._recompute_attendance_eligibility(binding)
            return binding

        # -------------------------------------------------------------------
        # Case A: Clear Face
        # -------------------------------------------------------------------
        # Quality is acceptable and face is sufficiently large & frontal
        binding.recognition_confidence = similarity
        binding.temporal_consistency = consistency

        # Check liveness
        if not is_real and liveness_status in ("spoof", "candidate_spoof"):
            binding.identity_state = IdentityState.PENDING_VERIFICATION
            self._recompute_attendance_eligibility(binding)
            return binding

        # Check recognition match
        if person_id and person_id != "unknown" and similarity >= self.MIN_RECOGNITION_SIMILARITY:
            binding.candidate_person_id = person_id
            binding.candidate_name = student_name
            binding.candidate_similarity = max(binding.candidate_similarity, similarity)
            if consistency >= self.MIN_TEMPORAL_CONSISTENCY or similarity >= 0.50:
                # Conservatively verified
                binding.identity_state = IdentityState.IDENTITY_VERIFIED
                binding.person_id = person_id
                binding.student_name = student_name
                binding.verified_at = ts
            else:
                # Accumulating temporal multi-frame votes
                binding.identity_state = IdentityState.FACE_PROCESSING
        elif person_id is None or person_id == "unknown":
            if is_real and similarity < self.MIN_RECOGNITION_SIMILARITY:
                # Unrecognized face in group
                binding.identity_state = IdentityState.UNKNOWN_PERSON
            else:
                binding.identity_state = IdentityState.FACE_PROCESSING

        self._recompute_attendance_eligibility(binding)
        return binding

    def _recompute_attendance_eligibility(self, binding: TrackIdentityBinding) -> None:
        """Attendance requires BOTH biometric verification AND spatial presence.
        
        Entering a classroom or crossing an entry line does NOT automatically mark attendance.
        """
        # Criteria:
        # 1. Identity must be verified
        # 2. Must have spatial presence (either crossed entry line OR stayed in seating zone >= 5.0 seconds)
        has_identity = binding.identity_state == IdentityState.IDENTITY_VERIFIED and bool(binding.person_id)
        has_spatial_presence = binding.entered_classroom or (binding.time_in_seating_zone_seconds >= 5.0)

        binding.attendance_eligible = has_identity and has_spatial_presence

    def prune_stale_tracks(self, max_age_seconds: float = 10.0, now: Optional[float] = None) -> None:
        ts = now if now is not None else time.time()
        stale = [tid for tid, b in self._bindings.items() if (ts - b.last_seen_at) > max_age_seconds]
        for tid in stale:
            self._bindings.pop(tid, None)

