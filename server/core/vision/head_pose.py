"""Head pose estimation, facial occlusion assessment, and multi-frame clarity scoring."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import cv2
import numpy as np


# Canonical 3D facial landmark coordinates (in mm) matching YuNet 5-point ordering:
# [right_eye, left_eye, nose_tip, right_mouth_corner, left_mouth_corner]
_MODEL_3D_POINTS = np.array(
    [
        [-30.0, -32.0, -25.0],  # Right eye
        [30.0, -32.0, -25.0],  # Left eye
        [0.0, 0.0, 0.0],  # Nose tip
        [-22.0, 32.0, -20.0],  # Right mouth corner
        [22.0, 32.0, -20.0],  # Left mouth corner
    ],
    dtype=np.float64,
)


@dataclass
class HeadPoseEstimate:
    yaw: float
    pitch: float
    roll: float
    pose_ok: bool
    occlusion_suspected: bool
    visibility_score: float
    clarity_score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "yaw": round(float(self.yaw), 2),
            "pitch": round(float(self.pitch), 2),
            "roll": round(float(self.roll), 2),
            "pose_ok": bool(self.pose_ok),
            "occlusion_suspected": bool(self.occlusion_suspected),
            "visibility_score": round(float(self.visibility_score), 3),
            "clarity_score": round(float(self.clarity_score), 3),
        }


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


def score_face_crop_clarity(image: np.ndarray, bbox: Any) -> float:
    """Compute normalized sharpness score [0, 1] for a detected face bounding box."""
    if image is None or image.size == 0 or not bbox:
        return 0.0
    norm = _normalize_bbox(bbox)
    h, w = image.shape[:2]
    x = max(0, int(norm["x"]))
    y = max(0, int(norm["y"]))
    bw = max(1, int(norm["width"]))
    bh = max(1, int(norm["height"]))
    x2 = min(w, x + bw)
    y2 = min(h, y + bh)
    if x2 <= x or y2 <= y:
        return 0.0
    crop = image[y:y2, x:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    return float(np.clip(lap_var / 140.0, 0.0, 1.0))


def _estimate_lower_face_occlusion(
    image: np.ndarray, bbox: Any, landmarks: Optional[List[Dict[str, Any]]]
) -> bool:
    """Detect likely mask/hand occlusion using lower-face vs upper-face variance & landmark bounds."""
    if image is None or image.size == 0 or not bbox:
        return False
    norm = _normalize_bbox(bbox)
    h, w = image.shape[:2]
    x = max(0, int(norm["x"]))
    y = max(0, int(norm["y"]))
    bw = max(1, int(norm["width"]))
    bh = max(1, int(norm["height"]))
    x2 = min(w, x + bw)
    y2 = min(h, y + bh)
    if x2 - x < 24 or y2 - y < 24:
        return False

    # Check if landmarks fall outside the bounding box (partial face crop / occlusion)
    if landmarks and len(landmarks) >= 5:
        out_of_box = 0
        for lm in landmarks[:5]:
            lx, ly = float(lm.get("x", 0)), float(lm.get("y", 0))
            if lx < x - 4 or lx > x2 + 4 or ly < y - 4 or ly > y2 + 4:
                out_of_box += 1
        if out_of_box >= 2:
            return True

    crop = image[y:y2, x:x2]
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    ch, _ = gray.shape
    upper = gray[: max(1, ch // 2), :]
    lower = gray[max(1, ch // 2) :, :]
    upper_std = float(np.std(upper))
    lower_std = float(np.std(lower))
    # Uniform surgical/cloth masks flatten lower-face texture relative to eyes/brow
    if upper_std > 18.0 and lower_std < upper_std * 0.30:
        return True
    return False


def _extract_landmark_points(face: Dict[str, Any]) -> List[Dict[str, float]]:
    landmarks = face.get("landmarks") or []
    if landmarks and len(landmarks) >= 5 and isinstance(landmarks[0], dict):
        return landmarks[:5]
    lm5 = face.get("landmarks_5") or []
    pts: List[Dict[str, float]] = []
    for item in lm5[:5]:
        if isinstance(item, dict):
            pts.append({"x": float(item.get("x", 0.0)), "y": float(item.get("y", 0.0))})
        elif isinstance(item, (list, tuple)) and len(item) >= 2:
            pts.append({"x": float(item[0]), "y": float(item[1])})
    return pts


def estimate_head_pose_and_occlusion(
    image: np.ndarray,
    face: Dict[str, Any],
    *,
    max_yaw_deg: float = 30.0,
    max_pitch_deg: float = 28.0,
) -> HeadPoseEstimate:
    """Estimate head yaw/pitch/roll from 5 facial landmarks and check visibility/occlusion."""
    bbox = face.get("bbox") or {}
    landmarks = _extract_landmark_points(face)
    clarity = score_face_crop_clarity(image, bbox)
    occlusion = _estimate_lower_face_occlusion(image, bbox, landmarks)

    yaw = 0.0
    pitch = 0.0
    roll = 0.0

    if len(landmarks) >= 5 and image is not None and image.size > 0:
        pts_2d = np.array(
            [[float(lm.get("x", 0.0)), float(lm.get("y", 0.0))] for lm in landmarks[:5]],
            dtype=np.float64,
        )
        right_eye, left_eye, nose, mouth_r, mouth_l = pts_2d
        # Normalize left/right ordering by screen X so mirrored/flipped landmarks
        # never invert roll or confuse solvePnP correspondences.
        if right_eye[0] > left_eye[0]:
            right_eye, left_eye = left_eye.copy(), right_eye.copy()
        if mouth_r[0] > mouth_l[0]:
            mouth_r, mouth_l = mouth_l.copy(), mouth_r.copy()
        pts_2d = np.array(
            [right_eye, left_eye, nose, mouth_r, mouth_l],
            dtype=np.float64,
        )

        # Geometric roll from eye line
        dx_eye = left_eye[0] - right_eye[0]
        dy_eye = left_eye[1] - right_eye[1]
        eye_dist = max(1.0, float(np.hypot(dx_eye, dy_eye)))
        roll = float(np.degrees(np.arctan2(dy_eye, dx_eye)))

        # Geometric yaw from nose horizontal offset between eyes
        eye_mid_x = 0.5 * (right_eye[0] + left_eye[0])
        yaw_geo = float(np.clip(((nose[0] - eye_mid_x) / (0.5 * eye_dist)) * 45.0, -75.0, 75.0))

        # Geometric pitch from nose vertical position between eye line and mouth line
        eye_mid_y = 0.5 * (right_eye[1] + left_eye[1])
        mouth_mid_y = 0.5 * (mouth_r[1] + mouth_l[1])
        face_vert = max(1.0, mouth_mid_y - eye_mid_y)
        nose_ratio = (nose[1] - eye_mid_y) / face_vert
        pitch_geo = float(np.clip((0.48 - nose_ratio) * 65.0, -60.0, 60.0))

        # Refine with solvePnP if frame dimensions are valid
        h, w = image.shape[:2]
        focal = float(max(w, h))
        cam_matrix = np.array(
            [[focal, 0.0, w / 2.0], [0.0, focal, h / 2.0], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )
        try:
            ok, rvec, _ = cv2.solvePnP(
                _MODEL_3D_POINTS,
                pts_2d,
                cam_matrix,
                np.zeros((4, 1), dtype=np.float64),
                flags=cv2.SOLVEPNP_EPNP,
            )
            if ok:
                rot_mat, _ = cv2.Rodrigues(rvec)
                sy = float(np.hypot(rot_mat[0, 0], rot_mat[1, 0]))
                if sy > 1e-6:
                    pnp_pitch = float(np.degrees(np.arctan2(-rot_mat[2, 0], sy)))
                    pnp_yaw = float(np.degrees(np.arctan2(rot_mat[1, 0], rot_mat[0, 0])))
                    # Blend geometric and PnP estimates to remain stable on 5-point landmarks
                    yaw = 0.7 * yaw_geo + 0.3 * float(np.clip(pnp_yaw, -75.0, 75.0))
                    pitch = 0.75 * pitch_geo + 0.25 * float(np.clip(pnp_pitch, -60.0, 60.0))
                else:
                    yaw, pitch = yaw_geo, pitch_geo
            else:
                yaw, pitch = yaw_geo, pitch_geo
        except cv2.error:
            yaw, pitch = yaw_geo, pitch_geo

    pose_ok = abs(yaw) <= max_yaw_deg and abs(pitch) <= max_pitch_deg and not occlusion
    pose_penalty = max(
        0.0,
        min(
            1.0,
            1.0 - 0.5 * (abs(yaw) / 70.0) - 0.5 * (abs(pitch) / 55.0),
        ),
    )
    visibility_score = float(
        np.clip(
            pose_penalty * (0.55 if occlusion else 1.0) * (0.4 + 0.6 * clarity),
            0.0,
            1.0,
        )
    )

    return HeadPoseEstimate(
        yaw=yaw,
        pitch=pitch,
        roll=roll,
        pose_ok=pose_ok,
        occlusion_suspected=occlusion,
        visibility_score=visibility_score,
        clarity_score=clarity,
    )
