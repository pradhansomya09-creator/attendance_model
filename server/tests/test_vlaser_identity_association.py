"""Tests for V-LASER Conservative Identity Association & Attendance Gatekeeper Engine."""

from __future__ import annotations

import time
import pytest
from core.vlaser.identity_association import (
    IdentityState,
    TrackIdentityBinding,
    VLaserIdentityAssociationManager,
)


@pytest.fixture
def identity_manager() -> VLaserIdentityAssociationManager:
    return VLaserIdentityAssociationManager(camera_id="cam-lh1-test")


def test_case_a_clear_face_verified(identity_manager: VLaserIdentityAssociationManager):
    """Case A: Clear, frontal, real face with confident recognition confirms identity."""
    track_id = 101
    face_dict = {
        "bbox": {"x": 100, "y": 100, "width": 80, "height": 80},
        "head_pose": {"yaw": 5.0, "pitch": 3.0, "pose_ok": True},
        "liveness": {"status": "real", "is_real": True},
        "recognition": {
            "person_id": "STU_2024_001",
            "name": "Jane Doe",
            "similarity": 0.72,
            "temporal_consistency": 0.85,
        },
    }

    binding = identity_manager.evaluate_track_identity(
        track_id=track_id,
        face_detected=True,
        face_dict=face_dict,
        quality_score=0.88,
        quality_status="green",
    )

    assert binding.track_id == track_id
    assert binding.identity_state == IdentityState.IDENTITY_VERIFIED
    assert binding.person_id == "STU_2024_001"
    assert binding.student_name == "Jane Doe"
    assert binding.recognition_confidence == 0.72
    assert binding.verified_at is not None


def test_case_b_small_or_low_quality_pending(identity_manager: VLaserIdentityAssociationManager):
    """Case B: Face too small or poor quality remains pending, never forced."""
    track_id = 102
    # Small face (< 48px)
    small_face = {
        "bbox": {"x": 100, "y": 100, "width": 32, "height": 32},
        "head_pose": {"yaw": 2.0, "pitch": 2.0, "pose_ok": True},
        "liveness": {"status": "real", "is_real": True},
        "recognition": {
            "person_id": "STU_2024_002",
            "name": "John Smith",
            "similarity": 0.45,
            "temporal_consistency": 0.50,
        },
    }

    binding_small = identity_manager.evaluate_track_identity(
        track_id=track_id,
        face_detected=True,
        face_dict=small_face,
        quality_score=0.85,
        quality_status="green",
    )

    assert binding_small.identity_state == IdentityState.PENDING_VERIFICATION
    assert binding_small.person_id is None  # Not verified yet!

    # Severe angle face (yaw > 25 degrees)
    turned_face = {
        "bbox": {"x": 100, "y": 100, "width": 80, "height": 80},
        "head_pose": {"yaw": 38.0, "pitch": 5.0, "pose_ok": False},
        "liveness": {"status": "real", "is_real": True},
        "recognition": {
            "person_id": "STU_2024_002",
            "name": "John Smith",
            "similarity": 0.65,
            "temporal_consistency": 0.80,
        },
    }

    binding_turned = identity_manager.evaluate_track_identity(
        track_id=track_id,
        face_detected=True,
        face_dict=turned_face,
        quality_score=0.85,
        quality_status="green",
    )

    assert binding_turned.identity_state == IdentityState.PENDING_VERIFICATION
    assert binding_turned.person_id is None


def test_case_c_face_not_visible_spatially_tracked_only(identity_manager: VLaserIdentityAssociationManager):
    """Case C: Person tracked kinematically without visible face must be marked Spatially Tracked Only."""
    track_id = 103

    binding = identity_manager.evaluate_track_identity(
        track_id=track_id,
        face_detected=False,
        face_dict=None,
        quality_score=0.0,
        quality_status="none",
    )

    assert binding.identity_state == IdentityState.SPATIALLY_TRACKED
    assert binding.person_id is None
    assert binding.student_name is None
    assert binding.attendance_eligible is False


