import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

import numpy as np
from sqlalchemy import select

from api.schemas import AttendanceEventCreate
from core.vision.head_pose import HeadPoseEstimate, estimate_head_pose_and_occlusion
from core.vision.image_quality import ImageQualityReport
from database.models import CctvCamera
from services.attendance_service import AttendanceService
from services.cctv_monitor_service import CctvMonitorService
from services.smart_attendance_engine import (
    SmartAttendanceEngine,
    SmartSessionAccumulator,
    TrackObservationState,
    _encode_face_crop,
    _today_str,
    _utc_now,
)

logger = logging.getLogger(__name__)

MIN_RECOGNITION_FACE_SIZE = 48
LIVE_CONTEXT_TTL_SECONDS = 5.0
LIVE_RECOGNITION_SAMPLE_INTERVAL = 5
PROTECTED_IDENTITY = "PROTECTED_IDENTITY"


@dataclass
class LiveGroupContext:
    group_id: Optional[str] = None
    group_exists: bool = False
    allowed_person_ids: set[str] = field(default_factory=set)
    members_by_person_id: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    attendance_cooldown_seconds: int = 300
    max_recognition_faces_per_frame: int = 6
    group_matrix: Optional[np.ndarray] = None
    person_index_map: list[str] = field(default_factory=list)
    loaded_at: float = 0.0


@dataclass(eq=False)
class LiveSessionConfig:
    enable_liveness_detection: bool = False
    requested_liveness_detection: bool = False
    force_liveness_detection: bool = False
    active_group_id: Optional[str] = None
    max_recognition_faces_per_frame: int = 6
    client_id: Optional[str] = None
    device_id: Optional[str] = None
    scan_behavior: Optional[str] = None
    organization_id: Optional[str] = None
    group_context: LiveGroupContext = field(default_factory=LiveGroupContext)
    attendance_cooldowns: Dict[str, float] = field(default_factory=dict)
    track_recognition_cache: Dict[
        int, tuple[Dict[str, Any], Optional[Dict[str, Any]]]
    ] = field(default_factory=dict)
    track_last_sampled_frame: Dict[int, int] = field(default_factory=dict)
    frame_counter: int = 0
    is_dirty: bool = False
    loaded_version: int = 0
    camera_id: Optional[str] = None
    smart_accumulator: SmartSessionAccumulator = field(
        default_factory=SmartSessionAccumulator
    )
    last_headcount_summary: Optional[Dict[str, Any]] = None
    last_quality_alert_at: float = 0.0

    def reset_group(self, group_id: Optional[str]) -> None:
        self.active_group_id = group_id
        self.group_context = LiveGroupContext(
            group_id=None,
            max_recognition_faces_per_frame=self.max_recognition_faces_per_frame,
        )
        self.attendance_cooldowns.clear()
        self.track_recognition_cache.clear()
        self.track_last_sampled_frame.clear()
        self.smart_accumulator = SmartSessionAccumulator()
        self.last_headcount_summary = None
        self.is_dirty = True

    def invalidate(self) -> None:
        self.track_recognition_cache.clear()
        self.track_last_sampled_frame.clear()
        self.is_dirty = True


