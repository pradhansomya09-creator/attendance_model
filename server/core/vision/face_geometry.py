"""Facial alignment overlay geometry and guided multi-angle enrollment validation."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from core.vision.head_pose import (
    _extract_landmark_points,
    estimate_head_pose_and_occlusion,
)
from core.vision.image_quality import ImageQualityReport, analyze_frame_quality

ENROLLMENT_ANGLES: Tuple[str, ...] = (
    "front",
    "slight_left",
    "slight_right",
    "left_profile",
    "right_profile",
)

ANGLE_STEP_SPECS: Dict[str, Dict[str, Any]] = {
    "front": {
        "angle": "front",
        "label": "Forward Facing",
        "short_label": "Front",
        "instruction": "Look straight ahead into the center oval.",
        "yaw_min": -10.5,
        "yaw_max": 10.5,
        "max_pitch": 18.0,
        "max_roll": 18.0,
        "target_yaw": 0.0,
    },
    "slight_left": {
        "angle": "slight_left",
        "label": "Slight Left Turn",
        "short_label": "Slight Left",
        "instruction": "Turn your head slightly to the left (~15 deg).",
        "yaw_min": -25.0,
        "yaw_max": -7.5,
        "max_pitch": 20.0,
        "max_roll": 20.0,
        "target_yaw": -15.0,
    },
    "slight_right": {
        "angle": "slight_right",
        "label": "Slight Right Turn",
        "short_label": "Slight Right",
        "instruction": "Turn your head slightly to the right (~15 deg).",
        "yaw_min": 7.5,
        "yaw_max": 25.0,
        "max_pitch": 20.0,
        "max_roll": 20.0,
        "target_yaw": 15.0,
    },
    "left_profile": {
        "angle": "left_profile",
        "label": "Left Profile",
        "short_label": "Left Profile",
        "instruction": "Turn further left for a left profile view (~25+ deg).",
        "yaw_min": -68.0,
        "yaw_max": -18.0,
        "max_pitch": 22.0,
        "max_roll": 22.0,
        "target_yaw": -30.0,
    },
    "right_profile": {
        "angle": "right_profile",
        "label": "Right Profile",
        "short_label": "Right Profile",
        "instruction": "Turn further right for a right profile view (~25+ deg).",
        "yaw_min": 18.0,
        "yaw_max": 68.0,
        "max_pitch": 22.0,
        "max_roll": 22.0,
        "target_yaw": 30.0,
    },
}

_ANGLE_ALIASES: Dict[str, str] = {
    "front": "front",
    "forward": "front",
    "forward_facing": "front",
    "center": "front",
    "slight_left": "slight_left",
    "slight left": "slight_left",
    "left_slight": "slight_left",
    "slight_right": "slight_right",
    "slight right": "slight_right",
    "right_slight": "slight_right",
    "left_profile": "left_profile",
    "left profile": "left_profile",
    "profile_left": "left_profile",
    "right_profile": "right_profile",
    "right profile": "right_profile",
    "profile_right": "right_profile",
}


def normalize_angle_key(angle: Optional[str]) -> Optional[str]:
    """Normalize an incoming angle label or alias to a canonical enrollment angle key."""
    if not angle:
        return None
    cleaned = angle.strip().lower().replace("-", "_")
    if cleaned in ANGLE_STEP_SPECS:
        return cleaned
    return _ANGLE_ALIASES.get(cleaned)


def classify_detected_angle(yaw: float, pitch: float) -> str:
    """Classify head yaw/pitch into the nearest canonical enrollment angle."""
    if abs(pitch) > 26.0 or abs(yaw) > 70.0:
        return "out_of_range"
    if -10.0 <= yaw <= 10.0:
        return "front"
    if -22.0 <= yaw < -10.0:
        return "slight_left"
    if 10.0 < yaw <= 22.0:
        return "slight_right"
    if yaw < -22.0:
        return "left_profile"
    return "right_profile"


def _round_pt(x: float, y: float, img_w: int, img_h: int) -> Dict[str, float]:
    cx = max(0.0, min(float(img_w), float(x)))
    cy = max(0.0, min(float(img_h), float(y)))
    return {"x": round(cx, 1), "y": round(cy, 1)}


def _rotate_offset(
    dx: float, dy: float, cos_r: float, sin_r: float
) -> Tuple[float, float]:
    return (dx * cos_r - dy * sin_r, dx * sin_r + dy * cos_r)


def _normalize_bbox(bbox: Any) -> Dict[str, float]:
    """Normalize bounding box to dict with x, y, width, height whether given as list or dict."""
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return {
            "x": float(bbox[0]),
            "y": float(bbox[1]),
            "width": float(bbox[2]),
            "height": float(bbox[3]),
        }
    if isinstance(bbox, dict):
        return {
            "x": float(bbox.get("x", 0.0)),
            "y": float(bbox.get("y", 0.0)),
            "width": float(bbox.get("width", 0.0)),
            "height": float(bbox.get("height", 0.0)),
        }
    return {"x": 0.0, "y": 0.0, "width": 0.0, "height": 0.0}


def compute_facial_guide_overlay(
    image: np.ndarray,
    face: Dict[str, Any],
    *,
    mirrored: bool = False,
    quality: Optional[ImageQualityReport] = None,
) -> Dict[str, Any]:
    """Build smooth landmark contours (eyes, eyebrows, nose, mouth, ears, outline) and coordinates."""
    h, w = image.shape[:2] if image is not None and image.size > 0 else (480, 640)
    norm = _normalize_bbox(face.get("bbox"))
    bx = norm["x"]
    by = norm["y"]
    bw = max(1.0, norm["width"])
    bh = max(1.0, norm["height"])

    pose = estimate_head_pose_and_occlusion(
        image, face, max_yaw_deg=65.0, max_pitch_deg=35.0
    )
    q = quality or analyze_frame_quality(image)

    raw_pts = _extract_landmark_points(face)
    if len(raw_pts) >= 5:
        pts = [
            (float(raw_pts[i].get("x", 0.0)), float(raw_pts[i].get("y", 0.0)))
            for i in range(5)
        ]
    else:
        pts = [
            (bx + 0.30 * bw, by + 0.38 * bh),
            (bx + 0.70 * bw, by + 0.38 * bh),
            (bx + 0.50 * bw, by + 0.56 * bh),
            (bx + 0.35 * bw, by + 0.75 * bh),
            (bx + 0.65 * bw, by + 0.75 * bh),
        ]

    def map_x(val_x: float) -> float:
        return (float(w) - val_x) if mirrored else val_x

    mapped_pts = [(map_x(px), py) for px, py in pts]
    box_x = (float(w) - (bx + bw)) if mirrored else bx

    # Order screen-left / screen-right pairs consistently after optional mirroring
    eye_a, eye_b, nose_pt, mouth_a, mouth_b = mapped_pts
    screen_left_eye, screen_right_eye = (
        (eye_a, eye_b) if eye_a[0] <= eye_b[0] else (eye_b, eye_a)
    )
    screen_left_mouth, screen_right_mouth = (
        (mouth_a, mouth_b) if mouth_a[0] <= mouth_b[0] else (mouth_b, mouth_a)
    )

    eye_mid_x = 0.5 * (screen_left_eye[0] + screen_right_eye[0])
    eye_mid_y = 0.5 * (screen_left_eye[1] + screen_right_eye[1])
    mouth_mid_x = 0.5 * (screen_left_mouth[0] + screen_right_mouth[0])
    mouth_mid_y = 0.5 * (screen_left_mouth[1] + screen_right_mouth[1])

    dx_eye = screen_right_eye[0] - screen_left_eye[0]
    dy_eye = screen_right_eye[1] - screen_left_eye[1]
    eye_dist = max(10.0, float(math.hypot(dx_eye, dy_eye)))
    roll_rad = math.atan2(dy_eye, max(1.0, dx_eye))
    cos_r = math.cos(roll_rad)
    sin_r = math.sin(roll_rad)

    display_yaw = -float(pose.yaw) if mirrored else float(pose.yaw)
    display_pitch = float(pose.pitch)
    display_roll = float(math.degrees(roll_rad))

    face_cx = box_x + 0.5 * bw
    face_cy = by + 0.5 * bh

    def build_eye_contour(cx: float, cy: float) -> List[Dict[str, float]]:
        rx = 0.24 * eye_dist
        ry = 0.11 * eye_dist
        offsets = [
            (-rx, 0.0),
            (-0.45 * rx, -ry),
            (0.45 * rx, -ry),
            (rx, 0.0),
            (0.45 * rx, ry * 0.85),
            (-0.45 * rx, ry * 0.85),
        ]
        contour = []
        for ox, oy in offsets:
            rx_o, ry_o = _rotate_offset(ox, oy, cos_r, sin_r)
            contour.append(_round_pt(cx + rx_o, cy + ry_o, w, h))
        return contour

    def build_brow(cx: float, cy: float, is_left_screen: bool) -> List[Dict[str, float]]:
        span = 0.34 * eye_dist
        lift = 0.25 * eye_dist
        arch = 0.06 * eye_dist
        # Slight inner-to-outer arch
        sign = -1.0 if is_left_screen else 1.0
        raw_offsets = [
            (-span, -lift * 0.88),
            (-0.35 * span, -lift - arch),
            (0.35 * span, -lift - (0.6 * arch if sign > 0 else 1.1 * arch)),
            (span, -lift * 0.78),
        ]
        if is_left_screen:
            raw_offsets = [
                (-span, -lift * 0.78),
                (-0.35 * span, -lift - 1.1 * arch),
                (0.35 * span, -lift - arch),
                (span, -lift * 0.88),
            ]
        brow_pts = []
        for ox, oy in raw_offsets:
            rx_o, ry_o = _rotate_offset(ox, oy, cos_r, sin_r)
            brow_pts.append(_round_pt(cx + rx_o, cy + ry_o, w, h))
        return brow_pts

    # Nose bridge + tip + alar base
    nose_wing = 0.16 * eye_dist
    nose_up_x, nose_up_y = _rotate_offset(0.0, -0.05 * bh, cos_r, sin_r)
    nose_lw_x, nose_lw_y = _rotate_offset(-nose_wing, 0.02 * bh, cos_r, sin_r)
    nose_rw_x, nose_rw_y = _rotate_offset(nose_wing, 0.02 * bh, cos_r, sin_r)
    nose_bridge = [
        _round_pt(eye_mid_x + nose_up_x, eye_mid_y + nose_up_y, w, h),
        _round_pt(0.5 * (eye_mid_x + nose_pt[0]), 0.5 * (eye_mid_y + nose_pt[1]), w, h),
        _round_pt(nose_pt[0], nose_pt[1], w, h),
    ]
    nose_base = [
        _round_pt(nose_pt[0] + nose_lw_x, nose_pt[1] + nose_lw_y, w, h),
        _round_pt(nose_pt[0], nose_pt[1], w, h),
        _round_pt(nose_pt[0] + nose_rw_x, nose_pt[1] + nose_rw_y, w, h),
    ]

    # Mouth closed/smiling contour anchored to detected mouth corners
    mouth_width = max(10.0, math.hypot(screen_right_mouth[0] - screen_left_mouth[0], screen_right_mouth[1] - screen_left_mouth[1]))
    lip_h = 0.18 * mouth_width
    top_cupid_x, top_cupid_y = _rotate_offset(0.0, -lip_h, cos_r, sin_r)
    bot_lip_x, bot_lip_y = _rotate_offset(0.0, lip_h * 1.15, cos_r, sin_r)
    mouth_contour = [
        _round_pt(screen_left_mouth[0], screen_left_mouth[1], w, h),
        _round_pt(0.35 * screen_left_mouth[0] + 0.65 * mouth_mid_x + 0.6 * top_cupid_x, 0.35 * screen_left_mouth[1] + 0.65 * mouth_mid_y + 0.85 * top_cupid_y, w, h),
        _round_pt(mouth_mid_x + top_cupid_x, mouth_mid_y + top_cupid_y, w, h),
        _round_pt(0.35 * screen_right_mouth[0] + 0.65 * mouth_mid_x + 0.6 * top_cupid_x, 0.35 * screen_right_mouth[1] + 0.65 * mouth_mid_y + 0.85 * top_cupid_y, w, h),
        _round_pt(screen_right_mouth[0], screen_right_mouth[1], w, h),
        _round_pt(0.35 * screen_right_mouth[0] + 0.65 * mouth_mid_x + 0.6 * bot_lip_x, 0.35 * screen_right_mouth[1] + 0.65 * mouth_mid_y + 0.85 * bot_lip_y, w, h),
        _round_pt(mouth_mid_x + bot_lip_x, mouth_mid_y + bot_lip_y, w, h),
        _round_pt(0.35 * screen_left_mouth[0] + 0.65 * mouth_mid_x + 0.6 * bot_lip_x, 0.35 * screen_left_mouth[1] + 0.65 * mouth_mid_y + 0.85 * bot_lip_y, w, h),
    ]

    # Face outline oval & ear contours scaled smoothly with bbox + yaw foreshortening
    yaw_ratio = max(-0.55, min(0.55, display_yaw / 60.0))
    left_rx = bw * 0.50 * (1.0 + 0.25 * max(0.0, yaw_ratio) - 0.18 * max(0.0, -yaw_ratio))
    right_rx = bw * 0.50 * (1.0 + 0.25 * max(0.0, -yaw_ratio) - 0.18 * max(0.0, yaw_ratio))
    top_ry = bh * 0.52
    bot_ry = bh * 0.50

    face_outline: List[Dict[str, float]] = []
    num_outline = 16
    for idx in range(num_outline):
        theta = (2.0 * math.pi * idx) / num_outline
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        rx = right_rx if cos_t >= 0 else left_rx
        ry = bot_ry if sin_t >= 0 else top_ry
        # Slightly taper lower jaw for anatomical oval
        taper = 0.88 if sin_t > 0.35 else 1.0
        ox, oy = _rotate_offset(cos_t * rx * taper, sin_t * ry, cos_r, sin_r)
        face_outline.append(_round_pt(face_cx + ox, face_cy + oy, w, h))

    def build_ear(side: int) -> List[Dict[str, float]]:
        # side: -1 = screen-left ear, +1 = screen-right ear
        rx_edge = (-left_rx) if side < 0 else right_rx
        ear_out = 0.08 * bw * side
        offsets = [
            (rx_edge * 0.96, -0.10 * bh),
            (rx_edge + ear_out, -0.05 * bh),
            (rx_edge + ear_out * 0.92, 0.10 * bh),
            (rx_edge * 0.92, 0.18 * bh),
        ]
        ear_pts = []
        for ox, oy in offsets:
            rx_o, ry_o = _rotate_offset(ox, oy, cos_r, sin_r)
            ear_pts.append(_round_pt(face_cx + rx_o, face_cy + ry_o, w, h))
        return ear_pts

    left_ear = build_ear(-1)
    right_ear = build_ear(1)

    # Horizontal and vertical reference axes anchored to the detected face center & tilt
    hx1, hy1 = _rotate_offset(-0.58 * bw, 0.0, cos_r, sin_r)
    hx2, hy2 = _rotate_offset(0.58 * bw, 0.0, cos_r, sin_r)
    vx1, vy1 = _rotate_offset(0.0, -0.56 * bh, cos_r, sin_r)
    vx2, vy2 = _rotate_offset(0.0, 0.56 * bh, cos_r, sin_r)

    top_fx, top_fy = _rotate_offset(0.0, -top_ry, cos_r, sin_r)
    chin_x, chin_y = _rotate_offset(0.0, bot_ry, cos_r, sin_r)

    norm_cx = face_cx / max(1.0, float(w))
    norm_cy = face_cy / max(1.0, float(h))

    return {
        "image_width": int(w),
        "image_height": int(h),
        "mirrored": bool(mirrored),
        "bbox": {
            "x": round(box_x, 1),
            "y": round(by, 1),
            "width": round(bw, 1),
            "height": round(bh, 1),
        },
        "features": {
            "left_eye": {
                "center": _round_pt(screen_left_eye[0], screen_left_eye[1], w, h),
                "contour": build_eye_contour(screen_left_eye[0], screen_left_eye[1]),
            },
            "right_eye": {
                "center": _round_pt(screen_right_eye[0], screen_right_eye[1], w, h),
                "contour": build_eye_contour(screen_right_eye[0], screen_right_eye[1]),
            },
            "left_eyebrow": build_brow(screen_left_eye[0], screen_left_eye[1], True),
            "right_eyebrow": build_brow(screen_right_eye[0], screen_right_eye[1], False),
            "nose": {
                "tip": _round_pt(nose_pt[0], nose_pt[1], w, h),
                "bridge": nose_bridge,
                "base": nose_base,
            },
            "mouth": {
                "left": _round_pt(screen_left_mouth[0], screen_left_mouth[1], w, h),
                "right": _round_pt(screen_right_mouth[0], screen_right_mouth[1], w, h),
                "center": _round_pt(mouth_mid_x, mouth_mid_y, w, h),
                "contour": mouth_contour,
            },
            "left_ear": left_ear,
            "right_ear": right_ear,
            "face_outline": face_outline,
        },
        "axes": {
            "horizontal": {
                "x1": round(face_cx + hx1, 1),
                "y1": round(eye_mid_y + hy1, 1),
                "x2": round(face_cx + hx2, 1),
                "y2": round(eye_mid_y + hy2, 1),
                "mid_x": round(face_cx, 1),
                "mid_y": round(eye_mid_y, 1),
            },
            "vertical": {
                "x1": round(eye_mid_x + vx1, 1),
                "y1": round(face_cy + vy1, 1),
                "x2": round(eye_mid_x + vx2, 1),
                "y2": round(face_cy + vy2, 1),
                "mid_x": round(eye_mid_x, 1),
                "mid_y": round(face_cy, 1),
            },
        },
        "coordinates": {
            "center_x": round(face_cx, 1),
            "center_y": round(face_cy, 1),
            "norm_x": round(norm_cx, 4),
            "norm_y": round(norm_cy, 4),
            "offset_x": round(norm_cx - 0.5, 4),
            "offset_y": round(norm_cy - 0.5, 4),
            "face_width_ratio": round(bw / max(1.0, float(w)), 4),
            "face_height_ratio": round(bh / max(1.0, float(h)), 4),
            "yaw": round(display_yaw, 2),
            "pitch": round(display_pitch, 2),
            "roll": round(display_roll, 2),
            "clarity_score": round(float(pose.clarity_score), 3),
            "brightness": round(float(q.brightness), 1),
            "sharpness": round(float(q.sharpness), 1),
            "landmarks": {
                "left_eye": _round_pt(screen_left_eye[0], screen_left_eye[1], w, h),
                "right_eye": _round_pt(screen_right_eye[0], screen_right_eye[1], w, h),
                "nose": _round_pt(nose_pt[0], nose_pt[1], w, h),
                "left_mouth": _round_pt(screen_left_mouth[0], screen_left_mouth[1], w, h),
                "right_mouth": _round_pt(screen_right_mouth[0], screen_right_mouth[1], w, h),
                "eye_midpoint": _round_pt(eye_mid_x, eye_mid_y, w, h),
                "mouth_midpoint": _round_pt(mouth_mid_x, mouth_mid_y, w, h),
                "forehead": _round_pt(face_cx + top_fx, face_cy + top_fy, w, h),
                "chin": _round_pt(face_cx + chin_x, face_cy + chin_y, w, h),
                "left_ear": left_ear[1],
                "right_ear": right_ear[1],
            },
        },
        "occlusion_suspected": bool(pose.occlusion_suspected),
    }


def evaluate_enrollment_alignment(
    image: np.ndarray,
    faces: List[Dict[str, Any]],
    target_angle: Optional[str] = None,
    *,
    mirrored: bool = False,
) -> Dict[str, Any]:
    """Evaluate frame readiness, lighting, blur, centering, and target angle match for enrollment."""
    normalized_target = normalize_angle_key(target_angle)
    quality = analyze_frame_quality(image)
    h, w = image.shape[:2] if image is not None and image.size > 0 else (480, 640)

    def _base_payload(
        status: str,
        ready: bool,
        guidance: str,
        issues: List[str],
        overlay: Optional[Dict[str, Any]] = None,
        angle_detected: Optional[str] = None,
    ) -> Dict[str, Any]:
        coords = (overlay or {}).get("coordinates") or {}
        metrics = {
            "brightness": round(float(quality.brightness), 1),
            "sharpness": round(float(quality.sharpness), 1),
            "quality_status": quality.status,
            "quality_score": round(float(quality.score), 3),
            "clarity_score": coords.get("clarity_score", 0.0),
            "yaw": coords.get("yaw", 0.0),
            "pitch": coords.get("pitch", 0.0),
            "roll": coords.get("roll", 0.0),
            "offset_x": coords.get("offset_x", 0.0),
            "offset_y": coords.get("offset_y", 0.0),
            "face_height_ratio": coords.get("face_height_ratio", 0.0),
        }
        return {
            "status": status,
            "ready": ready,
            "guidance": guidance,
            "quality_issues": issues,
            "target_angle": normalized_target,
            "angle_detected": angle_detected,
            "metrics": metrics,
            "overlay": overlay,
        }

    # Global lighting check even when face is missing
    lighting_issues: List[str] = []
    lighting_hint = ""
    if quality.brightness < 48.0 or quality.underexposed_ratio > 0.55:
        lighting_issues.append("poor_lighting_dark")
        lighting_hint = "Room is too dark. Increase front lighting on your face."
    elif quality.overexposed_ratio > 0.45 or quality.brightness > 228.0:
        lighting_issues.append("poor_lighting_glare")
        lighting_hint = "Strong glare or overexposure detected. Reduce direct backlight."
    elif quality.obstruction_score >= 0.45 or quality.haze_score >= 0.55:
        lighting_issues.append("camera_obstructed_or_hazy")
        lighting_hint = "Camera view looks hazy or obstructed. Clean the lens."

    if not faces:
        issues = ["face_missing", *lighting_issues]
        msg = (
            lighting_hint
            if lighting_issues
            else "No face detected. Position your face inside the alignment oval."
        )
        return _base_payload("missing", False, msg, issues, overlay=None)

    # Use largest detected face for overlay rendering
    primary_face = max(
        faces,
        key=lambda f: _normalize_bbox(f.get("bbox"))["width"]
        * _normalize_bbox(f.get("bbox"))["height"],
    )
    overlay = compute_facial_guide_overlay(
        image, primary_face, mirrored=mirrored, quality=quality
    )
    coords = overlay["coordinates"]
    yaw = float(coords["yaw"])
    pitch = float(coords["pitch"])
    roll = float(coords["roll"])
    clarity_score = float(coords["clarity_score"])
    offset_x = float(coords["offset_x"])
    offset_y = float(coords["offset_y"])
    height_ratio = float(coords["face_height_ratio"])
    angle_detected = classify_detected_angle(yaw, pitch)

    if len(faces) > 1:
        return _base_payload(
            "multiple_faces",
            False,
            "Multiple faces detected. Ensure only one person is visible in the frame.",
            ["multiple_faces"],
            overlay=overlay,
            angle_detected=angle_detected,
        )

    issues: List[str] = list(lighting_issues)
    if height_ratio < 0.20:
        issues.append("too_far")
    elif height_ratio > 0.88:
        issues.append("too_close")

    if abs(offset_x) > 0.20 or abs(offset_y) > 0.22:
        issues.append("off_center")

    if clarity_score < 0.22 or quality.sharpness < 18.0:
        issues.append("too_blurry")

    if overlay.get("occlusion_suspected"):
        issues.append("occluded")

    if abs(roll) > 22.0:
        issues.append("head_tilted")

    # Return highest-priority corrective guidance
    if lighting_issues:
        return _base_payload(
            "poor_lighting",
            False,
            lighting_hint,
            issues,
            overlay=overlay,
            angle_detected=angle_detected,
        )

    if "too_far" in issues:
        return _base_payload(
            "too_far",
            False,
            "Face is too small. Move closer so your face fills the guide oval.",
            issues,
            overlay=overlay,
            angle_detected=angle_detected,
        )

    if "too_close" in issues:
        return _base_payload(
            "too_close",
            False,
            "Too close to the camera. Move slightly back to keep full face inside the oval.",
            issues,
            overlay=overlay,
            angle_detected=angle_detected,
        )

    if "off_center" in issues:
        hints = []
        if offset_x < -0.20:
            hints.append("right")
        elif offset_x > 0.20:
            hints.append("left")
        if offset_y < -0.22:
            hints.append("down")
        elif offset_y > 0.22:
            hints.append("up")
        direction = " and ".join(hints) if hints else "to the center"
        return _base_payload(
            "off_center",
            False,
            f"Face is off-center. Move slightly {direction} into the guide oval.",
            issues,
            overlay=overlay,
            angle_detected=angle_detected,
        )

    if "too_blurry" in issues:
        return _base_payload(
            "too_blurry",
            False,
            "Image is too blurry. Hold still and ensure sharp focus before capturing.",
            issues,
            overlay=overlay,
            angle_detected=angle_detected,
        )

    if "occluded" in issues:
        return _base_payload(
            "occluded",
            False,
            "Lower face or landmarks appear obstructed. Remove coverings and face clearly.",
            issues,
            overlay=overlay,
            angle_detected=angle_detected,
        )

    if "head_tilted" in issues:
        return _base_payload(
            "head_tilted",
            False,
            "Keep your head level horizontally within the guide lines.",
            issues,
            overlay=overlay,
            angle_detected=angle_detected,
        )

    if normalized_target and normalized_target in ANGLE_STEP_SPECS:
        spec = ANGLE_STEP_SPECS[normalized_target]
        ymin = float(spec["yaw_min"])
        ymax = float(spec["yaw_max"])
        max_pitch = float(spec["max_pitch"])

        if abs(pitch) > max_pitch:
            hint = (
                "Lower your chin slightly" if pitch > 0 else "Lift your chin slightly"
            )
            issues.append("pitch_out_of_range")
            return _base_payload(
                "adjust_angle",
                False,
                f"{hint} for {spec['label']}.",
                issues,
                overlay=overlay,
                angle_detected=angle_detected,
            )

        if yaw < ymin or yaw > ymax:
            issues.append("wrong_angle")
            if normalized_target == "front":
                hint = (
                    "Turn slightly right to face straight ahead."
                    if yaw < ymin
                    else "Turn slightly left to face straight ahead."
                )
            elif normalized_target in ("slight_left", "left_profile"):
                hint = (
                    "Turn back slightly right — rotated a bit too far left."
                    if yaw < ymin
                    else f"Turn your head more to the left ({spec['label']})."
                )
            else:
                hint = (
                    f"Turn your head more to the right ({spec['label']})."
                    if yaw < ymin
                    else "Turn back slightly left — rotated a bit too far right."
                )
            return _base_payload(
                "adjust_angle",
                False,
                hint,
                issues,
                overlay=overlay,
                angle_detected=angle_detected,
            )

        return _base_payload(
            "ready",
            True,
            f"Aligned for {spec['label']} — hold steady or capture.",
            [],
            overlay=overlay,
            angle_detected=normalized_target,
        )

    return _base_payload(
        "ready",
        True,
        "Face aligned clearly — ready to capture.",
        [],
        overlay=overlay,
        angle_detected=angle_detected,
    )

