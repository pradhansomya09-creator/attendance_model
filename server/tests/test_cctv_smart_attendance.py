"""Comprehensive tests for Advanced CCTV-Based Smart Attendance modules & API routes."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import cv2
import numpy as np
import pytest

from test_api_biometrics import (
    biometrics_env as biometrics_env,
    _create_group,
    _create_member,
    _enroll_metadata,
    _headers,
    _make_image_bytes,
)


def _bright_textured_frame(h: int = 240, w: int = 320) -> np.ndarray:
    img = np.full((h, w, 3), 130, dtype=np.uint8)
    for x in range(0, w, 24):
        cv2.line(img, (x, 0), (x, h), (190, 200, 210), 2)
    for y in range(0, h, 24):
        cv2.line(img, (0, y), (w, y), (80, 90, 100), 2)
    cv2.putText(img, "ROOM 101", (60, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (245, 245, 245), 2)
    return img


# ---------------------------------------------------------------------------
# 1. Image Quality Detection & Adaptive Enhancement
# ---------------------------------------------------------------------------


def test_image_quality_darkness_enhancement_and_red_threshold():
    from core.vision.image_quality import analyze_and_enhance_frame

    # Normal textured scene -> green & reliable
    healthy = _bright_textured_frame()
    _, green_report = analyze_and_enhance_frame(healthy)
    assert green_report.status == "green"
    assert green_report.recognition_reliable is True
    assert green_report.score >= 0.68

    # Moderately dim colored classroom -> enhanced with CLAHE/gamma/IR
    colored = _bright_textured_frame()
    colored[:, :, 0] = np.clip(colored[:, :, 0].astype(np.int16) - 25, 0, 255).astype(np.uint8)
    dim = (colored.astype(np.float32) * 0.30).astype(np.uint8)
    enhanced_dim, dim_report = analyze_and_enhance_frame(dim)
    assert any(
        k in dim_report.enhancements_applied
        for k in ("gamma_correction", "clahe_contrast", "infrared_clahe")
    )
    assert float(np.mean(enhanced_dim)) > float(np.mean(dim))

    # Pitch black / obstructed camera -> red & NOT recognition_reliable
    pitch_black = np.zeros((240, 320, 3), dtype=np.uint8)
    _, red_report = analyze_and_enhance_frame(pitch_black)
    assert red_report.status == "red"
    assert red_report.recognition_reliable is False
    assert any(
        issue in red_report.issues
        for issue in ("severe_darkness", "camera_obstructed", "underexposed")
    )


def test_image_quality_overexposed_and_ir_mode():
    from core.vision.image_quality import analyze_and_enhance_frame

    # Overexposed whiteout -> flagged & suppressed
    glare = np.full((240, 320, 3), 252, dtype=np.uint8)
    _, glare_report = analyze_and_enhance_frame(glare)
    assert glare_report.status in ("yellow", "red")
    assert "overexposed" in glare_report.issues or "camera_obstructed" in glare_report.issues

    # Monochrome IR frame -> is_ir_mode True
    gray_scene = cv2.cvtColor(_bright_textured_frame(), cv2.COLOR_BGR2GRAY)
    ir_frame = cv2.merge([gray_scene, gray_scene, gray_scene])
    _, ir_report = analyze_and_enhance_frame(ir_frame)
    assert ir_report.is_ir_mode is True


# ---------------------------------------------------------------------------
# 2. Head Pose & Occlusion Estimation
# ---------------------------------------------------------------------------


def test_head_pose_frontal_vs_rotated_and_occluded():
    from core.vision.head_pose import estimate_head_pose_and_occlusion

    img = _bright_textured_frame()
    # Symmetric frontal landmarks
    frontal_face = {
        "bbox": {"x": 80, "y": 40, "width": 140, "height": 140},
        "confidence": 0.98,
        "landmarks_5": [
            [115, 85],   # right eye
            [185, 85],   # left eye
            [150, 115],  # nose
            [125, 148],  # right mouth
            [175, 148],  # left mouth
        ],
    }
    frontal_pose = estimate_head_pose_and_occlusion(img, frontal_face)
    assert frontal_pose.pose_ok is True
    assert frontal_pose.visibility_score >= 0.55

    # Heavily turned head (nose close to one eye) + low detection confidence (occlusion)
    turned_face = {
        "bbox": {"x": 80, "y": 40, "width": 140, "height": 140},
        "confidence": 0.42,
        "landmarks_5": [
            [110, 85],
            [185, 85],
            [112, 115],  # strongly skewed to right eye
            [120, 148],
            [168, 148],
        ],
    }
    turned_pose = estimate_head_pose_and_occlusion(img, turned_face)
    assert abs(turned_pose.yaw) > 25.0 or turned_pose.occlusion_suspected is True
    assert turned_pose.pose_ok is False


# ---------------------------------------------------------------------------
# 3. Centralized Engine: 10-Factor Verification, Entry/Exit & Red-Quality Fail-Safe
# ---------------------------------------------------------------------------


def test_centralized_classification_and_entry_exit_rules():
    from core.vision.image_quality import ImageQualityReport
    from services.smart_attendance_engine import SmartAttendanceEngine

    green = ImageQualityReport(
        status="green",
        score=0.9,
        brightness=125.0,
        contrast=40.0,
        sharpness=110.0,
        haze_score=0.05,
        overexposed_ratio=0.0,
        underexposed_ratio=0.0,
        obstruction_score=0.0,
        is_ir_mode=False,
        recognition_reliable=True,
    )
    red = ImageQualityReport(
        status="red",
        score=0.18,
        brightness=10.0,
        contrast=4.0,
        sharpness=5.0,
        haze_score=0.8,
        overexposed_ratio=0.0,
        underexposed_ratio=0.95,
        obstruction_score=0.9,
        is_ir_mode=False,
        recognition_reliable=False,
        issues=["severe_darkness"],
    )

    # Red quality -> pending_verification (never absent or present)
    cls_red, _ = SmartAttendanceEngine.compute_centralized_classification(
        recognition_confidence=0.95,
        image_quality=red,
        visibility_score=0.9,
        temporal_consistency=1.0,
        observations_count=5,
        pose_ok=True,
        is_registered=True,
        section_matched=True,
        has_exception=False,
        camera_online=True,
        duplicate_flagged=False,
        non_biometric_opt_out=False,
    )
    assert cls_red == "pending_verification"

    # Offline camera -> pending_verification
    cls_off, _ = SmartAttendanceEngine.compute_centralized_classification(
        recognition_confidence=0.95,
        image_quality=green,
        visibility_score=0.9,
        temporal_consistency=1.0,
        observations_count=5,
        pose_ok=True,
        is_registered=True,
        section_matched=True,
        has_exception=False,
        camera_online=False,
        duplicate_flagged=False,
        non_biometric_opt_out=False,
    )
    assert cls_off == "pending_verification"

    # Non-biometric opt-out -> pending_verification
    cls_opt, _ = SmartAttendanceEngine.compute_centralized_classification(
        recognition_confidence=0.95,
        image_quality=green,
        visibility_score=0.9,
        temporal_consistency=1.0,
        observations_count=5,
        pose_ok=True,
        is_registered=True,
        section_matched=True,
        has_exception=False,
        camera_online=True,
        duplicate_flagged=False,
        non_biometric_opt_out=True,
    )
    assert cls_opt == "pending_verification"

    # Section mismatch without exception -> section_mismatch
    cls_sec, _ = SmartAttendanceEngine.compute_centralized_classification(
        recognition_confidence=0.95,
        image_quality=green,
        visibility_score=0.9,
        temporal_consistency=1.0,
        observations_count=5,
        pose_ok=True,
        is_registered=True,
        section_matched=False,
        has_exception=False,
        camera_online=True,
        duplicate_flagged=False,
        non_biometric_opt_out=False,
    )
    assert cls_sec == "section_mismatch"

    # Section mismatch WITH approved exception -> cctv_verified_present
    cls_exc, _ = SmartAttendanceEngine.compute_centralized_classification(
        recognition_confidence=0.95,
        image_quality=green,
        visibility_score=0.9,
        temporal_consistency=1.0,
        observations_count=5,
        pose_ok=True,
        is_registered=True,
        section_matched=False,
        has_exception=True,
        camera_online=True,
        duplicate_flagged=False,
        non_biometric_opt_out=False,
    )
    assert cls_exc == "cctv_verified_present"

    # Entry/exit rules
    from database.models import AcademicSchedule

    sched = AcademicSchedule(
        id="s1",
        department="CSE",
        semester="5",
        section="A",
        subject_code="CS501",
        subject_name="AI",
        faculty_name="Dr. Rao",
        classroom="LH-1",
        start_time="09:00",
        end_time="10:00",
        late_after_minutes=10,
        early_exit_minutes=10,
        min_presence_percent=60.0,
    )
    full_status, dur_full = SmartAttendanceEngine.evaluate_entry_exit_rule(
        first_seen_at=datetime(2026, 11, 12, 9, 2),
        last_seen_at=datetime(2026, 11, 12, 9, 55),
        schedule=sched,
        group=None,
        classification="cctv_verified_present",
    )
    assert full_status == "full_attendance"
    assert dur_full == pytest.approx(53.0)

    late_status, _ = SmartAttendanceEngine.evaluate_entry_exit_rule(
        first_seen_at=datetime(2026, 11, 12, 9, 25),
        last_seen_at=datetime(2026, 11, 12, 9, 55),
        schedule=sched,
        group=None,
        classification="cctv_verified_present",
    )
    assert late_status == "late_entry"


# ---------------------------------------------------------------------------
# 4. Live Stream: Cross-Section Validation, Unknown Queue & Red-Quality Guard
# ---------------------------------------------------------------------------


def test_live_stream_section_mismatch_red_quality_and_unknown_queue(biometrics_env):
    from core.vision.image_quality import analyze_and_enhance_frame
    from services.live_stream_service import LiveSessionConfig, LiveStreamService

    client = biometrics_env["client"]
    org = "smart-cctv-org"
    headers = _headers(org)
    group_b = _create_group(client, headers, "CSE-Sem5-B")

    # Enroll student belonging to Section A
    _create_member(client, headers, group_b, "stu-a", "Aarav SectionA")
    m_a = client.get("/attendance/members/stu-a", headers=headers).json()
    client.post(
        f"/attendance/groups/{group_b}/persons/stu-a/enroll-face",
        headers=headers,
        data={"metadata": _enroll_metadata()},
        files={"image": ("a.jpg", _make_image_bytes(), "image/jpeg")},
    )
    prof_res = client.put(
        f"/cctv/student-profiles/{m_a['id']}",
        headers=headers,
        json={
            "registration_number": "REG2026-001",
            "department": "CSE",
            "semester": "5",
            "section": "A",
            "biometric_consent_granted": True,
            "non_biometric_opt_out": False,
        },
    )
    assert prof_res.status_code == 200, prof_res.text

    # Create simulated CCTV camera and Section B schedule
    cam_res = client.post(
        "/cctv/cameras",
        headers=headers,
        json={
            "name": "LH-202 Front Cam",
            "camera_code": "CAM-202",
            "source_type": "simulated",
            "classroom": "LH-202",
            "department": "CSE",
            "assigned_group_id": group_b,
        },
    )
    assert cam_res.status_code == 200, cam_res.text
    camera_id = cam_res.json()["id"]

    sched_res = client.post(
        "/cctv/schedules",
        headers=headers,
        json={
            "group_id": group_b,
            "department": "CSE",
            "semester": "5",
            "section": "B",
            "subject_code": "CS502",
            "subject_name": "Computer Networks",
            "faculty_name": "Prof. Mehta",
            "classroom": "LH-202",
            "camera_id": camera_id,
            "start_time": "00:00",
            "end_time": "23:59",
        },
    )
    assert sched_res.status_code == 200, sched_res.text
    schedule_id = sched_res.json()["id"]

    bright_img = _bright_textured_frame()
    _, green_report = analyze_and_enhance_frame(bright_img)
    _, red_report = analyze_and_enhance_frame(np.zeros((240, 320, 3), dtype=np.uint8))

    async def scenario():
        svc = LiveStreamService(org)
        cfg = LiveSessionConfig(organization_id=org)
        svc.apply_config_message(
            cfg,
            {
                "group_id": group_b,
                "camera_id": camera_id,
                "enable_liveness_detection": False,
            },
        )
        face = {
            "bbox": {"x": 80, "y": 40, "width": 120, "height": 120},
            "track_id": 7,
            "confidence": 0.97,
            "landmarks_5": [[115, 80], [165, 80], [140, 105], [122, 130], [158, 130]],
        }

        # 1) Red quality emits quality_warning and blocks marking attendance
        red_msgs = await svc.process_live_recognition(
            bright_img, [dict(face)], cfg, quality_report=red_report
        )
        assert any(
            m.get("type") == "cctv_alert" and m.get("alert_type") == "quality_warning"
            for m in red_msgs
        )
        assert not any(m.get("type") == "attendance_event" for m in red_msgs)

        # 2) Green quality + temporal observations of Section A student in Section B -> section_mismatch alert!
        msgs_g1 = await svc.process_live_recognition(
            bright_img, [dict(face)], cfg, quality_report=green_report
        )
        msgs2 = await svc.process_live_recognition(
            bright_img, [dict(face)], cfg, quality_report=green_report
        )
        combined = msgs_g1 + msgs2
        assert any(
            m.get("type") == "cctv_alert" and m.get("alert_type") == "section_mismatch"
            for m in combined
        )
        assert not any(m.get("type") == "attendance_event" for m in combined)

    asyncio.run(scenario())

    # Confirm alert recorded in /cctv/section-mismatches and faculty approve exception works
    mismatches = client.get("/cctv/section-mismatches", headers=headers).json()
    assert len(mismatches) == 1
    assert "A" in mismatches[0]["actual_section"]
    resolve = client.post(
        f"/cctv/section-mismatches/{mismatches[0]['id']}/resolve",
        headers=headers,
        json={
            "action": "approve_exception",
            "resolved_by": "Prof. Mehta",
            "notes": "Attending combined lecture",
            "exception_type": "combined_lecture",
        },
    )
    assert resolve.status_code == 200
    assert resolve.json()["status"] == "exception_approved"

    # Confirm finalization on red/offline camera never marks students absent
    client.post(
        f"/cctv/cameras/{camera_id}/simulate",
        headers=headers,
        json={"fault": "offline"},
    )
    m_b = _create_member(client, headers, group_b, "stu-b", "Bhavna SectionB")
    fin = client.post(
        f"/cctv/schedules/{schedule_id}/finalize",
        headers=headers,
        json={"verified_by": "Prof. Mehta"},
    )
    assert fin.status_code == 200
    fin_json = fin.json()
    assert fin_json["camera_blocked"] is True
    assert fin_json["marked_absent"] == 0
    assert fin_json["kept_pending"] >= 1


# ---------------------------------------------------------------------------
# 5. Camera Recovery, Backup Failover, Manual Fallback, Unknowns, HOD & Student Views
# ---------------------------------------------------------------------------


def test_camera_outage_backup_reconnect_and_unknown_reconciliation(biometrics_env):
    client = biometrics_env["client"]
    org = "smart-admin-org"
    headers = _headers(org)
    group_id = _create_group(client, headers, "ECE-A")
    stu1_res = client.post(
        "/attendance/members",
        headers=headers,
        json={"person_id": "ece-1", "name": "Kiran", "group_id": group_id, "role": "student"},
    )
    assert stu1_res.status_code == 200
    stu1 = stu1_res.json()

    # Backup camera (online in same classroom LH-105)
    backup_cam = client.post(
        "/cctv/cameras",
        headers=headers,
        json={
            "name": "LH-105 Backup Cam",
            "camera_code": "CAM-105-BK",
            "source_type": "simulated",
            "classroom": "LH-105",
            "department": "ECE",
            "assigned_group_id": group_id,
        },
    ).json()

    primary_cam = client.post(
        "/cctv/cameras",
        headers=headers,
        json={
            "name": "LH-105 Primary Cam",
            "camera_code": "CAM-105-PRI",
            "source_type": "simulated",
            "classroom": "LH-105",
            "department": "ECE",
            "assigned_group_id": group_id,
            "backup_camera_id": backup_cam["id"],
        },
    ).json()

    # Simulate outage -> backup used + outage log created
    sim = client.post(
        f"/cctv/cameras/{primary_cam['id']}/simulate",
        headers=headers,
        json={"fault": "offline"},
    )
    assert sim.status_code == 200
    assert sim.json()["recovery"]["backup_camera"]["id"] == backup_cam["id"]

    logs = client.get(f"/cctv/cameras/logs?camera_id={primary_cam['id']}", headers=headers).json()
    assert any(l["recovery_status"] == "backup_used" for l in logs)

    # Clear fault & reconnect -> status restored online & log resolved
    rec = client.post(
        f"/cctv/cameras/{primary_cam['id']}/reconnect",
        headers=headers,
        json={"clear_fault": True},
    )
    assert rec.status_code == 200
    assert rec.json()["reconnected"] is True

    # Create schedule and submit alternative faculty manual fallback
    sched = client.post(
        "/cctv/schedules",
        headers=headers,
        json={
            "group_id": group_id,
            "department": "ECE",
            "semester": "3",
            "section": "A",
            "subject_code": "EC301",
            "subject_name": "Signals",
            "faculty_name": "Dr. Verma",
            "classroom": "LH-105",
            "camera_id": primary_cam["id"],
        },
    ).json()

    fb = client.post(
        "/cctv/manual-fallback",
        headers=headers,
        json={
            "schedule_id": sched["id"],
            "verified_by": "Dr. Verma",
            "reason": "Primary camera briefly offline at start of class",
            "entries": [{"member_id": stu1["id"], "status": "present"}],
        },
    )
    assert fb.status_code == 200
    assert fb.json()["label"] == "Manually Verified"

    # HOD report shows 1 manually_verified
    hod = client.get("/cctv/hod/department-report?department=ECE", headers=headers)
    assert hod.status_code == 200
    assert hod.json()["totals"]["manually_verified"] == 1

    # Student self-view strictly scoped to stu1 & shows "Manually Verified"
    stu_view = client.get(f"/cctv/student/{stu1['id']}/attendance", headers=headers)
    assert stu_view.status_code == 200
    sv_json = stu_view.json()
    assert sv_json["student"]["member_id"] == stu1["id"]
    assert sv_json["records"][0]["verification_source"] == "Manually Verified"

    # Admin overview + audit logs work
    overview = client.get("/cctv/admin/overview", headers=headers)
    assert overview.status_code == 200
    assert overview.json()["cameras"]["total"] == 2
    audits = client.get("/cctv/audit-logs", headers=headers).json()
    assert any(a["action"] == "MANUAL_ATTENDANCE_FALLBACK_SUBMITTED" for a in audits)


def test_unknown_student_capture_and_register_action(biometrics_env):
    from database.session import AsyncSessionLocal
    from services.smart_attendance_engine import SmartAttendanceEngine

    client = biometrics_env["client"]
    org = "unknown-org"
    headers = _headers(org)
    group_id = _create_group(client, headers, "IT-A")

    async def insert_unknown():
        async with AsyncSessionLocal() as session:
            ok, buf = cv2.imencode(".jpg", _bright_textured_frame())
            assert ok
            rec = await SmartAttendanceEngine.record_unknown_student_detection(
                session,
                tracking_id="UNK-42-1",
                camera_id=None,
                schedule_id=None,
                group_id=group_id,
                classroom="IT-301",
                crop_bytes=bytes(buf),
                embedding=np.ones((128,), dtype=np.float32) * 0.1,
                confidence_best_guess=0.22,
                organization_id=org,
            )
            await session.commit()
            return rec.id

    unk_id = asyncio.run(insert_unknown())
    items = client.get("/cctv/unknown-detections?status=pending", headers=headers).json()
    assert len(items) == 1
    assert items[0]["snapshot_data_url"].startswith("data:image/jpeg;base64,")

    reg = client.post(
        f"/cctv/unknown-detections/{unk_id}/action",
        headers=headers,
        json={
            "action": "register_student",
            "resolved_by": "Admin-1",
            "name": "New Student Riya",
            "group_id": group_id,
            "registration_number": "IT2026-099",
            "department": "IT",
            "semester": "1",
            "section": "A",
            "enroll_captured_face": True,
        },
    )
    assert reg.status_code == 200, reg.text
    assert reg.json()["status"] == "verified"
    assert reg.json()["resolved_member_id"] is not None


def test_live_headcount_reflects_only_current_frame_faces(biometrics_env, monkeypatch):
    from core import lifespan
    from core.vision.image_quality import analyze_and_enhance_frame
    from services.live_stream_service import LiveSessionConfig, LiveStreamService

    client = biometrics_env["client"]
    org = "live-headcount-org"
    headers = _headers(org)
    group_id = _create_group(client, headers, "CSE-Live-Count")
    _create_member(client, headers, group_id, "stu-1", "Ashish")
    client.post(
        f"/attendance/groups/{group_id}/persons/stu-1/enroll-face",
        headers=headers,
        data={"metadata": _enroll_metadata()},
        files={"image": ("stu1.jpg", _make_image_bytes(), "image/jpeg")},
    )

    frame = _bright_textured_frame()
    _, green_report = analyze_and_enhance_frame(frame)

    async def scenario():
        svc = LiveStreamService(org)
        cfg = LiveSessionConfig(organization_id=org)
        svc.apply_config_message(
            cfg,
            {"group_id": group_id, "enable_liveness_detection": False},
        )

        # Simulate track_id churn (1 -> 2 -> 3) for a single registered person
        for tid in (1, 2, 3):
            face = {
                "bbox": {"x": 80, "y": 40, "width": 120, "height": 120},
                "track_id": tid,
                "confidence": 0.96,
                "landmarks_5": [[115, 80], [165, 80], [140, 105], [122, 130], [158, 130]],
            }
            await svc.process_live_recognition(
                frame, [face], cfg, quality_report=green_report
            )
            assert cfg.last_headcount_summary is not None
            assert cfg.last_headcount_summary["unique_detected"] == 1
            assert cfg.last_headcount_summary["successfully_identified"] == 1
            assert cfg.last_headcount_summary["unknown_individuals"] == 0

        # Frame with 1 known + 1 unknown person -> Detected 2 / Verified 1 / Unknown 1
        async def mixed_recognize(_image, faces_batch, **_kwargs):
            out = []
            for f in faces_batch:
                if f.get("track_id") == 3:
                    out.append({"person_id": "stu-1", "similarity": 0.91, "success": True})
                else:
                    out.append({"person_id": None, "similarity": 0.15, "success": False})
            return out

        monkeypatch.setattr(lifespan.face_recognizer, "recognize_faces", mixed_recognize)
        known_face = {
            "bbox": {"x": 80, "y": 40, "width": 120, "height": 120},
            "track_id": 3,
            "confidence": 0.96,
            "landmarks_5": [[115, 80], [165, 80], [140, 105], [122, 130], [158, 130]],
        }
        unknown_face = {
            "bbox": {"x": 180, "y": 40, "width": 110, "height": 110},
            "track_id": 99,
            "confidence": 0.94,
            "landmarks_5": [[210, 80], [260, 80], [235, 105], [218, 130], [252, 130]],
        }
        await svc.process_live_recognition(
            frame, [known_face, unknown_face], cfg, quality_report=green_report
        )
        assert cfg.last_headcount_summary["unique_detected"] == 2
        assert cfg.last_headcount_summary["successfully_identified"] == 1
        assert cfg.last_headcount_summary["unknown_individuals"] == 1

        # Empty frame -> immediately resets counts to 0
        await svc.process_live_recognition(frame, [], cfg, quality_report=green_report)
        assert cfg.last_headcount_summary["unique_detected"] == 0
        assert cfg.last_headcount_summary["successfully_identified"] == 0
        assert cfg.last_headcount_summary["unknown_individuals"] == 0

    asyncio.run(scenario())


def test_ip_stream_url_validation_and_candidates():
    from services.ip_stream_service import build_candidate_urls, validate_ip_stream_url

    assert validate_ip_stream_url("192.168.1.25:8080") == "http://192.168.1.25:8080"
    assert (
        validate_ip_stream_url("rtsp://192.168.1.25:554/h264_ulaw.sdp")
        == "rtsp://192.168.1.25:554/h264_ulaw.sdp"
    )

    assert build_candidate_urls("http://192.168.1.25:8080") == [
        "http://192.168.1.25:8080/video",
        "http://192.168.1.25:8080/videostream",
        "http://192.168.1.25:8080/mjpegfeed",
        "http://192.168.1.25:8080/videofeed",
        "http://192.168.1.25:8080/stream",
        "http://192.168.1.25:8080/shot.jpg",
        "http://192.168.1.25:8080",
    ]
    assert build_candidate_urls("rtsp://192.168.1.25:554/live") == [
        "rtsp://192.168.1.25:554/live"
    ]

    with pytest.raises(ValueError):
        validate_ip_stream_url("   ")
    with pytest.raises(ValueError):
        validate_ip_stream_url("ftp://192.168.1.25/video")
    with pytest.raises(ValueError):
        validate_ip_stream_url("http://192.168.1.25:8080/my stream")


def test_ip_stream_probe_and_mjpeg_routes(biometrics_env, monkeypatch):
    import api.routes.cctv as cctv_routes
    import services.ip_stream_service as ip_svc

    client = biometrics_env["client"]
    headers = _headers("ip-cam-org")

    bad_scheme = client.post(
        "/cctv/ip-stream/probe",
        headers=headers,
        json={"url": "ftp://192.168.1.50/video"},
    )
    assert bad_scheme.status_code == 400

    monkeypatch.setattr(
        ip_svc,
        "_check_tcp_reachable",
        lambda _url, timeout=2.5: (False, "Cannot reach 192.168.1.50:8080"),
    )
    unreachable = client.post(
        "/cctv/ip-stream/probe",
        headers=headers,
        json={"url": "192.168.1.50:8080"},
    )
    assert unreachable.status_code == 400
    assert "Cannot reach" in unreachable.json()["detail"]

    monkeypatch.setattr(
        ip_svc,
        "_check_tcp_reachable",
        lambda _url, timeout=2.5: (True, None),
    )
    monkeypatch.setattr(
        ip_svc,
        "_try_open_capture_frame",
        lambda candidate: (1280, 720, "mjpeg") if candidate.endswith("/video") else None,
    )
    ok_probe = client.post(
        "/cctv/ip-stream/probe",
        headers=headers,
        json={"url": "192.168.1.50:8080"},
    )
    assert ok_probe.status_code == 200
    body = ok_probe.json()
    assert body["ok"] is True
    assert body["resolved_url"] == "http://192.168.1.50:8080/video"
    assert body["width"] == 1280
    assert body["height"] == 720
    assert body["mode"] == "mjpeg"

    async def fake_iter_mjpeg_frames(_url, _is_disc, target_fps=20.0):
        yield b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: 4\r\n\r\nTEST\r\n"

    monkeypatch.setattr(cctv_routes, "iter_mjpeg_frames", fake_iter_mjpeg_frames)
    stream_resp = client.get(
        "/cctv/ip-stream/mjpeg",
        headers=headers,
        params={"url": "http://192.168.1.50:8080/video"},
    )
    assert stream_resp.status_code == 200
    assert stream_resp.headers.get("access-control-allow-origin") == "*"
    assert b"TEST" in stream_resp.content


# ---------------------------------------------------------------------------
# 11. Robust Mobile IP Camera Connection & Health Verification (10 Scenarios)
# ---------------------------------------------------------------------------


def test_ip_camera_scenarios_1_to_5_connectivity_and_subnet(monkeypatch):
    from services.ip_stream_service import (
        CameraHealthStatus,
        check_subnet_compatibility,
        verify_camera_connectivity,
    )
    import services.ip_stream_service as ip_svc

    # Scenario 4: Subnet mismatch detection
    monkeypatch.setattr(ip_svc, "get_local_host_ips", lambda: ["10.26.33.187"])
    subnet_check = check_subnet_compatibility("10.206.29.33")
    assert subnet_check["compatible"] is False
    assert subnet_check["error_type"] == "subnet_mismatch"
    assert "Host PC is on 10.26.33.187, but camera is on 10.206.29.33" in subnet_check["message"]

    # Cellular CLAT 192.0.0.x detection
    cellular_check = check_subnet_compatibility("192.0.0.4")
    assert cellular_check["compatible"] is False
    assert cellular_check["error_type"] == "cellular_clat"

    # Scenario 2: Incorrect / invalid IP address
    res_bad_ip = verify_camera_connectivity("http://192.0.0.4:8080")
    assert res_bad_ip["ok"] is False
    assert res_bad_ip["status"] == CameraHealthStatus.CAMERA_ERROR.value

    # Scenario 5: Camera server stopped (connection refused / unreachable)
    monkeypatch.setattr(
        ip_svc,
        "_check_tcp_reachable",
        lambda _url, timeout=2.0: (False, "Port 8080 closed or rejected connection"),
    )
    res_stopped = verify_camera_connectivity("http://192.168.1.100:8080")
    assert res_stopped["ok"] is False
    assert res_stopped["status"] == CameraHealthStatus.DISCONNECTED.value
    assert "Port 8080 closed" in res_stopped["error"]

    # Scenario 3: Incorrect streaming endpoint (reachable port, but no video stream)
    monkeypatch.setattr(
        ip_svc,
        "_check_tcp_reachable",
        lambda _url, timeout=2.0: (True, None),
    )
    monkeypatch.setattr(
        ip_svc,
        "_try_open_capture_frame",
        lambda _cand: None,
    )
    res_bad_endpoint = verify_camera_connectivity("http://192.168.1.100:8080/wrongpath")
    assert res_bad_endpoint["ok"] is False
    assert res_bad_endpoint["status"] == CameraHealthStatus.NO_FRAMES_RECEIVED.value

    # Scenario 1: Camera successfully connects
    monkeypatch.setattr(
        ip_svc,
        "_try_open_capture_frame",
        lambda cand: (1920, 1080, "mjpeg") if cand.endswith("/video") else None,
    )
    res_success = verify_camera_connectivity("http://192.168.1.100:8080")
    assert res_success["ok"] is True
    assert res_success["status"] == CameraHealthStatus.CONNECTED.value
    assert res_success["resolved_url"] == "http://192.168.1.100:8080/video"
    assert res_success["width"] == 1920
    assert res_success["height"] == 1080


def test_ip_camera_scenarios_6_to_10_health_reconnection_and_attendance_safety(monkeypatch):
    import time
    from services.ip_stream_service import (
        CameraHealthStatus,
        CameraStreamRegistry,
        IpCameraStreamWorker,
    )

    worker = IpCameraStreamWorker("http://192.168.1.120:8080/video", camera_id="cam_test_01")

    # Scenario 6 & 7: Reconnection state transitions
    worker.status = CameraHealthStatus.RECONNECTING
    worker.reconnect_attempts = 2
    assert worker.status == CameraHealthStatus.RECONNECTING
    assert worker.get_valid_attendance_frame() is None  # Safe: never mark attendance while reconnecting

    # Reconnection succeeds
    worker.status = CameraHealthStatus.CONNECTED
    worker.reconnect_attempts = 0
    diag = worker.get_diagnostics()
    assert diag["status"] == CameraHealthStatus.CONNECTED.value
    assert diag["reconnect_attempts"] == 0

    # Scenario 8: Frozen stream detection (STREAM_FROZEN)
    dummy_frame = np.full((120, 160, 3), 150, dtype=np.uint8)
    now = time.monotonic()
    assert worker._check_frame_frozen(dummy_frame, now) is False
    # Next frame identical after 3.5s elapsed
    assert worker._check_frame_frozen(dummy_frame, now + 3.5) is True
    worker._store_frame(dummy_frame, 12.0)
    worker.status = CameraHealthStatus.STREAM_FROZEN

    # Scenario 10: Attendance Safety Guard on frozen frames
    # get_valid_attendance_frame MUST return None so no attendance record is ever produced from frozen frames!
    assert worker.get_valid_attendance_frame() is None

    # Scenario 9: Low Frame Rate (LOW_FRAME_RATE)
    worker.fps = 4.2
    worker.status = CameraHealthStatus.LOW_FRAME_RATE
    diag_low = worker.get_diagnostics()
    assert diag_low["status"] == CameraHealthStatus.LOW_FRAME_RATE.value

    # Registry management: ensures no duplicate connections or memory leaks
    reg_worker = CameraStreamRegistry.get_or_create("http://192.168.1.120:8080/video")
    reg_worker_2 = CameraStreamRegistry.get_or_create("http://192.168.1.120:8080/video")
    assert reg_worker is reg_worker_2
    CameraStreamRegistry.stop("http://192.168.1.120:8080/video")