class LiveStreamService:
    _active_configs: set[LiveSessionConfig] = set()
    _db_versions: Dict[Optional[str], int] = {}

    def __init__(self, organization_id: Optional[str]):
        self.organization_id = organization_id
        self._background_tasks: set = set()

    @classmethod
    def register_config(cls, config: LiveSessionConfig) -> None:
        cls._active_configs.add(config)

    @classmethod
    def unregister_config(cls, config: Optional[LiveSessionConfig]) -> None:
        if config is not None:
            cls._active_configs.discard(config)

    @classmethod
    def get_db_version(cls, organization_id: Optional[str] = None) -> int:
        return cls._db_versions.get(organization_id, 0)

    @classmethod
    def invalidate_all(cls, organization_id: Optional[str] = None) -> None:
        """Mark active streaming sessions dirty and bump version so they immediately reload group context."""
        current = cls._db_versions.get(organization_id, 0)
        cls._db_versions[organization_id] = current + 1
        for config in list(cls._active_configs):
            if organization_id is None or config.organization_id == organization_id:
                config.invalidate()
        logger.info(
            "[LiveStreamService] Invalidated active live stream contexts for organization: %s (v%d)",
            organization_id,
            cls._db_versions[organization_id],
        )

    @staticmethod
    def _extract_face_area(face: Dict[str, Any]) -> float:
        bbox = face.get("bbox") or {}
        return float(bbox.get("width", 0) * bbox.get("height", 0))

    @classmethod
    def apply_liveness_policy(
        cls,
        organization_id: Optional[str],
        forced: bool,
        preferred: bool,
        *,
        invalidate: bool = True,
    ) -> None:
        configs = [
            config
            for config in cls._active_configs
            if config.organization_id == organization_id
        ]
        changed = any(
            config.force_liveness_detection != bool(forced)
            or config.requested_liveness_detection != bool(preferred)
            or config.enable_liveness_detection != bool(forced or preferred)
            for config in configs
        )
        for config in configs:
            config.force_liveness_detection = bool(forced)
            config.requested_liveness_detection = bool(preferred)
            config.enable_liveness_detection = bool(forced or preferred)
        if invalidate or changed:
            cls.invalidate_all(organization_id)

    @staticmethod
    def _has_live_recognition_basics(face: Dict[str, Any]) -> bool:
        bbox = face.get("bbox") or {}
        if bbox.get("width", 0) < MIN_RECOGNITION_FACE_SIZE:
            return False
        if bbox.get("height", 0) < MIN_RECOGNITION_FACE_SIZE:
            return False
        return face.get("track_id") is not None

    @staticmethod
    def _is_attendance_candidate(face: Dict[str, Any]) -> bool:
        liveness = face.get("liveness") or {}
        return liveness.get("status") == "real" and liveness.get("is_real") is True

    def _is_attendance_allowed(
        self, face: Dict[str, Any], config: LiveSessionConfig
    ) -> bool:
        if not config.enable_liveness_detection:
            return self._has_live_recognition_basics(face)
        return self._is_attendance_candidate(face)

    @staticmethod
    def _serialize_recognition_result(
        result: Dict[str, Any], member_info: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        person_id = result.get("person_id")
        similarity = float(result.get("similarity") or 0.0)
        error = result.get("error")

        if not person_id:
            return {
                "success": bool(result.get("success", False)),
                "person_id": None,
                "name": None,
                "similarity": similarity,
                "processing_time": 0.0,
                "error": error,
            }

        return {
            "success": True,
            "person_id": person_id,
            "name": (member_info or {}).get("name") or person_id,
            "similarity": similarity,
            "processing_time": 0.0,
            "error": error,
        }

    @staticmethod
    def _build_attendance_message(
        event_result, member_info: Dict[str, Any], face: Dict[str, Any]
    ) -> Dict[str, Any]:
        bbox = face.get("bbox") or {}
        return {
            "type": "attendance_event",
            "data": {
                "id": event_result.id,
                "person_id": event_result.person_id,
                "group_id": event_result.group_id,
                "timestamp": event_result.timestamp.isoformat(),
                "confidence": event_result.confidence,
                "location": event_result.location,
                "event_type": event_result.event_type,
                "time_health": (
                    event_result.time_health.model_dump(mode="json")
                    if event_result.time_health
                    else None
                ),
                "member": {
                    "name": member_info.get("name"),
                    "role": member_info.get("role"),
                },
                "bbox": {
                    "x": bbox.get("x"),
                    "y": bbox.get("y"),
                    "width": bbox.get("width"),
                    "height": bbox.get("height"),
                },
                "track_id": face.get("track_id"),
            },
        }

    async def load_initial_config(self) -> LiveSessionConfig:
        from database.repository import AttendanceRepository
        from database.session import AsyncSessionLocal

        config = LiveSessionConfig()
        config.organization_id = self.organization_id
        config.loaded_version = self.get_db_version(self.organization_id)
        self.register_config(config)

        try:
            while True:
                version = self.get_db_version(self.organization_id)
                async with AsyncSessionLocal() as session:
                    repo = AttendanceRepository(
                        session, organization_id=self.organization_id
                    )
                    settings = await repo.get_settings()
                    if version != self.get_db_version(self.organization_id):
                        continue
                    config.requested_liveness_detection = (
                        settings.enable_liveness_detection
                    )
                    config.force_liveness_detection = bool(
                        getattr(settings, "cloud_force_liveness", False)
                    )
                    config.enable_liveness_detection = bool(
                        config.requested_liveness_detection
                        or config.force_liveness_detection
                    )
                    config.max_recognition_faces_per_frame = (
                        settings.max_recognition_faces_per_frame
                        if settings.max_recognition_faces_per_frame is not None
                        else 6
                    )
                    config.group_context.max_recognition_faces_per_frame = (
                        config.max_recognition_faces_per_frame
                    )
                    config.loaded_version = version
                    break
        except Exception as exc:
            # An unreadable settings row must not disable a cached Cloud requirement.
            config.force_liveness_detection = True
            config.enable_liveness_detection = True
            logger.warning(
                "[LiveStreamService] Failed to load initial stream config: %s", exc
            )
        return config

    def apply_config_message(
        self, config: LiveSessionConfig, message: Dict[str, Any]
    ) -> None:
        if "enable_liveness_detection" in message:
            config.requested_liveness_detection = bool(
                message.get("enable_liveness_detection", True)
            )
            config.enable_liveness_detection = bool(
                config.requested_liveness_detection or config.force_liveness_detection
            )

        if "client_id" in message:
            config.client_id = message.get("client_id")

        if "device_id" in message:
            config.device_id = message.get("device_id")

        if "camera_id" in message:
            config.camera_id = message.get("camera_id")

        if "scan_behavior" in message:
            behavior = message.get("scan_behavior")
            if behavior is None or behavior in {"automatic", "entry_only", "exit_only"}:
                config.scan_behavior = behavior

        if "group_id" in message:
            requested_group_id = message.get("group_id")
            normalized_group_id = (
                requested_group_id.strip()
                if isinstance(requested_group_id, str) and requested_group_id.strip()
                else None
            )
            config.reset_group(normalized_group_id)

        if message.get("force_refresh", False):
            config.is_dirty = True

        if "max_recognition_faces_per_frame" in message:
            configured_cap = message.get("max_recognition_faces_per_frame", 6)
            try:
                parsed = int(configured_cap)
                # 0 means "no limit"; only enforce minimum of 1 for positive values
                config.max_recognition_faces_per_frame = (
                    max(1, parsed) if parsed > 0 else 0
                )
            except (TypeError, ValueError):
                config.max_recognition_faces_per_frame = 6
            config.group_context.max_recognition_faces_per_frame = (
                config.max_recognition_faces_per_frame
            )

    async def _fetch_group_context(
        self, active_group_id: str, max_recognition_faces_per_frame: int
    ) -> LiveGroupContext:
        """Fetch group details and members from the database to build a fast-matching vector matrix.

        This handles the synchronous database interaction and caches them inside LiveGroupContext to bypass
        repeated SQLite lookups in the hot path.
        """
        from database.repository import AttendanceRepository
        from database.session import AsyncSessionLocal

        group_context = LiveGroupContext(
            group_id=active_group_id,
            max_recognition_faces_per_frame=max_recognition_faces_per_frame,
            loaded_at=time.time(),
        )

        async with AsyncSessionLocal() as session:
            repo = AttendanceRepository(session, organization_id=self.organization_id)
            settings = await repo.get_settings()

            group_context.attendance_cooldown_seconds = (
                settings.attendance_cooldown_seconds or 300
            )
            group_context.max_recognition_faces_per_frame = (
                settings.max_recognition_faces_per_frame
                if settings.max_recognition_faces_per_frame is not None
                else 6
            )

            from sqlalchemy import select
            from database.models import AttendanceGroup, AttendanceMember

            if active_group_id and active_group_id.lower() == "all":
                stmt = (
                    select(
                        AttendanceMember.person_id,
                        AttendanceMember.name,
                        AttendanceMember.role,
                    )
                    .join(
                        AttendanceGroup, AttendanceMember.group_id == AttendanceGroup.id
                    )
                    .where(
                        AttendanceMember.is_deleted.is_(False),
                        AttendanceMember.is_active.is_(True),
                        AttendanceGroup.is_deleted.is_(False),
                        AttendanceGroup.is_active.is_(True),
                    )
                )
                stmt = repo._apply_org_scope(stmt, AttendanceMember)
                stmt = repo._apply_org_scope(stmt, AttendanceGroup)
                res = await repo.session.execute(stmt)
                rows = res.all()

                group_context.group_exists = True
                group_context.allowed_person_ids = {r[0] for r in rows}
                group_context.members_by_person_id = {
                    r[0]: {
                        "name": r[1],
                        "role": r[2],
                    }
                    for r in rows
                }
            else:
                group = await repo.get_group(active_group_id)
                if group and group.is_active:
                    stmt = select(
                        AttendanceMember.person_id,
                        AttendanceMember.name,
                        AttendanceMember.role,
                    ).where(
                        AttendanceMember.group_id == active_group_id,
                        AttendanceMember.is_deleted.is_(False),
                        AttendanceMember.is_active.is_(True),
                    )
                    stmt = repo._apply_org_scope(stmt, AttendanceMember)
                    res = await repo.session.execute(stmt)
                    rows = res.all()

                    group_context.group_exists = True
                    group_context.allowed_person_ids = {r[0] for r in rows}
                    group_context.members_by_person_id = {
                        r[0]: {
                            "name": r[1],
                            "role": r[2],
                        }
                        for r in rows
                    }

            if group_context.group_exists:
                # Pre-build high-performance NumPy matrix for batch recognition
                from core.lifespan import face_recognizer

                if face_recognizer:
                    valid_embeddings = []
                    valid_person_ids = []

                    if hasattr(face_recognizer, "export_template_bank"):
                        bank_ids, bank_matrix = (
                            await face_recognizer.export_template_bank(
                                organization_id=self.organization_id
                            )
                        )
                        if bank_matrix is not None and bank_ids:
                            for idx, person_id in enumerate(bank_ids):
                                if person_id in group_context.allowed_person_ids:
                                    valid_embeddings.append(bank_matrix[idx])
                                    valid_person_ids.append(person_id)

                    if not valid_embeddings:
                        # Fallback to 1:1 person centroid embeddings
                        full_db = await face_recognizer.export_embeddings(
                            organization_id=self.organization_id
                        )
                        for person_id in group_context.allowed_person_ids:
                            if person_id in full_db:
                                valid_embeddings.append(full_db[person_id])
                                valid_person_ids.append(person_id)

                    if valid_embeddings:
                        group_context.group_matrix = np.stack(valid_embeddings)
                        group_context.person_index_map = valid_person_ids

        return group_context

    async def ensure_group_context(self, config: LiveSessionConfig) -> LiveGroupContext:
        """Ensure group settings are populated, loading changes only when switched or marked dirty."""
        if not config.active_group_id:
            return config.group_context

        current_ver = self.get_db_version(self.organization_id)
        is_group_switch = config.group_context.group_id != config.active_group_id
        is_version_stale = config.loaded_version != current_ver
        time_since_load = time.time() - config.group_context.loaded_at
        is_cold_matrix_retry = (
            config.group_context.group_matrix is None and time_since_load > 3.0
        )

        if (
            is_group_switch
            or config.is_dirty
            or is_version_stale
            or is_cold_matrix_retry
        ):
            group_id = config.active_group_id
            global_version = self.get_db_version()
            context = await self._fetch_group_context(
                group_id, config.max_recognition_faces_per_frame
            )
            if (
                config.active_group_id != group_id
                or self.get_db_version(self.organization_id) != current_ver
                or self.get_db_version() != global_version
            ):
                # A write or group switch raced this load. Skip this frame and
                # reload next time instead of publishing its stale snapshot.
                config.is_dirty = True
                return LiveGroupContext()
            config.group_context = context
            config.track_recognition_cache.clear()
            config.track_last_sampled_frame.clear()
            config.is_dirty = False
            config.loaded_version = current_ver
            return config.group_context

        return config.group_context

    @staticmethod
    def _resolve_head_pose(
        image: np.ndarray, face: Dict[str, Any]
    ) -> HeadPoseEstimate:
        hp = face.get("head_pose")
        if isinstance(hp, dict) and "visibility_score" in hp and "pose_ok" in hp:
            return HeadPoseEstimate(
                yaw=float(hp.get("yaw", 0.0)),
                pitch=float(hp.get("pitch", 0.0)),
                roll=float(hp.get("roll", 0.0)),
                pose_ok=bool(hp.get("pose_ok", True)),
                occlusion_suspected=bool(hp.get("occlusion_suspected", False)),
                visibility_score=float(hp.get("visibility_score", 0.85)),
                clarity_score=float(hp.get("clarity_score", 0.8)),
            )
        pose = estimate_head_pose_and_occlusion(image, face)
        face["head_pose"] = pose.to_dict()
        return pose

    @staticmethod
    def _build_live_frame_headcount_summary(
        faces: list[Dict[str, Any]],
        *,
        config: LiveSessionConfig,
        group_context: LiveGroupContext,
        quality_report: Optional[ImageQualityReport] = None,
    ) -> Dict[str, int]:
        """Compute live headcount metrics strictly from faces currently in the frame."""
        enrolled_count = len(group_context.members_by_person_id)
        # Filter for genuine faces currently in frame (ignoring tiny noise artifacts)
        valid_faces = [
            f
            for f in faces
            if (
                isinstance(f.get("bbox"), (dict, list))
                and f.get("confidence", 1.0) >= 0.50
                and (
                    (
                        isinstance(f.get("bbox"), dict)
                        and f["bbox"].get("width", 0) >= 35
                        and f["bbox"].get("height", 0) >= 35
                    )
                    or (
                        isinstance(f.get("bbox"), list)
                        and len(f["bbox"]) >= 4
                        and f["bbox"][2] >= 35
                        and f["bbox"][3] >= 35
                    )
                )
            )
        ]
        unique_detected = len(valid_faces)
        if unique_detected == 0:
            return {
                "enrolled": enrolled_count,
                "unique_detected": 0,
                "successfully_identified": 0,
                "unknown_individuals": 0,
                "pending_verification": 0,
                "confirmed_present": 0,
                "section_mismatches": 0,
                "duplicate_alerts": 0,
            }

        quality_is_red = quality_report is not None and quality_report.status == "red"
        successfully_identified = 0
        unknown_individuals = 0
        section_mismatches = 0
        pending_verification = 0
        identified_pids: list[str] = []

        for face in valid_faces:
            rec = face.get("recognition")
            liveness_status = (face.get("liveness") or {}).get("status")
            liveness_ok = (not config.enable_liveness_detection) or (
                liveness_status == "real"
            )

            if isinstance(rec, dict) and rec.get("section_mismatch"):
                section_mismatches += 1
            elif (
                isinstance(rec, dict)
                and rec.get("person_id")
                and rec.get("person_id") != PROTECTED_IDENTITY
                and liveness_ok
                and not quality_is_red
            ):
                successfully_identified += 1
                identified_pids.append(str(rec["person_id"]))
            elif (
                isinstance(rec, dict)
                and "person_id" in rec
                and rec.get("person_id") is None
                and not rec.get("error")
                and liveness_ok
                and not quality_is_red
            ):
                unknown_individuals += 1
            else:
                pending_verification += 1

        duplicate_alerts = max(0, len(identified_pids) - len(set(identified_pids)))
        return {
            "enrolled": enrolled_count,
            "unique_detected": unique_detected,
            "successfully_identified": successfully_identified,
            "unknown_individuals": unknown_individuals,
            "pending_verification": pending_verification,
            "confirmed_present": successfully_identified,
            "section_mismatches": section_mismatches,
            "duplicate_alerts": duplicate_alerts,
        }

    async def process_live_recognition(
        self,
        image: np.ndarray,
        faces: list[Dict[str, Any]],
        config: LiveSessionConfig,
        client_id: Optional[str] = None,
        *,
        quality_report: Optional[ImageQualityReport] = None,
    ) -> list[Dict[str, Any]]:
        early_alerts: list[Dict[str, Any]] = []
        now_ts = time.time()

        if config.camera_id and config.frame_counter % 10 == 0:
            try:
                await CctvMonitorService.record_frame_telemetry(
                    config.camera_id,
                    image,
                    fps=15.0,
                    organization_id=self.organization_id,
                )
            except Exception as tele_err:
                logger.debug("[LiveStreamService] Camera telemetry skipped: %s", tele_err)

        if quality_report is not None and quality_report.status == "red":
            if now_ts - config.last_quality_alert_at >= 10.0:
                config.last_quality_alert_at = now_ts
                issues_label = ", ".join(quality_report.issues or ["poor_visibility"])
                early_alerts.append(
                    {
                        "type": "cctv_alert",
                        "alert_type": "quality_warning",
                        "severity": "critical",
                        "camera_id": config.camera_id,
                        "group_id": config.active_group_id,
                        "quality_status": quality_report.status,
                        "quality_score": quality_report.score,
                        "issues": quality_report.issues,
                        "message": (
                            f"Camera Image Quality Warning ({issues_label}): "
                            "Recognition unreliable; affected attendance set to Pending Verification."
                        ),
                        "timestamp": now_ts,
                    }
                )

        if not faces:
            config.last_headcount_summary = self._build_live_frame_headcount_summary(
                [],
                config=config,
                group_context=config.group_context,
                quality_report=quality_report,
            )
            return early_alerts

        config.frame_counter += 1

        # Periodic cleanup of stale tracks from recognition cache
        if len(config.track_recognition_cache) > 20:
            active_tids = {
                f.get("track_id")
                for f in faces
                if f.get("track_id") is not None and f.get("track_id") >= 0
            }
            stale_tids = [
                tid
                for tid, last_f in config.track_last_sampled_frame.items()
                if tid not in active_tids and (config.frame_counter - last_f > 60)
            ]
            for tid in stale_tids:
                config.track_recognition_cache.pop(tid, None)
                config.track_last_sampled_frame.pop(tid, None)

        group_context = await self.ensure_group_context(config)
        if not config.active_group_id or not group_context.group_exists:
            config.last_headcount_summary = self._build_live_frame_headcount_summary(
                faces,
                config=config,
                group_context=group_context,
                quality_report=quality_report,
            )
            return early_alerts

        from core.lifespan import face_recognizer
        from database.repository import AttendanceRepository
        from database.session import AsyncSessionLocal

        if not face_recognizer:
            config.last_headcount_summary = self._build_live_frame_headcount_summary(
                faces,
                config=config,
                group_context=group_context,
                quality_report=quality_report,
            )
            return early_alerts

        context_version = config.loaded_version
        global_version = self.get_db_version()

        def context_is_current() -> bool:
            return (
                not config.is_dirty
                and config.group_context is group_context
                and config.active_group_id == group_context.group_id
                and self.get_db_version(self.organization_id) == context_version
                and self.get_db_version() == global_version
            )

        recognition_candidates = sorted(
            (
                face
                for face in faces
                if self._has_live_recognition_basics(face)
                and (
                    not config.enable_liveness_detection
                    or face.get("liveness", {}).get("status")
                    in ("real", "candidate_real")
                )
            ),
            key=self._extract_face_area,
            reverse=True,
        )

        limit = config.max_recognition_faces_per_frame
        if limit > 0:
            recognition_candidates = recognition_candidates[:limit]

        if not recognition_candidates:
            config.last_headcount_summary = self._build_live_frame_headcount_summary(
                faces,
                config=config,
                group_context=group_context,
                quality_report=quality_report,
            )
            return early_alerts

        # Partition candidates: infer immediately on first appearance or when sample interval is due
        faces_to_infer: list[Dict[str, Any]] = []
        for face in recognition_candidates:
            tid = face.get("track_id")
            is_untracked = tid is None or tid < 0
            is_new_track = tid not in config.track_recognition_cache
            is_sample_due = (
                config.frame_counter - config.track_last_sampled_frame.get(tid, -999)
                >= LIVE_RECOGNITION_SAMPLE_INTERVAL
            )

            if is_untracked or is_new_track or is_sample_due:
                faces_to_infer.append(face)

        new_results_map: Dict[int, Dict[str, Any]] = {}
        if faces_to_infer:
            inferred_results = await face_recognizer.recognize_faces(
                image,
                faces_to_infer,
                allowed_person_ids=list(group_context.allowed_person_ids),
                organization_id=self.organization_id,
                prebuilt_matrix=group_context.group_matrix,
                person_index_map=group_context.person_index_map,
            )
            for face, res in zip(faces_to_infer, inferred_results):
                new_results_map[id(face)] = res

        if not context_is_current():
            config.invalidate()
            for face in recognition_candidates:
                face.pop("recognition", None)
            return []

        from core.lifespan import liveness_detector

        attendance_messages: list[Dict[str, Any]] = list(early_alerts)
        smart_dirty = False
        effective_quality = quality_report or ImageQualityReport(
            status="green",
            score=0.9,
            brightness=120.0,
            contrast=40.0,
            sharpness=100.0,
            haze_score=0.0,
            overexposed_ratio=0.0,
            underexposed_ratio=0.0,
            obstruction_score=0.0,
            is_ir_mode=False,
            recognition_reliable=True,
            issues=[],
            enhancements_applied=[],
        )

        async with AsyncSessionLocal() as session:
            repo = AttendanceRepository(session, organization_id=self.organization_id)
            settings = await repo.get_settings()
            service = AttendanceService(
                repo,
                face_recognizer=face_recognizer,
                ws_manager=None,
            )

            active_schedule = None
            group_row = None
            camera_online = True
            try:
                active_schedule = await SmartAttendanceEngine.find_active_schedule(
                    session,
                    group_id=group_context.group_id,
                    camera_id=config.camera_id,
                    organization_id=self.organization_id,
                )
                group_row = await repo.get_group(group_context.group_id)
                if config.camera_id:
                    if CctvMonitorService.get_simulated_fault(config.camera_id):
                        camera_online = False
                    else:
                        cam_res = await session.execute(
                            select(CctvCamera).where(CctvCamera.id == config.camera_id)
                        )
                        cam_obj = cam_res.scalar_one_or_none()
                        if cam_obj is not None and cam_obj.status not in (
                            "online",
                            "recovering",
                        ):
                            camera_online = False
            except Exception as ctx_err:
                logger.debug("[LiveStreamService] Schedule/camera context skipped: %s", ctx_err)

            today_str = _today_str()
            now_dt = _utc_now()
            frame_seen_person_tracks: Dict[str, int] = {}

            for face in recognition_candidates:
                if not context_is_current():
                    break
                pose = self._resolve_head_pose(image, face)
                tid = face.get("track_id")
                is_fresh = id(face) in new_results_map

                if is_fresh:
                    result = new_results_map[id(face)]
                    member_info = None
                elif tid in config.track_recognition_cache:
                    result, member_info = config.track_recognition_cache[tid]
                else:
                    result = {"person_id": None, "similarity": 0.0, "success": False}
                    member_info = None

                original_person_id = result.get("person_id")
                if member_info is None and original_person_id:
                    member_info = group_context.members_by_person_id.get(
                        original_person_id
                    )

                # Single-point fallback on cache miss (e.g. freshly enrolled identity)
                if original_person_id and not member_info:
                    try:
                        fallback_member = await repo.get_member(original_person_id)
                        if fallback_member:
                            member_info = {
                                "name": fallback_member.name,
                                "role": fallback_member.role,
                            }
                            group_context.members_by_person_id[original_person_id] = (
                                member_info
                            )
                            group_context.allowed_person_ids.add(original_person_id)
                    except Exception as fallback_err:
                        logger.debug(
                            "[LiveStreamService] Fallback lookup error for %s: %s",
                            original_person_id,
                            fallback_err,
                        )

                # Cache fresh inference result for tracked faces
                if is_fresh and tid is not None and tid >= 0:
                    config.track_recognition_cache[tid] = (result, member_info)
                    config.track_last_sampled_frame[tid] = config.frame_counter

                serialized_result = self._serialize_recognition_result(
                    result, member_info
                )
                face["recognition"] = serialized_result

                if (
                    original_person_id
                    and liveness_detector
                    and face.get("track_id") is not None
                ):
                    face["liveness"] = liveness_detector.update_face_identity(
                        track_id=face["track_id"],
                        person_id=original_person_id,
                        current_liveness=face.get("liveness", {}),
                        namespace=client_id,
                    )

                # Accumulate temporal track evidence for smart classification
                track_key = (
                    int(tid)
                    if (tid is not None and int(tid) >= 0)
                    else -(abs(id(face)) % 1_000_000)
                )
                track_state: Optional[TrackObservationState] = None
                similarity_val = float(
                    result.get("similarity")
                    or result.get("confidence")
                    or face.get("confidence")
                    or 0.0
                )
                if tid is not None and int(tid) >= 0:
                    config.smart_accumulator.unique_track_ids.add(track_key)
                    track_state = config.smart_accumulator.tracks.get(track_key)
                    if track_state is None:
                        track_state = TrackObservationState(
                            track_id=track_key,
                            first_seen_at=now_dt,
                            last_seen_at=now_dt,
                        )
                        config.smart_accumulator.tracks[track_key] = track_state
                    crop_bytes = (
                        _encode_face_crop(image, face.get("bbox", {}))
                        if (active_schedule is not None or config.camera_id or quality_report is not None)
                        else None
                    )
                    track_state.record_observation(
                        now=now_dt,
                        quality_score=effective_quality.score,
                        pose=pose,
                        person_id=original_person_id,
                        similarity=similarity_val,
                        crop_bytes=crop_bytes,
                        face_dict=face,
                    )

                duplicate_flagged = bool(
                    track_state and track_state.duplicate_conflict_flagged
                )
                if original_person_id:
                    if (
                        original_person_id in frame_seen_person_tracks
                        and frame_seen_person_tracks[original_person_id] != track_key
                    ):
                        duplicate_flagged = True
                        config.smart_accumulator.duplicate_alerts += 1
                    else:
                        frame_seen_person_tracks[original_person_id] = track_key

                # Quality / camera health guard: never wrongly mark present or absent
                if (quality_report is not None and quality_report.status == "red") or not camera_online:
                    if track_state is not None:
                        config.smart_accumulator.pending_track_ids.add(track_key)
                    if original_person_id and (active_schedule is not None or config.camera_id):
                        try:
                            member = await repo.get_member(original_person_id)
                            if member:
                                cls_status, cls_reason = (
                                    SmartAttendanceEngine.compute_centralized_classification(
                                        recognition_confidence=similarity_val,
                                        image_quality=effective_quality,
                                        visibility_score=pose.visibility_score,
                                        temporal_consistency=1.0,
                                        observations_count=(
                                            track_state.observations_count if track_state else 1
                                        ),
                                        pose_ok=pose.pose_ok,
                                        is_registered=True,
                                        section_matched=True,
                                        has_exception=False,
                                        camera_online=camera_online,
                                        duplicate_flagged=duplicate_flagged,
                                        non_biometric_opt_out=False,
                                    )
                                )
                                first_seen = track_state.first_seen_at if track_state else now_dt
                                last_seen = track_state.last_seen_at if track_state else now_dt
                                rule_status, dur_mins = SmartAttendanceEngine.evaluate_entry_exit_rule(
                                    first_seen_at=first_seen,
                                    last_seen_at=last_seen,
                                    schedule=active_schedule,
                                    group=group_row,
                                    classification=cls_status,
                                )
                                await SmartAttendanceEngine.upsert_smart_evaluation(
                                    session,
                                    schedule_id=active_schedule.id if active_schedule else None,
                                    group_id=group_context.group_id,
                                    camera_id=config.camera_id,
                                    date_str=today_str,
                                    member_id=member.id,
                                    person_id=member.person_id,
                                    tracking_id=str(track_key),
                                    expected_section=active_schedule.section if active_schedule else None,
                                    detected_section=None,
                                    classification=cls_status,
                                    attendance_rule_status=rule_status,
                                    recognition_confidence=similarity_val,
                                    image_quality_score=effective_quality.score,
                                    face_visibility_score=pose.visibility_score,
                                    temporal_consistency_score=1.0,
                                    head_pose_ok=pose.pose_ok,
                                    duplicate_flagged=duplicate_flagged,
                                    first_seen_at=first_seen,
                                    last_seen_at=last_seen,
                                    estimated_duration_minutes=dur_mins,
                                    observations_count=(
                                        track_state.observations_count if track_state else 1
                                    ),
                                    reason=cls_reason,
                                    organization_id=self.organization_id,
                                )
                                smart_dirty = True
                        except Exception as pend_err:
                            logger.debug("[LiveStreamService] Pending quality save skipped: %s", pend_err)
                    continue

                # Unregistered / unknown individual capture & alert queue
                if not original_person_id:
                    liveness_ok_for_unknown = (
                        not config.enable_liveness_detection
                        or (face.get("liveness") or {}).get("status") == "real"
                    )
                    if (
                        (active_schedule is not None or config.camera_id or quality_report is not None)
                        and track_state is not None
                        and track_state.observations_count >= LIVE_RECOGNITION_SAMPLE_INTERVAL + 1
                        and not track_state.candidate_votes
                        and pose.pose_ok
                        and liveness_ok_for_unknown
                        and not track_state.unknown_logged
                    ):
                        try:
                            emb = None
                            if hasattr(face_recognizer, "_extract_embeddings"):
                                emb_list = await face_recognizer._extract_embeddings(
                                    image, [face]
                                )
                                if emb_list and emb_list[0] is not None:
                                    emb = emb_list[0]
                            unk_tracking_id = f"UNK-{track_key}-{int(now_ts)}"
                            unk_rec = await SmartAttendanceEngine.record_unknown_student_detection(
                                session,
                                tracking_id=unk_tracking_id,
                                camera_id=config.camera_id,
                                schedule_id=active_schedule.id if active_schedule else None,
                                group_id=group_context.group_id,
                                classroom=active_schedule.classroom if active_schedule else None,
                                crop_bytes=track_state.best_crop_bytes,
                                embedding=emb,
                                confidence_best_guess=float(result.get("similarity") or 0.0),
                                organization_id=self.organization_id,
                            )
                            await SmartAttendanceEngine.upsert_smart_evaluation(
                                session,
                                schedule_id=active_schedule.id if active_schedule else None,
                                group_id=group_context.group_id,
                                camera_id=config.camera_id,
                                date_str=today_str,
                                member_id=None,
                                person_id=None,
                                tracking_id=unk_tracking_id,
                                expected_section=active_schedule.section if active_schedule else None,
                                detected_section=None,
                                classification="unknown_student",
                                attendance_rule_status="pending_verification",
                                recognition_confidence=float(result.get("similarity") or 0.0),
                                image_quality_score=effective_quality.score,
                                face_visibility_score=pose.visibility_score,
                                temporal_consistency_score=1.0,
                                head_pose_ok=pose.pose_ok,
                                duplicate_flagged=False,
                                first_seen_at=track_state.first_seen_at,
                                last_seen_at=track_state.last_seen_at,
                                estimated_duration_minutes=0.0,
                                observations_count=track_state.observations_count,
                                reason="Unregistered student detected; identity verification required.",
                                organization_id=self.organization_id,
                            )
                            track_state.unknown_logged = True
                            config.smart_accumulator.unknown_track_ids.add(track_key)
                            smart_dirty = True
                            attendance_messages.append(
                                {
                                    "type": "cctv_alert",
                                    "alert_type": "unknown_student",
                                    "severity": "warning",
                                    "detection_id": unk_rec.id,
                                    "tracking_id": unk_tracking_id,
                                    "camera_id": config.camera_id,
                                    "group_id": config.active_group_id,
                                    "message": "UNREGISTERED STUDENT DETECTED – Identity verification required.",
                                    "timestamp": now_ts,
                                }
                            )
                        except Exception as unk_err:
                            logger.warning(
                                "[LiveStreamService] Unknown student alert error: %s",
                                unk_err,
                            )
                    continue

                if (
                    serialized_result["person_id"] == PROTECTED_IDENTITY
                    or not self._is_attendance_allowed(face, config)
                ):
                    continue

                try:
                    member = await repo.get_member(original_person_id)
                    if not context_is_current():
                        break
                    if not member:
                        continue

                    val = await SmartAttendanceEngine.validate_member_for_schedule(
                        session,
                        member=member,
                        schedule=active_schedule,
                        date_str=today_str,
                        organization_id=self.organization_id,
                    )

                    if track_state is not None and active_schedule is not None:
                        best_pid, mean_sim, consistency = track_state.summary()
                        eff_conf = max(similarity_val, mean_sim)
                        eff_obs = track_state.observations_count
                        first_seen = track_state.first_seen_at
                        last_seen = track_state.last_seen_at
                    else:
                        eff_conf = max(similarity_val, float(face.get("confidence") or 0.0))
                        consistency = 1.0
                        eff_obs = (
                            track_state.observations_count
                            if track_state is not None
                            else SmartAttendanceEngine.MIN_TEMPORAL_OBSERVATIONS
                        )
                        first_seen = track_state.first_seen_at if track_state else now_dt
                        last_seen = track_state.last_seen_at if track_state else now_dt

                    classification, cls_reason = (
                        SmartAttendanceEngine.compute_centralized_classification(
                            recognition_confidence=eff_conf,
                            image_quality=effective_quality,
                            visibility_score=pose.visibility_score,
                            temporal_consistency=consistency,
                            observations_count=eff_obs,
                            pose_ok=pose.pose_ok,
                            is_registered=True,
                            section_matched=val["section_matched"],
                            has_exception=val["has_exception"],
                            camera_online=camera_online,
                            duplicate_flagged=duplicate_flagged,
                            non_biometric_opt_out=val["non_biometric_opt_out"],
                        )
                    )

                    # Preserve single-frame standard Facenox behavior when no schedule/CCTV camera is bound
                    # (still enforcing red image-quality blocks and non-biometric opt-out).
                    if (
                        active_schedule is None
                        and config.camera_id is None
                        and effective_quality.status != "red"
                        and not val["non_biometric_opt_out"]
                    ):
                        classification = "cctv_verified_present"
                        cls_reason = "Standard live recognition match."

                    rule_status, dur_mins = SmartAttendanceEngine.evaluate_entry_exit_rule(
                        first_seen_at=first_seen,
                        last_seen_at=last_seen,
                        schedule=active_schedule,
                        group=group_row,
                        classification=classification,
                    )

                    if classification == "section_mismatch" and active_schedule is not None:
                        config.smart_accumulator.mismatch_person_ids.add(original_person_id)
                        face["recognition"]["section_mismatch"] = True
                        face["recognition"]["actual_section"] = val["detected_section"]
                        if track_state is None or not track_state.mismatch_logged:
                            if val["profile"] is not None:
                                await SmartAttendanceEngine.record_section_mismatch(
                                    session,
                                    member=member,
                                    profile=val["profile"],
                                    schedule=active_schedule,
                                    camera_id=config.camera_id,
                                    organization_id=self.organization_id,
                                )
                            await SmartAttendanceEngine.upsert_smart_evaluation(
                                session,
                                schedule_id=active_schedule.id,
                                group_id=group_context.group_id,
                                camera_id=config.camera_id,
                                date_str=today_str,
                                member_id=member.id,
                                person_id=member.person_id,
                                tracking_id=str(track_key),
                                expected_section=val["expected_section"],
                                detected_section=val["detected_section"],
                                classification="section_mismatch",
                                attendance_rule_status="pending_verification",
                                recognition_confidence=eff_conf,
                                image_quality_score=effective_quality.score,
                                face_visibility_score=pose.visibility_score,
                                temporal_consistency_score=consistency,
                                head_pose_ok=pose.pose_ok,
                                duplicate_flagged=duplicate_flagged,
                                first_seen_at=first_seen,
                                last_seen_at=last_seen,
                                estimated_duration_minutes=dur_mins,
                                observations_count=eff_obs,
                                reason=cls_reason,
                                organization_id=self.organization_id,
                            )
                            smart_dirty = True
                            if track_state is not None:
                                track_state.mismatch_logged = True
                            attendance_messages.append(
                                {
                                    "type": "cctv_alert",
                                    "alert_type": "section_mismatch",
                                    "severity": "warning",
                                    "person_id": member.person_id,
                                    "student_name": member.name,
                                    "actual_section": val["detected_section"],
                                    "scheduled_section": val["expected_section"],
                                    "camera_id": config.camera_id,
                                    "group_id": config.active_group_id,
                                    "message": (
                                        f"Unassigned Section Detection: {member.name} "
                                        f"({val['detected_section']}) detected in {val['expected_section']}."
                                    ),
                                    "timestamp": now_ts,
                                }
                            )
                        continue

                    if classification != "cctv_verified_present":
                        config.smart_accumulator.pending_track_ids.add(track_key)
                        if (active_schedule is not None or quality_report is not None) and (
                            track_state is None or now_ts - track_state.last_persisted_at >= 1.5
                        ):
                            await SmartAttendanceEngine.upsert_smart_evaluation(
                                session,
                                schedule_id=active_schedule.id if active_schedule else None,
                                group_id=group_context.group_id,
                                camera_id=config.camera_id,
                                date_str=today_str,
                                member_id=member.id,
                                person_id=member.person_id,
                                tracking_id=str(track_key),
                                expected_section=val["expected_section"],
                                detected_section=val["detected_section"],
                                classification=classification,
                                attendance_rule_status=rule_status,
                                recognition_confidence=eff_conf,
                                image_quality_score=effective_quality.score,
                                face_visibility_score=pose.visibility_score,
                                temporal_consistency_score=consistency,
                                head_pose_ok=pose.pose_ok,
                                duplicate_flagged=duplicate_flagged,
                                first_seen_at=first_seen,
                                last_seen_at=last_seen,
                                estimated_duration_minutes=dur_mins,
                                observations_count=eff_obs,
                                reason=cls_reason,
                                organization_id=self.organization_id,
                            )
                            smart_dirty = True
                            if track_state is not None:
                                track_state.last_persisted_at = now_ts
                        continue

                    if track_state is not None:
                        track_state.confirmed_person_id = original_person_id
                    config.smart_accumulator.confirmed_person_ids.add(original_person_id)
                    config.smart_accumulator.unknown_track_ids.discard(track_key)
                    config.smart_accumulator.pending_track_ids.discard(track_key)

                    # Camera throttle: debounce rapid frame re-evaluations for the same recognized face
                    cooldown_seconds = 5.0
                    cooldown_key = f"{original_person_id}:{group_context.group_id}"
                    now = time.time()
                    if (
                        now - config.attendance_cooldowns.get(cooldown_key, 0.0)
                        < cooldown_seconds
                    ):
                        continue

                    if active_schedule is not None or quality_report is not None:
                        await SmartAttendanceEngine.upsert_smart_evaluation(
                            session,
                            schedule_id=active_schedule.id if active_schedule else None,
                            group_id=group_context.group_id,
                            camera_id=config.camera_id,
                            date_str=today_str,
                            member_id=member.id,
                            person_id=member.person_id,
                            tracking_id=str(track_key),
                            expected_section=val["expected_section"],
                            detected_section=val["detected_section"],
                            classification="cctv_verified_present",
                            attendance_rule_status=rule_status,
                            recognition_confidence=eff_conf,
                            image_quality_score=effective_quality.score,
                            face_visibility_score=pose.visibility_score,
                            temporal_consistency_score=consistency,
                            head_pose_ok=pose.pose_ok,
                            duplicate_flagged=duplicate_flagged,
                            first_seen_at=first_seen,
                            last_seen_at=last_seen,
                            estimated_duration_minutes=dur_mins,
                            observations_count=eff_obs,
                            reason=cls_reason,
                            organization_id=self.organization_id,
                        )
                        smart_dirty = True

                    event_result = await service.process_event(
                        AttendanceEventCreate(
                            person_id=original_person_id,
                            confidence=float(face.get("confidence") or 0.0),
                            location="LiveVideo Camera",
                            liveness_status=(face.get("liveness") or {}).get("status"),
                            liveness_confidence=(face.get("liveness") or {}).get(
                                "confidence"
                            ),
                            device_id=config.device_id or config.client_id,
                            scan_behavior=config.scan_behavior,
                        ),
                        member,
                        settings,
                    )
                    if not context_is_current():
                        await session.rollback()
                        break
                    if event_result.processed:
                        await session.commit()
                        smart_dirty = False
                        config.attendance_cooldowns[cooldown_key] = now
                        attendance_messages.append(
                            self._build_attendance_message(
                                event_result, member_info or {}, face
                            )
                        )
                    else:
                        config.attendance_cooldowns[cooldown_key] = now
                except Exception as exc:
                    logger.warning(
                        "[LiveStreamService] Live attendance processing failed for %s: %s",
                        original_person_id,
                        exc,
                    )

            if smart_dirty and context_is_current():
                try:
                    await session.commit()
                except Exception:
                    await session.rollback()

            config.last_headcount_summary = self._build_live_frame_headcount_summary(
                faces,
                config=config,
                group_context=group_context,
                quality_report=quality_report,
            )

        if not context_is_current():
            config.invalidate()
            for face in recognition_candidates:
                face.pop("recognition", None)
        return attendance_messages