def test_unknown_person_classification(identity_manager: VLaserIdentityAssociationManager):
    """Unrecognized real person gets classified as UNKNOWN_PERSON."""
    track_id = 104
    unknown_face = {
        "bbox": {"x": 100, "y": 100, "width": 75, "height": 75},
        "head_pose": {"yaw": 4.0, "pitch": 2.0, "pose_ok": True},
        "liveness": {"status": "real", "is_real": True},
        "recognition": {
            "person_id": "unknown",
            "name": None,
            "similarity": 0.15,
            "temporal_consistency": 0.10,
        },
    }

    binding = identity_manager.evaluate_track_identity(
        track_id=track_id,
        face_detected=True,
        face_dict=unknown_face,
        quality_score=0.82,
        quality_status="green",
    )

    assert binding.identity_state == IdentityState.UNKNOWN_PERSON
    assert binding.person_id is None
    assert binding.attendance_eligible is False


def test_attendance_gatekeeping_rules(identity_manager: VLaserIdentityAssociationManager):
    """Entering classroom or crossing entry line does NOT automatically mark attendance.
    
    Attendance eligibility requires BOTH verified identity AND spatial presence.
    """
    track_id = 105

    # 1. Crossing entry line without verified identity does NOT grant eligibility
    identity_manager.record_spatial_entry(track_id=track_id, timestamp=time.time())
    binding = identity_manager.get_binding(track_id)
    assert binding is not None
    assert binding.entered_classroom is True
    assert binding.identity_state == IdentityState.SPATIALLY_TRACKED
    assert binding.attendance_eligible is False  # Gatekeeper blocks unverified student!

    # 2. Add verified identity to this track
    face_dict = {
        "bbox": {"x": 100, "y": 100, "width": 80, "height": 80},
        "head_pose": {"yaw": 2.0, "pitch": 1.0, "pose_ok": True},
        "liveness": {"status": "real", "is_real": True},
        "recognition": {
            "person_id": "STU_2024_005",
            "name": "Alice Wonder",
            "similarity": 0.78,
            "temporal_consistency": 0.90,
        },
    }
    binding = identity_manager.evaluate_track_identity(
        track_id=track_id,
        face_detected=True,
        face_dict=face_dict,
        quality_score=0.90,
        quality_status="green",
    )
    assert binding.identity_state == IdentityState.IDENTITY_VERIFIED
    # Now both criteria (verified + entered) are satisfied
    assert binding.attendance_eligible is True


def test_seating_zone_residence_eligibility(identity_manager: VLaserIdentityAssociationManager):
    """Presence in seating area for >= 5s satisfies spatial presence even without explicit entry line."""
    track_id = 106
    face_dict = {
        "bbox": {"x": 100, "y": 100, "width": 70, "height": 70},
        "head_pose": {"yaw": 0.0, "pitch": 0.0, "pose_ok": True},
        "liveness": {"status": "real", "is_real": True},
        "recognition": {
            "person_id": "STU_2024_006",
            "name": "Bob Marley",
            "similarity": 0.65,
            "temporal_consistency": 0.70,
        },
    }
    binding = identity_manager.evaluate_track_identity(
        track_id=track_id,
        face_detected=True,
        face_dict=face_dict,
        quality_score=0.80,
        quality_status="green",
    )
    # Not yet eligible because spatial presence is 0 seconds
    assert binding.attendance_eligible is False

    # Spend 3 seconds in seating zone -> still under 5s
    for _ in range(15):
        identity_manager.update_zone_residence(track_id, "student_seating", delta_seconds=0.2)
    assert binding.time_in_seating_zone_seconds == pytest.approx(3.0, abs=0.01)
    assert binding.attendance_eligible is False

    # Spend another 3 seconds (total 6s) -> exceeds 5s threshold -> attendance eligible!
    for _ in range(15):
        identity_manager.update_zone_residence(track_id, "student_seating", delta_seconds=0.2)
    assert binding.time_in_seating_zone_seconds == pytest.approx(6.0, abs=0.01)
    assert binding.attendance_eligible is True


def test_prune_stale_tracks(identity_manager: VLaserIdentityAssociationManager):
    """Old tracks inactive for > max_age_seconds are pruned."""
    now = 1000.0
    identity_manager.record_spatial_entry(track_id=1, timestamp=now - 20.0)
    identity_manager.record_spatial_entry(track_id=2, timestamp=now - 2.0)

    identity_manager.prune_stale_tracks(max_age_seconds=10.0, now=now)

    assert identity_manager.get_binding(1) is None
    assert identity_manager.get_binding(2) is not None

