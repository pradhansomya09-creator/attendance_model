"""Computer vision quality, enhancement, head-pose, and occlusion utilities."""

from core.vision.image_quality import (
    ImageQualityReport,
    analyze_and_enhance_frame,
    analyze_frame_quality,
    compute_frame_difference,
    enhance_frame,
)
from core.vision.head_pose import (
    HeadPoseEstimate,
    estimate_head_pose_and_occlusion,
    score_face_crop_clarity,
)
from core.vision.face_geometry import (
    ANGLE_STEP_SPECS,
    ENROLLMENT_ANGLES,
    classify_detected_angle,
    compute_facial_guide_overlay,
    evaluate_enrollment_alignment,
    normalize_angle_key,
)

__all__ = [
    "ImageQualityReport",
    "analyze_and_enhance_frame",
    "analyze_frame_quality",
    "compute_frame_difference",
    "enhance_frame",
    "HeadPoseEstimate",
    "estimate_head_pose_and_occlusion",
    "score_face_crop_clarity",
    "ANGLE_STEP_SPECS",
    "ENROLLMENT_ANGLES",
    "classify_detected_angle",
    "compute_facial_guide_overlay",
    "evaluate_enrollment_alignment",
    "normalize_angle_key",
]

