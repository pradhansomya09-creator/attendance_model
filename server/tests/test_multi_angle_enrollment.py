"""Tests for guided 5-angle face enrollment, facial alignment overlay telemetry, and multi-angle recognition."""

from __future__ import annotations

import asyncio
import json

import cv2
import numpy as np
import pytest

from tests.test_api_biometrics import biometrics_env  # noqa: F401


def _textured_face_frame(brightness: float = 135.0, width: int = 320, height: int = 240) -> np.ndarray:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    for x in range(0, width, 20):
        val = int(np.clip(brightness * (1.5 if (x // 20) % 2 == 0 else 0.5), 0, 255))
        img[:, x:x+20] = (val, val, val)
    if brightness > 40:
        cv2.putText(img, "ROOM 101", (60, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 255, 255), 2)
        # Add sharp texture inside face region for high Laplacian variance
        for y in range(45, 195, 4):
            cv2.line(img, (95, y), (225, y), (140, 150, 160), 2)
        cv2.circle(img, (132, 100), 6, (0, 0, 0), -1)
        cv2.circle(img, (188, 100), 6, (0, 0, 0), -1)
        cv2.line(img, (140, 150), (180, 150), (40, 20, 20), 2)
    return img


def _landmarks_for_yaw(yaw_shift: float, cx: float = 160.0, cy: float = 120.0) -> list[list[float]]:
    """Build 5-point landmarks matching centered face with horizontal nose shift for pose tests."""
    return [
        [cx - 28.0, cy - 20.0],          # right eye (screen-left)
        [cx + 28.0, cy - 20.0],          # left eye (screen-right)
        [cx + yaw_shift, cy + 4.0],      # nose tip
        [cx - 18.0 + 0.3 * yaw_shift, cy + 32.0],
        [cx + 18.0 + 0.3 * yaw_shift, cy + 32.0],
    ]


def test_facial_guide_overlay_and_alignment_conditions():
    from core.vision.face_geometry import (
        ENROLLMENT_ANGLES,
        compute_facial_guide_overlay,
        evaluate_enrollment_alignment,
    )

    assert len(ENROLLMENT_ANGLES) == 5

    sharp_img = _textured_face_frame()
    frontal_face = {
        "bbox": {"x": 95, "y": 45, "width": 130, "height": 150},
        "confidence": 0.98,
        "landmarks_5": _landmarks_for_yaw(0.0),
    }

    overlay = compute_facial_guide_overlay(sharp_img, frontal_face)
    features = overlay["features"]
    for key in (
        "left_eye",
        "right_eye",
        "left_eyebrow",
        "right_eyebrow",
        "nose",
        "mouth",
        "left_ear",
        "right_ear",
        "face_outline",
    ):
        assert key in features, f"Missing overlay feature: {key}"
    assert len(features["face_outline"]) >= 12
    assert len(features["left_ear"]) >= 3 and len(features["right_ear"]) >= 3
    assert "horizontal" in overlay["axes"] and "vertical" in overlay["axes"]
    coords = overlay["coordinates"]
    assert "center_x" in coords and "center_y" in coords
    assert "offset_x" in coords and "offset_y" in coords
    assert "yaw" in coords and "pitch" in coords and "roll" in coords
    assert "landmarks" in coords and "forehead" in coords["landmarks"]

    # Ready states for each of the 5 target angles
    angle_shifts = {
        "front": 0.0,
        "slight_left": -10.5,
        "slight_right": 10.5,
        "left_profile": -22.0,
        "right_profile": 22.0,
    }
    for target_angle, shift in angle_shifts.items():
        face = {
            "bbox": {"x": 95, "y": 45, "width": 130, "height": 150},
            "confidence": 0.97,
            "landmarks_5": _landmarks_for_yaw(shift),
        }
        eval_res = evaluate_enrollment_alignment(sharp_img, [face], target_angle=target_angle)
        assert eval_res["ready"] is True, f"Expected ready for {target_angle}, got {eval_res}"
        assert eval_res["status"] == "ready"

    # Missing face
    missing = evaluate_enrollment_alignment(sharp_img, [], target_angle="front")
    assert missing["ready"] is False and missing["status"] == "missing"

    # Multiple faces
    multi = evaluate_enrollment_alignment(sharp_img, [frontal_face, frontal_face], target_angle="front")
    assert multi["ready"] is False and multi["status"] == "multiple_faces"

    # Off-center face
    off_center_face = {
        "bbox": {"x": 5, "y": 45, "width": 120, "height": 140},
        "confidence": 0.97,
        "landmarks_5": _landmarks_for_yaw(0.0, cx=65.0, cy=115.0),
    }
    off_center = evaluate_enrollment_alignment(sharp_img, [off_center_face], target_angle="front")
    assert off_center["ready"] is False and off_center["status"] == "off_center"
    assert "off-center" in off_center["guidance"].lower()

    # Poor lighting (very dark frame)
    dark_img = _textured_face_frame(brightness=15.0)
    dark_res = evaluate_enrollment_alignment(dark_img, [frontal_face], target_angle="front")
    assert dark_res["ready"] is False and dark_res["status"] == "poor_lighting"
    assert "dark" in dark_res["guidance"].lower()

    # Too blurry frame
    blur_img = cv2.GaussianBlur(sharp_img, (31, 31), 0)
    blur_res = evaluate_enrollment_alignment(blur_img, [frontal_face], target_angle="front")
    assert blur_res["ready"] is False and blur_res["status"] == "too_blurry"
    assert "blurry" in blur_res["guidance"].lower()

    # Wrong angle (looking straight ahead when left_profile requested)
    wrong_angle = evaluate_enrollment_alignment(sharp_img, [frontal_face], target_angle="left_profile")
    assert wrong_angle["ready"] is False and wrong_angle["status"] == "adjust_angle"


def test_detect_endpoint_returns_optional_alignment(biometrics_env, monkeypatch):
    import api.routes.detection as det_route

    sharp_img = _textured_face_frame()
    ok, encoded = cv2.imencode(".jpg", sharp_img)
    assert ok

    async def fake_detect(*_args, **_kwargs):
        return [
            {
                "bbox": {"x": 95.0, "y": 45.0, "width": 130.0, "height": 150.0},
                "confidence": 0.98,
                "landmarks_5": _landmarks_for_yaw(0.0),
                "track_id": -1,
            }
        ]

    monkeypatch.setattr(det_route, "process_face_detection", fake_detect)
    client = biometrics_env["client"]
    auth_headers = {"X-Facenox-Token": "biometrics-token"}

    # Default /detect omits alignment payload
    plain = client.post(
        "/detect",
        headers=auth_headers,
        files={"image": ("face.jpg", encoded.tobytes(), "image/jpeg")},
        data={"model_type": "face_detector"},
    )
    assert plain.status_code == 200
    assert plain.json()["alignment"] is None

    # Alignment telemetry enabled
    with_align = client.post(
        "/detect",
        headers=auth_headers,
        files={"image": ("face.jpg", encoded.tobytes(), "image/jpeg")},
        data={
            "model_type": "face_detector",
            "include_alignment": "true",
            "target_angle": "front",
        },
    )
    assert with_align.status_code == 200
    payload = with_align.json()
    assert payload["alignment"]["ready"] is True
    assert payload["alignment"]["overlay"]["features"]["left_eyebrow"]
    assert payload["alignment"]["overlay"]["features"]["left_ear"]
    assert payload["alignment"]["overlay"]["coordinates"]["center_x"] > 0


def test_multi_angle_recognizer_encryption_consistency_and_pose_recall(biometrics_env):
    from pathlib import Path
    from core.models.face_recognizer.recognizer import FaceRecognizer
    from database.face import FaceDatabaseManager

    async def scenario():
        recognizer = FaceRecognizer.__new__(FaceRecognizer)
        recognizer.legacy_sqlite_path = Path("faces.db")
        recognizer.db_manager = FaceDatabaseManager()
        recognizer._db_managers = {}
        recognizer._persons_cache = {}
        recognizer._template_bank_cache = {}
        recognizer._cache_timestamp = {}
        recognizer._cache_ttl = 60.0
        recognizer._cache_locks = {}
        recognizer.similarity_threshold = 0.45

        # Create 5 realistic same-person embeddings spanning 5 head poses
        base = np.zeros(512, dtype=np.float32)
        base[0] = 1.0
        pose_vectors = {}
        for idx, angle in enumerate(
            ("front", "slight_left", "slight_right", "left_profile", "right_profile")
        ):
            vec = base.copy()
            vec[idx + 1] = 0.8 if "profile" in angle else 0.4
            vec = vec / np.linalg.norm(vec)
            pose_vectors[angle] = vec

        angle_order = ["front", "slight_left", "slight_right", "left_profile", "right_profile"]
        call_counter = {"i": 0}

        async def mock_extract(_image, _face_data):
            angle = angle_order[call_counter["i"] % 5]
            call_counter["i"] += 1
            return [pose_vectors[angle]]

        recognizer._extract_embeddings = mock_extract

        dummy_img = _textured_face_frame()
        samples = [
            {
                "angle": angle,
                "image": dummy_img,
                "landmarks_5": _landmarks_for_yaw(0.0),
                "yaw": 0.0,
                "pitch": 0.0,
                "clarity_score": 0.8,
            }
            for angle in angle_order
        ]

        # Reject < 5 captures
        too_few = await recognizer.enroll_person_multi_angle("person-1", samples[:4], "org-ma")
        assert too_few["success"] is False

        # Consistent 5 angles succeed
        ok_res = await recognizer.enroll_person_multi_angle("person-1", samples, "org-ma")
        assert ok_res["success"] is True
        assert ok_res["angle_count"] == 5

        mgr = recognizer._get_db_manager("org-ma")
        # Both fused centroid in `faces` and 5 encrypted rows in `face_angle_templates` exist
        fused = await mgr.get_person("person-1")
        assert fused is not None and fused.shape == (512,)
        stored_angles = await mgr.get_angle_templates("person-1")
        assert len(stored_angles) == 5
        assert {row["angle"] for row in stored_angles} == set(angle_order)

        # Verify raw template bytes in DB are encrypted (not equal to raw float32 bytes)
        from database.session import AsyncSessionLocal
        from database.repository import FaceRepository

        async with AsyncSessionLocal() as session:
            repo = FaceRepository(session, "org-ma")
            raw_rows = await repo.get_angle_templates_by_person("person-1")
            assert len(raw_rows) == 5
            for r in raw_rows:
                assert r.embedding != pose_vectors[r.angle].astype(np.float32).tobytes()

        # Verify pose recall: query strictly resembling left_profile matches strongly via template bank
        async def query_profile(_image, _face_data):
            return [pose_vectors["left_profile"]]

        recognizer._extract_embeddings = query_profile
        rec = await recognizer.recognize_face(
            dummy_img, _landmarks_for_yaw(-22.0), organization_id="org-ma"
        )
        assert rec["success"] is True
        assert rec["person_id"] == "person-1"
        assert rec["similarity"] >= 0.99

        # Verify mismatched person across 5 angles is rejected
        imposter = np.zeros(512, dtype=np.float32)
        imposter[99] = 1.0
        bad_idx = {"i": 0}

        async def mismatched_extract(_image, _face_data):
            i = bad_idx["i"]
            bad_idx["i"] += 1
            return [imposter if i == 4 else pose_vectors[angle_order[i]]]

        recognizer._extract_embeddings = mismatched_extract
        mismatch_res = await recognizer.enroll_person_multi_angle("person-2", samples, "org-ma")
        assert mismatch_res["success"] is False
        assert "does not match the same person" in mismatch_res["error"]

        # Removing person removes both `faces` and `face_angle_templates`
        rm_res = await recognizer.remove_person("person-1", "org-ma")
        assert rm_res["success"] is True
        assert await mgr.get_angle_templates("person-1") == []

    asyncio.run(scenario())


def test_enroll_multi_angle_http_route_requires_five_distinct_angles(biometrics_env, monkeypatch):
    import hooks

    client = biometrics_env["client"]
    headers = {
        "X-Facenox-Token": "biometrics-token",
        "X-Facenox-Org-Id": "org-route",
    }

    grp = client.post("/attendance/groups", headers=headers, json={"name": "CS-A"}).json()
    member = client.post(
        "/attendance/members",
        headers=headers,
        json={"group_id": grp["id"], "name": "Priya"},
    ).json()

    sharp_img = _textured_face_frame()
    ok, encoded = cv2.imencode(".jpg", sharp_img)
    assert ok
    jpg_bytes = encoded.tobytes()

    shifts = {
        "front": 0.0,
        "slight_left": -10.5,
        "slight_right": 10.5,
        "left_profile": -22.0,
        "right_profile": 22.0,
    }
    state = {"idx": 0}
    angles = list(shifts.keys())

    async def fake_detect(*_args, **_kwargs):
        ang = angles[state["idx"] % len(angles)]
        state["idx"] += 1
        return [
            {
                "bbox": {"x": 95.0, "y": 45.0, "width": 130.0, "height": 150.0},
                "confidence": 0.98,
                "landmarks_5": _landmarks_for_yaw(shifts[ang]),
            }
        ]

    monkeypatch.setattr(hooks, "process_face_detection", fake_detect)

    async def fake_multi_angle(person_id, samples, organization_id=None, **_kwargs):
        return {
            "success": True,
            "person_id": person_id,
            "database_saved": True,
            "angles_enrolled": [s["angle"] for s in samples],
            "angle_count": len(samples),
            "total_persons": 1,
        }

    monkeypatch.setattr(
        biometrics_env["recognizer"], "enroll_person_multi_angle", fake_multi_angle, raising=False
    )

    # Fewer than 5 images -> rejected cleanly (400)
    too_few = client.post(
        f"/attendance/groups/{grp['id']}/persons/{member['person_id']}/enroll-multi-angle",
        headers=headers,
        files=[("images", (f"{a}.jpg", jpg_bytes, "image/jpeg")) for a in angles[:4]],
        data={"metadata": json.dumps({"captures": [{"angle": a} for a in angles[:4]]})},
    )
    assert too_few.status_code == 400

    # 5 valid distinct angle images -> enrolled cleanly
    state["idx"] = 0
    ok_resp = client.post(
        f"/attendance/groups/{grp['id']}/persons/{member['person_id']}/enroll-multi-angle",
        headers=headers,
        files=[("images", (f"{a}.jpg", jpg_bytes, "image/jpeg")) for a in angles],
        data={"metadata": json.dumps({"captures": [{"angle": a} for a in angles]})},
    )
    assert ok_resp.status_code == 200
    body = ok_resp.json()
    assert body["success"] is True
    assert body["angle_count"] == 5
    assert body["angles_enrolled"] == angles

