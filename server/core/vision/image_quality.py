"""Intelligent Image Quality Detection and Adaptive Enhancement Module."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple

import cv2
import numpy as np


@dataclass
class ImageQualityReport:
    """Frame quality assessment and adaptive enhancement telemetry."""

    status: str  # "green" | "yellow" | "red"
    score: float  # 0.0 - 1.0
    brightness: float  # 0.0 - 255.0
    contrast: float
    sharpness: float
    haze_score: float
    overexposed_ratio: float
    underexposed_ratio: float
    obstruction_score: float
    is_ir_mode: bool
    recognition_reliable: bool
    issues: List[str] = field(default_factory=list)
    enhancements_applied: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "score": round(float(self.score), 3),
            "brightness": round(float(self.brightness), 2),
            "contrast": round(float(self.contrast), 2),
            "sharpness": round(float(self.sharpness), 2),
            "haze_score": round(float(self.haze_score), 3),
            "overexposed_ratio": round(float(self.overexposed_ratio), 3),
            "underexposed_ratio": round(float(self.underexposed_ratio), 3),
            "obstruction_score": round(float(self.obstruction_score), 3),
            "is_ir_mode": bool(self.is_ir_mode),
            "recognition_reliable": bool(self.recognition_reliable),
            "issues": list(self.issues),
            "enhancements_applied": list(self.enhancements_applied),
        }


def compute_frame_difference(
    current_frame: np.ndarray, previous_frame: Optional[np.ndarray]
) -> Optional[float]:
    """Compute normalized mean absolute difference between consecutive frames for freeze detection."""
    if previous_frame is None or current_frame is None:
        return None
    if current_frame.shape != previous_frame.shape:
        return None
    curr_small = cv2.resize(current_frame, (160, 90), interpolation=cv2.INTER_AREA)
    prev_small = cv2.resize(previous_frame, (160, 90), interpolation=cv2.INTER_AREA)
    diff = cv2.absdiff(curr_small, prev_small)
    return float(np.mean(diff))


def _detect_infrared_mode(image: np.ndarray) -> bool:
    """Detect monochrome/infrared night-vision camera footage."""
    if image.ndim < 3 or image.shape[2] < 3:
        return True
    b, g, r = cv2.split(image)
    rg_diff = float(np.mean(np.abs(r.astype(np.int16) - g.astype(np.int16))))
    rb_diff = float(np.mean(np.abs(r.astype(np.int16) - b.astype(np.int16))))
    return rg_diff < 2.5 and rb_diff < 2.5


def analyze_frame_quality(image: np.ndarray) -> ImageQualityReport:
    """Evaluate brightness, sharpness, haze, exposure, obstruction, and IR characteristics."""
    if image is None or image.size == 0:
        return ImageQualityReport(
            status="red",
            score=0.0,
            brightness=0.0,
            contrast=0.0,
            sharpness=0.0,
            haze_score=1.0,
            overexposed_ratio=0.0,
            underexposed_ratio=1.0,
            obstruction_score=1.0,
            is_ir_mode=False,
            recognition_reliable=False,
            issues=["empty_frame"],
        )

    # Downscale for consistent real-time metrics regardless of 720p/1080p/4K resolution
    h, w = image.shape[:2]
    target_w = 320
    target_h = max(1, int(h * (target_w / max(1, w))))
    small = cv2.resize(image, (target_w, target_h), interpolation=cv2.INTER_AREA)

    ycrcb = cv2.cvtColor(small, cv2.COLOR_BGR2YCrCb)
    y_channel = ycrcb[:, :, 0]
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)

    brightness = float(np.mean(y_channel))
    contrast = float(np.std(y_channel))
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    overexposed_ratio = float(np.mean(y_channel >= 245))
    underexposed_ratio = float(np.mean(y_channel <= 25))

    # Estimate haze / fog via dark-channel intensity and low contrast
    min_rgb = np.min(small, axis=2)
    haze_score = float(np.clip(np.mean(min_rgb) / 180.0, 0.0, 1.0)) if contrast < 38 else float(
        np.clip((np.mean(min_rgb) - 60.0) / 180.0, 0.0, 1.0)
    )

    # Estimate camera lens obstruction via flat/low-gradient grid cells
    edges = cv2.Canny(gray, 40, 120)
    cell_h = max(1, target_h // 4)
    cell_w = max(1, target_w // 4)
    blocked_cells = 0
    total_cells = 0
    for r_idx in range(4):
        for c_idx in range(4):
            y1, y2 = r_idx * cell_h, min(target_h, (r_idx + 1) * cell_h)
            x1, x2 = c_idx * cell_w, min(target_w, (c_idx + 1) * cell_w)
            patch = gray[y1:y2, x1:x2]
            edge_patch = edges[y1:y2, x1:x2]
            if patch.size == 0:
                continue
            total_cells += 1
            if float(np.std(patch)) < 6.0 and float(np.mean(edge_patch > 0)) < 0.01:
                blocked_cells += 1
    obstruction_score = float(blocked_cells / max(1, total_cells))
    if contrast >= 30.0:
        # High global contrast indicates clear scene structure (e.g. clean sky or studio gradient), not lens cover
        obstruction_score = min(obstruction_score, 0.35)

    is_ir_mode = _detect_infrared_mode(small)

    issues: List[str] = []
    # Component scores in [0, 1]
    if brightness < 32.0:
        issues.append("darkness")
        bright_score = max(0.0, brightness / 32.0) * 0.35
    elif brightness < 65.0:
        issues.append("low_light")
        bright_score = 0.35 + ((brightness - 32.0) / 33.0) * 0.45
    elif brightness > 225.0:
        issues.append("overexposed")
        bright_score = max(0.1, 1.0 - (brightness - 225.0) / 30.0)
    else:
        bright_score = 1.0

    if overexposed_ratio > 0.35 and "overexposed" not in issues:
        issues.append("glare_overexposure")
        bright_score = min(bright_score, max(0.15, 1.0 - overexposed_ratio))

    if underexposed_ratio > 0.60 and "darkness" not in issues and "low_light" not in issues:
        issues.append("underexposed")
        bright_score = min(bright_score, max(0.15, 1.0 - underexposed_ratio * 0.8))

    if sharpness < 25.0:
        issues.append("severe_blur")
        sharp_score = max(0.05, sharpness / 25.0 * 0.35)
    elif sharpness < 65.0:
        issues.append("blur")
        sharp_score = 0.35 + ((sharpness - 25.0) / 40.0) * 0.50
    else:
        sharp_score = 1.0

    if contrast < 16.0:
        issues.append("low_contrast")
        contrast_score = max(0.1, contrast / 16.0 * 0.45)
    elif contrast < 28.0:
        contrast_score = 0.45 + ((contrast - 16.0) / 12.0) * 0.45
    else:
        contrast_score = 1.0

    if haze_score > 0.65 and contrast < 36.0:
        issues.append("haze_fog")

    if obstruction_score >= 0.75:
        issues.append("camera_obstructed")
    elif obstruction_score >= 0.45:
        issues.append("partial_obstruction")

    # Weighted quality score
    raw_score = (
        0.35 * bright_score
        + 0.25 * sharp_score
        + 0.20 * contrast_score
        + 0.20 * max(0.0, 1.0 - obstruction_score)
    )
    if "haze_fog" in issues:
        raw_score *= 0.82
    if "camera_obstructed" in issues:
        raw_score = min(raw_score, 0.22)
    if "darkness" in issues and brightness < 18.0:
        raw_score = min(raw_score, 0.25)

    score = float(np.clip(raw_score, 0.0, 1.0))

    if score >= 0.68 and not any(
        i in issues for i in ("darkness", "severe_blur", "camera_obstructed", "overexposed")
    ):
        status = "green"
    elif score >= 0.38:
        status = "yellow"
    else:
        status = "red"

    recognition_reliable = status != "red"

    return ImageQualityReport(
        status=status,
        score=score,
        brightness=brightness,
        contrast=contrast,
        sharpness=sharpness,
        haze_score=haze_score,
        overexposed_ratio=overexposed_ratio,
        underexposed_ratio=underexposed_ratio,
        obstruction_score=obstruction_score,
        is_ir_mode=is_ir_mode,
        recognition_reliable=recognition_reliable,
        issues=issues,
    )


def enhance_frame(
    image: np.ndarray,
    report: ImageQualityReport,
    *,
    high_quality_denoise: bool = False,
) -> Tuple[np.ndarray, List[str]]:
    """Apply adaptive brightness, gamma, CLAHE, and denoising based on quality diagnostics."""
    if image is None or image.size == 0:
        return image, []

    enhanced = image.copy()
    applied: List[str] = []

    if report.is_ir_mode:
        gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.2, tileGridSize=(8, 8))
        ir_eq = clahe.apply(gray)
        enhanced = cv2.cvtColor(ir_eq, cv2.COLOR_GRAY2BGR)
        applied.append("infrared_clahe")
        return enhanced, applied

    needs_gamma_or_clahe = any(
        issue in report.issues
        for issue in ("darkness", "low_light", "underexposed", "low_contrast", "haze_fog")
    )
    needs_highlight_recovery = any(
        issue in report.issues for issue in ("overexposed", "glare_overexposure")
    )

    if needs_gamma_or_clahe or needs_highlight_recovery:
        lab = cv2.cvtColor(enhanced, cv2.COLOR_BGR2LAB)
        l_chan, a_chan, b_chan = cv2.split(lab)

        if "darkness" in report.issues or "low_light" in report.issues or "underexposed" in report.issues:
            # Gamma < 1.0 lifts dark midtones/shadows toward target illumination
            gamma = float(np.clip(max(report.brightness, 15.0) / 95.0, 0.42, 0.82))
            lut = np.array(
                [min(255, int(((i / 255.0) ** gamma) * 255.0)) for i in range(256)],
                dtype=np.uint8,
            )
            l_chan = cv2.LUT(l_chan, lut)
            applied.append("gamma_correction")

        if needs_highlight_recovery:
            gamma = 1.45
            lut = np.array(
                [min(255, int(((i / 255.0) ** gamma) * 255.0)) for i in range(256)],
                dtype=np.uint8,
            )
            l_chan = cv2.LUT(l_chan, lut)
            applied.append("highlight_compression")

        if "low_contrast" in report.issues or "haze_fog" in report.issues or "low_light" in report.issues:
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            l_chan = clahe.apply(l_chan)
            applied.append("clahe_contrast")

        enhanced = cv2.cvtColor(cv2.merge((l_chan, a_chan, b_chan)), cv2.COLOR_LAB2BGR)

    if "darkness" in report.issues or "low_light" in report.issues:
        if high_quality_denoise:
            enhanced = cv2.fastNlMeansDenoisingColored(enhanced, None, 5, 5, 7, 15)
            applied.append("nlm_denoising")
        else:
            enhanced = cv2.bilateralFilter(enhanced, d=5, sigmaColor=35, sigmaSpace=35)
            applied.append("bilateral_denoising")

    return enhanced, applied


def analyze_and_enhance_frame(
    image: np.ndarray, *, high_quality_denoise: bool = False
) -> Tuple[np.ndarray, ImageQualityReport]:
    """Assess raw frame quality, enhance if needed, and re-evaluate post-enhancement visibility."""
    raw_report = analyze_frame_quality(image)
    if raw_report.status == "green" and not raw_report.is_ir_mode:
        return image, raw_report

    enhanced_img, applied = enhance_frame(
        image, raw_report, high_quality_denoise=high_quality_denoise
    )
    if not applied:
        return image, raw_report

    post_report = analyze_frame_quality(enhanced_img)
    post_report.enhancements_applied = applied
    # Preserve original obstruction / darkness flags if image could not be rescued
    if "camera_obstructed" in raw_report.issues and "camera_obstructed" not in post_report.issues:
        post_report.issues.append("camera_obstructed")
        post_report.status = "red"
        post_report.recognition_reliable = False

    # If enhancement improved visibility out of red into yellow, reflect recovered reliability
    if post_report.score > raw_report.score:
        return enhanced_img, post_report
    raw_report.enhancements_applied = applied
    return enhanced_img, raw_report
