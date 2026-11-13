import asyncio
import time
import logging
import cv2
import numpy as np
from typing import Dict, Any, List, Tuple, Callable

from config.models import FACE_DETECTOR_CONFIG
from core.vision import (
    ImageQualityReport,
    analyze_and_enhance_frame,
    estimate_head_pose_and_occlusion,
)
from hooks import (
    process_face_detection,
    process_face_tracking,
    process_liveness_detection,
)
from services.vlaser_service import VLaserService
from utils import serialize_faces
from utils.websocket_manager import notification_manager

logger = logging.getLogger(__name__)


class FrameDecodeError(Exception):
    """Raised when frame bytes cannot be converted into an image by OpenCV."""

    pass


class DetectionPipeline:
    """
    DetectionPipeline handles the processing stages for camera stream frames.

    This encapsulates OpenCV decoding, AI model inference (detection, tracking, liveness),
    and attendance recognition triggers into an isolated pipeline.
    """

    def __init__(self, live_stream_service: Any):
        """
        Initialize the pipeline with the required stream service.

        Why: Decoupling this logic from routing allows testing image processing pipelines
        separately from FastAPI's websocket protocol handlers.
        """
        self.live_stream_service = live_stream_service

    async def process_frame(
        self,
        frame_bytes: bytes,
        client_id: str,
        live_session_config: Any,
        fps_provider: Callable[[str], float],
    ) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """
        Execute frame decoding and AI pipeline evaluation.

        Returns:
            Tuple containing:
              - response_data: Serialized face detection metrics.
              - attendance_messages: List of attendance trigger notifications.
        """
        start_time = time.time()

        # 1. Image decoding
        nparr = np.frombuffer(frame_bytes, np.uint8)
        image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if image is None:
            raise FrameDecodeError("Failed to decode frame bytes to image.")

        # 1b. Intelligent Image Quality Detection & Adaptive Enhancement
        working_image, quality_report = analyze_and_enhance_frame(image)

        # 2. Face detection
        min_face_size = FACE_DETECTOR_CONFIG["min_face_size"]
        faces = await process_face_detection(
            working_image,
            confidence_threshold=FACE_DETECTOR_CONFIG["score_threshold"],
            nms_threshold=FACE_DETECTOR_CONFIG["nms_threshold"],
            min_face_size=min_face_size,
            enable_liveness=live_session_config.enable_liveness_detection,
        )

        # 3. Face tracking
        current_fps = fps_provider(client_id)
        faces = process_face_tracking(faces, working_image, current_fps, client_id)

        # 3b. Head pose & occlusion estimation per tracked face
        for face in faces:
            pose = estimate_head_pose_and_occlusion(working_image, face)
            face["head_pose"] = pose.to_dict()

        # 3c. V-LASER Spatial Tracking & Zone Analysis
        spatial_summary = None
        cam_id = getattr(live_session_config, "camera_id", None) or "cam-main-1"
        try:
            frame_h, frame_w = working_image.shape[:2]
            _, spatial_events, zone_counts = await VLaserService.process_spatial_frame(
                cam_id,
                faces,
                frame_width=frame_w,
                frame_height=frame_h,
                timestamp=start_time,
                organization_id=getattr(live_session_config, "organization_id", None),
            )
            spatial_summary = {
                "zone_counts": zone_counts,
                "events": [e.to_dict() for e in spatial_events],
            }

            if spatial_events:
                for ev in spatial_events:
                    asyncio.create_task(
                        notification_manager.broadcast({
                            "type": "vlaser_spatial_event",
                            "event": ev.to_dict(),
                        })
                    )
        except Exception as spatial_err:
            logger.warning("[DetectionPipeline] V-LASER spatial tracking skipped: %s", spatial_err)

        # 4. Liveness detection
        faces = await process_liveness_detection(
            faces,
            working_image,
            live_session_config.enable_liveness_detection,
            tracking_namespace=client_id,
        )

        # 5. Attendance verification/recognition (with smart validation & recovery)
        attendance_messages = await self.live_stream_service.process_live_recognition(
            working_image,
            faces,
            live_session_config,
            client_id,
            quality_report=quality_report,
        )

        # 5b. V-LASER Conservative Identity Association
        try:
            cam_id = getattr(live_session_config, "camera_id", None) or "cam-main-1"
            identity_mgr = VLaserService.get_identity_manager(cam_id)
            q_score = quality_report.score if quality_report else 1.0
            q_status = quality_report.status if quality_report else "green"
            for face in faces:
                tid = face.get("track_id")
                if tid is not None and int(tid) >= 0:
                    binding = identity_mgr.evaluate_track_identity(
                        track_id=int(tid),
                        face_detected=True,
                        face_dict=face,
                        quality_score=q_score,
                        quality_status=q_status,
                        now=start_time,
                    )
                    face["spatial_identity"] = binding.to_dict()
        except Exception as ident_err:
            logger.warning("[DetectionPipeline] V-LASER identity association error: %s", ident_err)

        # 6. Serialization
        serialized_faces = serialize_faces(faces, "websocket")
        processing_time = time.time() - start_time
        current_timestamp = time.time()

        # 7. Adaptive Frame Skipping math
        if processing_time * 1000 > 50:
            suggested_skip = 2
        elif processing_time * 1000 > 30:
            suggested_skip = 1
        else:
            suggested_skip = 0

        headcount_summary = getattr(
            live_session_config, "last_headcount_summary", None
        )

        response_data = {
            "type": "detection_response",
            "faces": serialized_faces,
            "model_used": "face_detector",
            "processing_time": processing_time,
            "timestamp": current_timestamp,
            "frame_timestamp": start_time,
            "suggested_skip": suggested_skip,
            "image_quality": quality_report.to_dict(),
            "headcount_summary": headcount_summary,
            "spatial": spatial_summary,
            "success": True,
        }

        return response_data, attendance_messages
