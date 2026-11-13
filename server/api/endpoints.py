"""
API Router Aggregator
Combines all API route modules into a single router
"""

from fastapi import APIRouter

from api.routes import detection, recognition, websocket, attendance, backup, cctv, vlaser, recordings

router = APIRouter()

router.include_router(detection.router, tags=["detection"])
router.include_router(recognition.router, tags=["recognition"])
router.include_router(websocket.router, tags=["websocket"])
router.include_router(attendance.router, tags=["attendance"])
router.include_router(backup.router, tags=["backup"])
router.include_router(cctv.router, tags=["cctv"])
router.include_router(vlaser.router, tags=["vlaser"])
router.include_router(recordings.router, tags=["recordings"])

__all__ = ["router"]
