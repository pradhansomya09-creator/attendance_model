"""Mobile IP / RTSP / HTTP MJPEG Stream Resolver, Probe, Worker, and Health Service.

Supports Android IP Webcam (port 8080), DroidCam (port 4747), generic RTSP/MJPEG streams,
and provides background frame retrieval, connection verification, automatic reconnection,
health monitoring (8 states), freeze detection, and attendance safety guards.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import threading
import time
from enum import Enum
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import cv2
import httpx
import numpy as np

logger = logging.getLogger(__name__)

SUPPORTED_SCHEMES = {"http", "https", "rtsp", "rtsps"}
DEFAULT_PORTS = {"http": 80, "https": 443, "rtsp": 554, "rtsps": 322}


class CameraHealthStatus(str, Enum):
    """Camera operational states for health monitoring and attendance safety."""

    CONNECTED = "CONNECTED"
    CONNECTING = "CONNECTING"
    DISCONNECTED = "DISCONNECTED"
    NO_FRAMES_RECEIVED = "NO_FRAMES_RECEIVED"
    STREAM_FROZEN = "STREAM_FROZEN"
    LOW_FRAME_RATE = "LOW_FRAME_RATE"
    RECONNECTING = "RECONNECTING"
    CAMERA_ERROR = "CAMERA_ERROR"


def get_local_host_ips() -> List[str]:
    """Retrieve all non-loopback IPv4 addresses of this host PC."""
    ips: List[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except Exception:
        pass

    # Fallback probe via dummy UDP connect
    if not ips:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                if ip and not ip.startswith("127."):
                    ips.append(ip)
        except Exception:
            pass

    return ips or ["127.0.0.1"]


def check_subnet_compatibility(camera_host: str) -> Dict[str, Any]:
    """Check whether camera host IP is on the same subnet as any local network interface."""
    local_ips = get_local_host_ips()

    if camera_host.startswith("192.0.0."):
        return {
            "compatible": False,
            "host_ips": local_ips,
            "camera_ip": camera_host,
            "error_type": "cellular_clat",
            "message": (
                f"'{camera_host}' is an internal Android cellular (CLAT/464XLAT) interface "
                "and cannot be reached over Wi-Fi. Turn OFF Mobile Data on the phone, restart "
                "IP Webcam to view your real Wi-Fi IP (usually 192.168.x.x or 10.x.x.x), or turn on Mobile Hotspot."
            ),
        }

    # If camera host is loopback/localhost
    if camera_host in ("127.0.0.1", "localhost"):
        return {
            "compatible": True,
            "host_ips": local_ips,
            "camera_ip": camera_host,
            "error_type": None,
            "message": "Localhost loopback address.",
        }

    try:
        cam_ip_obj = ipaddress.ip_address(camera_host)
    except ValueError:
        # Non-IP hostname
        return {
            "compatible": True,
            "host_ips": local_ips,
            "camera_ip": camera_host,
            "error_type": None,
            "message": f"Host '{camera_host}' will be resolved via DNS.",
        }

    # Check /24 subnet match against all local interfaces
    matching_interface = None
    for lip in local_ips:
        try:
            local_net = ipaddress.ip_network(f"{lip}/24", strict=False)
            if cam_ip_obj in local_net:
                matching_interface = lip
                break
        except Exception:
            continue

    if matching_interface is not None:
        return {
            "compatible": True,
            "host_ips": local_ips,
            "camera_ip": camera_host,
            "matched_host_ip": matching_interface,
            "error_type": None,
            "message": f"Camera and host PC are on the same subnet ({matching_interface}/24).",
        }

    # Subnet mismatch detected
    primary_host = local_ips[0] if local_ips else "Unknown"
    return {
        "compatible": False,
        "host_ips": local_ips,
        "camera_ip": camera_host,
        "matched_host_ip": None,
        "error_type": "subnet_mismatch",
        "message": (
            f"Network subnet mismatch: Host PC is on {primary_host}, but camera is on {camera_host}. "
            "Ensure both phone and computer are connected to the exact same Wi-Fi network (or connect PC to the phone's Wi-Fi Hotspot)."
        ),
    }


def validate_ip_stream_url(raw_url: str) -> str:
    """Normalize and validate a user-entered mobile IP / RTSP stream URL."""
    cleaned = (raw_url or "").strip()
    if not cleaned:
        raise ValueError("Please enter a mobile IP address or camera stream URL.")
    if any(ch.isspace() for ch in cleaned):
        raise ValueError("Stream URL cannot contain whitespace.")

    if "://" not in cleaned:
        cleaned = f"http://{cleaned}"

    parsed = urlparse(cleaned)
    scheme = (parsed.scheme or "").lower()
    if scheme not in SUPPORTED_SCHEMES:
        raise ValueError(
            f"Unsupported stream protocol '{scheme}'. Use http://, https://, or rtsp://."
        )
    if not parsed.hostname:
        raise ValueError("Invalid camera address: missing host or IP.")

    subnet_info = check_subnet_compatibility(parsed.hostname)
    if not subnet_info["compatible"] and subnet_info.get("error_type") == "cellular_clat":
        raise ValueError(subnet_info["message"])

    return urlunparse(
        (
            scheme,
            parsed.netloc,
            parsed.path or "",
            parsed.params or "",
            parsed.query or "",
            "",
        )
    )


def build_candidate_urls(normalized_url: str) -> List[str]:
    """Expand a bare IP:port URL into common mobile IP camera stream paths."""
    parsed = urlparse(normalized_url)
    scheme = parsed.scheme.lower()
    path = parsed.path or ""

    if scheme in ("rtsp", "rtsps"):
        return [normalized_url]

    if path not in ("", "/"):
        return [normalized_url]

    base = urlunparse((scheme, parsed.netloc, "", "", "", ""))
    return [
        f"{base}/video",        # IP Webcam (Android) default MJPEG stream
        f"{base}/videostream",  # IP Webcam alternate path
        f"{base}/mjpegfeed",    # Alfred / generic MJPEG
        f"{base}/videofeed",    # generic MJPEG alias
        f"{base}/stream",       # generic alias
        f"{base}/shot.jpg",     # IP Webcam snapshot fallback
        normalized_url,         # bare root
    ]


def _decode_jpeg_dimensions(jpeg_bytes: bytes) -> Optional[Tuple[int, int]]:
    arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        return None
    h, w = img.shape[:2]
    return (w, h)


def _check_tcp_reachable(url: str, timeout: float = 2.0) -> Tuple[bool, Optional[str]]:
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False, "Missing IP address or hostname."
    port = parsed.port or DEFAULT_PORTS.get(parsed.scheme.lower(), 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except socket.timeout:
        return (
            False,
            f"Connection timed out reaching {host}:{port} ({timeout}s). The camera device is either unreachable, powered off, or blocked by Wi-Fi isolation.",
        )
    except ConnectionRefusedError:
        return (
            False,
            f"Port {port} on {host} is closed or rejected connection. Ensure IP Webcam or camera app is running and 'Start server' has been tapped.",
        )
    except OSError as exc:
        return (
            False,
            f"Cannot reach {host}:{port} ({exc}). Verify phone and PC are on the same Wi-Fi network.",
        )


def _extract_first_http_jpeg(url: str) -> Optional[Tuple[int, int, str]]:
    """Probe an HTTP/HTTPS snapshot or MJPEG stream directly with httpx."""
    try:
        with httpx.Client(timeout=3.0, follow_redirects=True) as client:
            if url.lower().endswith("/shot.jpg"):
                resp = client.get(url)
                if resp.status_code == 200 and resp.content:
                    dims = _decode_jpeg_dimensions(resp.content)
                    if dims:
                        return dims[0], dims[1], "snapshot"
                return None

            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                content_type = (resp.headers.get("content-type") or "").lower()
                if "text/html" in content_type or "application/json" in content_type:
                    return None

                buf = bytearray()
                for chunk in resp.iter_bytes(chunk_size=16384):
                    if not chunk:
                        continue
                    buf.extend(chunk)
                    soi = buf.find(b"\xff\xd8")
                    if soi != -1:
                        eoi = buf.find(b"\xff\xd9", soi + 2)
                        if eoi != -1:
                            frame_bytes = bytes(buf[soi : eoi + 2])
                            dims = _decode_jpeg_dimensions(frame_bytes)
                            if dims:
                                mode = (
                                    "snapshot"
                                    if content_type.startswith("image/jpeg")
                                    else "mjpeg"
                                )
                                return dims[0], dims[1], mode
                    if len(buf) > 4 * 1024 * 1024:
                        break
    except Exception:
        return None
    return None


def _try_open_capture_frame(url: str) -> Optional[Tuple[int, int, str]]:
    """Probe stream via HTTP JPEG/MJPEG parser or OpenCV VideoCapture."""
    lower = url.lower()
    if lower.startswith("http://") or lower.startswith("https://"):
        http_probe = _extract_first_http_jpeg(url)
        if http_probe is not None:
            return http_probe
        if lower.endswith("/shot.jpg"):
            return None

    cap = cv2.VideoCapture(url)
    try:
        if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 2500)
        if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 2500)
        if not cap.isOpened():
            return None
        ok, frame = cap.read()
        if not ok or frame is None or frame.size == 0:
            return None
        h, w = frame.shape[:2]
        return w, h, "mjpeg"
    finally:
        cap.release()


def verify_camera_connectivity(raw_url: str) -> Dict[str, Any]:
    """Perform comprehensive multi-stage camera connectivity verification.

    1. URL normalization and protocol validation.
    2. Subnet and cellular CLAT detection.
    3. TCP port reachability probe.
    4. Stream endpoint resolution and frame decode test.
    """
    try:
        normalized = validate_ip_stream_url(raw_url)
    except ValueError as exc:
        return {
            "ok": False,
            "stage": "validation",
            "status": CameraHealthStatus.CAMERA_ERROR.value,
            "error": str(exc),
            "diagnostics": {
                "raw_url": raw_url,
                "reachable": False,
                "port_accessible": False,
            },
        }

    parsed = urlparse(normalized)
    host = parsed.hostname or ""
    port = parsed.port or DEFAULT_PORTS.get(parsed.scheme.lower(), 80)
    subnet_info = check_subnet_compatibility(host)

    # TCP reachability check
    tcp_ok, tcp_err = _check_tcp_reachable(normalized, timeout=2.0)
    if not tcp_ok:
        return {
            "ok": False,
            "stage": "reachability",
            "status": CameraHealthStatus.DISCONNECTED.value,
            "error": tcp_err or f"Cannot connect to {host}:{port}",
            "diagnostics": {
                "normalized_url": normalized,
                "camera_ip": host,
                "camera_port": port,
                "host_ips": subnet_info.get("host_ips", []),
                "subnet_match": subnet_info.get("compatible", False),
                "reachable": False,
                "port_accessible": False,
                "hint": subnet_info.get("message"),
            },
        }

    # Endpoint probe
    candidates = build_candidate_urls(normalized)
    for candidate in candidates:
        res = _try_open_capture_frame(candidate)
        if res is not None:
            w, h, mode = res
            return {
                "ok": True,
                "stage": "connected",
                "status": CameraHealthStatus.CONNECTED.value,
                "resolved_url": candidate,
                "width": w,
                "height": h,
                "mode": mode,
                "message": f"Connected to camera at {host}:{port} ({w}x{h}, {mode}).",
                "diagnostics": {
                    "normalized_url": normalized,
                    "resolved_url": candidate,
                    "camera_ip": host,
                    "camera_port": port,
                    "host_ips": subnet_info.get("host_ips", []),
                    "subnet_match": subnet_info.get("compatible", False),
                    "reachable": True,
                    "port_accessible": True,
                    "frame_decoded": True,
                    "resolution": f"{w}x{h}",
                },
            }

    # Port was reachable, but no video stream detected on any candidate endpoint
    return {
        "ok": False,
        "stage": "streaming_endpoint",
        "status": CameraHealthStatus.NO_FRAMES_RECEIVED.value,
        "error": (
            f"Reached {host}:{port}, but no video stream was found on common endpoints (/video, /videostream, /shot.jpg). "
            "Make sure 'Start server' has been tapped inside the IP Webcam app."
        ),
        "diagnostics": {
            "normalized_url": normalized,
            "camera_ip": host,
            "camera_port": port,
            "host_ips": subnet_info.get("host_ips", []),
            "subnet_match": subnet_info.get("compatible", False),
            "reachable": True,
            "port_accessible": True,
            "frame_decoded": False,
            "candidates_tested": candidates,
        },
    }


async def probe_ip_stream(raw_url: str) -> Dict[str, Any]:
    """Async wrapper around verify_camera_connectivity for API endpoints."""
    result = await asyncio.to_thread(verify_camera_connectivity, raw_url)
    if not result["ok"]:
        raise ValueError(result.get("error") or "Camera connection failed.")
    return result


class IpCameraStreamWorker:
    """Asynchronous background worker for camera frame retrieval, health monitoring,

    freeze detection, and automatic reconnection.

    Guarantees:
    - Non-blocking frame retrieval.
    - Continuous health status tracking across 8 CameraHealthStatus states.
    - Detects frozen streams using visual difference and timestamp thresholds.
    - Automatic exponential backoff reconnection (1s, 2s, 4s, 8s, up to 15s).
    - Attendance safety: `get_valid_attendance_frame()` returns None on frozen or stale frames.
    - Preserves existing verified attendance without creating false records.
    """

    def __init__(self, raw_url: str, camera_id: Optional[str] = None):
        self.raw_url = raw_url
        self.camera_id = camera_id
        self.resolved_url: Optional[str] = None
        self.status: CameraHealthStatus = CameraHealthStatus.CONNECTING
        self.is_running = False

        # Frame buffers and synchronization
        self._lock = threading.Lock()
        self._latest_frame: Optional[np.ndarray] = None
        self._latest_jpeg: Optional[bytes] = None
        self._prev_frame_gray: Optional[np.ndarray] = None
        self._last_frame_time: float = 0.0
        self._last_active_change_time: float = 0.0
        self._consecutive_identical_frames = 0

        # Telemetry & metrics
        self.reconnect_attempts = 0
        self.last_error: Optional[str] = None
        self.fps: float = 0.0
        self.latency_ms: float = 0.0
        self._frame_timestamps: List[float] = []

        # Thread handle
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name=f"IpCamWorker-{self.camera_id or 'anon'}", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self.is_running = False
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.status = CameraHealthStatus.DISCONNECTED

    def get_latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_valid_attendance_frame(self) -> Optional[np.ndarray]:
        """Attendance Safety Gate: Returns a valid frame ONLY if the camera is healthy.

        Returns None if:
        - Stream is frozen (STREAM_FROZEN)
        - Camera is disconnected (DISCONNECTED / RECONNECTING)
        - No frames received within threshold (> 4.0 seconds)
        """
        now = time.monotonic()
        with self._lock:
            if self.status in (
                CameraHealthStatus.DISCONNECTED,
                CameraHealthStatus.RECONNECTING,
                CameraHealthStatus.STREAM_FROZEN,
                CameraHealthStatus.CAMERA_ERROR,
                CameraHealthStatus.NO_FRAMES_RECEIVED,
            ):
                return None

            if self._last_frame_time == 0 or (now - self._last_frame_time) > 4.0:
                return None

            if self._latest_frame is None:
                return None

            return self._latest_frame.copy()

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return real-time diagnostic payload for faculty UI."""
        with self._lock:
            now = time.monotonic()
            last_frame_age = round(now - self._last_frame_time, 2) if self._last_frame_time > 0 else None
            parsed = urlparse(self.resolved_url or self.raw_url)
            host = parsed.hostname or ""
            port = parsed.port or DEFAULT_PORTS.get(parsed.scheme.lower(), 80)
            subnet_info = check_subnet_compatibility(host)

            return {
                "camera_id": self.camera_id,
                "raw_url": self.raw_url,
                "resolved_url": self.resolved_url,
                "status": self.status.value,
                "camera_ip": host,
                "camera_port": port,
                "host_ips": subnet_info.get("host_ips", []),
                "subnet_compatible": subnet_info.get("compatible", False),
                "fps": round(self.fps, 1),
                "latency_ms": round(self.latency_ms, 1),
                "last_frame_age_seconds": last_frame_age,
                "reconnect_attempts": self.reconnect_attempts,
                "last_error": self.last_error,
                "is_frozen": self.status == CameraHealthStatus.STREAM_FROZEN,
                "safe_for_attendance": (
                    self.status in (CameraHealthStatus.CONNECTED, CameraHealthStatus.LOW_FRAME_RATE)
                    and last_frame_age is not None
                    and last_frame_age < 3.5
                ),
            }

    def _update_fps(self, now: float) -> None:
        self._frame_timestamps.append(now)
        cutoff = now - 2.0
        self._frame_timestamps = [t for t in self._frame_timestamps if t >= cutoff]
        if len(self._frame_timestamps) > 1:
            duration = self._frame_timestamps[-1] - self._frame_timestamps[0]
            if duration > 0.05:
                self.fps = (len(self._frame_timestamps) - 1) / duration

    def _check_frame_frozen(self, current_bgr: np.ndarray, now: float) -> bool:
        """Visual freeze detection using image difference between successive frames."""
        gray = cv2.cvtColor(current_bgr, cv2.COLOR_BGR2GRAY)
        if self._prev_frame_gray is None:
            self._prev_frame_gray = gray
            self._last_active_change_time = now
            return False

        if gray.shape != self._prev_frame_gray.shape:
            self._prev_frame_gray = gray
            self._last_active_change_time = now
            return False

        diff = cv2.absdiff(gray, self._prev_frame_gray)
        mean_diff = float(np.mean(diff))
        self._prev_frame_gray = gray

        # If difference is negligible (< 0.25 on a 0-255 scale)
        if mean_diff < 0.25:
            self._consecutive_identical_frames += 1
            if now - self._last_active_change_time > 3.0:
                return True
        else:
            self._consecutive_identical_frames = 0
            self._last_active_change_time = now

        return False

    def _store_frame(self, frame: np.ndarray, read_latency_ms: float) -> None:
        now = time.monotonic()
        is_frozen = self._check_frame_frozen(frame, now)

        with self._lock:
            self._latest_frame = frame
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            if ok:
                self._latest_jpeg = bytes(buf)
            self._last_frame_time = now
            self.latency_ms = read_latency_ms
            self._update_fps(now)

            if is_frozen:
                self.status = CameraHealthStatus.STREAM_FROZEN
            elif self.fps > 0 and self.fps < 6.0:
                self.status = CameraHealthStatus.LOW_FRAME_RATE
            else:
                self.status = CameraHealthStatus.CONNECTED

    def _run_loop(self) -> None:
        backoff_delays = [1.0, 2.0, 4.0, 8.0, 15.0]

        while not self._stop_event.is_set():
            # 1. Resolve and probe
            with self._lock:
                self.status = (
                    CameraHealthStatus.RECONNECTING
                    if self.reconnect_attempts > 0
                    else CameraHealthStatus.CONNECTING
                )

            verification = verify_camera_connectivity(self.raw_url)
            if not verification["ok"]:
                with self._lock:
                    self.last_error = verification.get("error")
                    self.status = CameraHealthStatus.DISCONNECTED
                    self.reconnect_attempts += 1

                delay = backoff_delays[min(self.reconnect_attempts - 1, len(backoff_delays) - 1)]
                logger.info(
                    "[IpCamWorker] Connection failed (%s). Retrying in %.1fs (attempt %d)...",
                    self.last_error,
                    delay,
                    self.reconnect_attempts,
                )
                self._stop_event.wait(delay)
                continue

            self.resolved_url = verification.get("resolved_url") or self.raw_url
            with self._lock:
                self.status = CameraHealthStatus.CONNECTED
                self.last_error = None
                self.reconnect_attempts = 0

            # 2. Frame reading loop
            try:
                self._stream_from_resolved(self.resolved_url)
            except Exception as stream_err:
                logger.warning("[IpCamWorker] Stream error on %s: %s", self.resolved_url, stream_err)
                with self._lock:
                    self.last_error = str(stream_err)
                    self.status = CameraHealthStatus.DISCONNECTED

            # Wait briefly before auto-reconnecting
            if not self._stop_event.is_set():
                self.reconnect_attempts += 1
                delay = backoff_delays[min(self.reconnect_attempts - 1, len(backoff_delays) - 1)]
                self._stop_event.wait(delay)

    def _stream_from_resolved(self, url: str) -> None:
        """Stream frames via HTTP multipart parser or OpenCV VideoCapture."""
        lower = url.lower()
        if lower.endswith("/shot.jpg"):
            self._stream_snapshot_loop(url)
            return

        if lower.startswith("http://") or lower.startswith("https://"):
            try:
                self._stream_http_mjpeg_loop(url)
                return
            except Exception as exc:
                logger.debug("[IpCamWorker] HTTP parser fell back to OpenCV: %s", exc)

        self._stream_opencv_loop(url)

    def _stream_http_mjpeg_loop(self, url: str) -> None:
        with httpx.Client(
            timeout=httpx.Timeout(connect=4.0, read=8.0, write=4.0, pool=4.0),
            follow_redirects=True,
        ) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise IOError(f"HTTP status {resp.status_code}")

                buf = bytearray()
                for chunk in resp.iter_bytes(chunk_size=16384):
                    if self._stop_event.is_set():
                        return
                    if not chunk:
                        continue
                    t0 = time.monotonic()
                    buf.extend(chunk)

                    while True:
                        soi = buf.find(b"\xff\xd8")
                        if soi == -1:
                            if len(buf) > 4:
                                del buf[:-2]
                            break
                        if soi > 0:
                            del buf[:soi]
                        eoi = buf.find(b"\xff\xd9", 2)
                        if eoi == -1:
                            if len(buf) > 8 * 1024 * 1024:
                                buf.clear()
                            break
                        jpeg_bytes = bytes(buf[: eoi + 2])
                        del buf[: eoi + 2]

                        arr = np.frombuffer(jpeg_bytes, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is not None and frame.size > 0:
                            latency_ms = (time.monotonic() - t0) * 1000.0
                            self._store_frame(frame, latency_ms)

    def _stream_snapshot_loop(self, url: str) -> None:
        with httpx.Client(timeout=3.0, follow_redirects=True) as client:
            while not self._stop_event.is_set():
                t0 = time.monotonic()
                try:
                    resp = client.get(url)
                    if resp.status_code == 200 and resp.content:
                        arr = np.frombuffer(resp.content, dtype=np.uint8)
                        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                        if frame is not None and frame.size > 0:
                            self._store_frame(frame, (time.monotonic() - t0) * 1000.0)
                except Exception as err:
                    with self._lock:
                        self.status = CameraHealthStatus.CAMERA_ERROR
                        self.last_error = str(err)
                    self._stop_event.wait(0.5)

                elapsed = time.monotonic() - t0
                target_interval = 1.0 / 15.0
                if elapsed < target_interval:
                    self._stop_event.wait(target_interval - elapsed)

    def _stream_opencv_loop(self, url: str) -> None:
        cap = cv2.VideoCapture(url)
        try:
            if hasattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 3500)
            if hasattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC"):
                cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 3500)
            if not cap.isOpened():
                raise IOError(f"OpenCV could not open stream {url}")

            while not self._stop_event.is_set():
                t0 = time.monotonic()
                ok, frame = cap.read()
                if not ok or frame is None or frame.size == 0:
                    with self._lock:
                        self.status = CameraHealthStatus.NO_FRAMES_RECEIVED
                    self._stop_event.wait(0.2)
                    continue

                latency_ms = (time.monotonic() - t0) * 1000.0
                self._store_frame(frame, latency_ms)
                self._stop_event.wait(0.01)
        finally:
            cap.release()


class CameraStreamRegistry:
    """Singleton registry tracking active camera stream workers to prevent resource leaks."""

    _workers: Dict[str, IpCameraStreamWorker] = {}
    _lock = threading.Lock()

    @classmethod
    def get_or_create(cls, raw_url: str, camera_id: Optional[str] = None) -> IpCameraStreamWorker:
        key = (raw_url or "").strip().lower()
        with cls._lock:
            if key in cls._workers:
                worker = cls._workers[key]
                if not worker.is_running:
                    worker.start()
                return worker

            worker = IpCameraStreamWorker(raw_url, camera_id=camera_id)
            worker.start()
            cls._workers[key] = worker
            return worker

    @classmethod
    def get(cls, raw_url: str) -> Optional[IpCameraStreamWorker]:
        key = (raw_url or "").strip().lower()
        with cls._lock:
            return cls._workers.get(key)

    @classmethod
    def stop(cls, raw_url: str) -> None:
        key = (raw_url or "").strip().lower()
        with cls._lock:
            worker = cls._workers.pop(key, None)
            if worker:
                worker.stop()

    @classmethod
    def stop_all(cls) -> None:
        with cls._lock:
            for worker in cls._workers.values():
                worker.stop()
            cls._workers.clear()

    @classmethod
    def reconnect_stream(cls, raw_url: str) -> Dict[str, Any]:
        """Force immediate reconnect on an existing worker."""
        key = (raw_url or "").strip().lower()
        with cls._lock:
            worker = cls._workers.get(key)
            if worker:
                worker.stop()
                worker.reconnect_attempts = 0
                worker.start()
                return worker.get_diagnostics()

        new_worker = cls.get_or_create(raw_url)
        return new_worker.get_diagnostics()

    @classmethod
    def get_diagnostics(cls, raw_url: str) -> Dict[str, Any]:
        key = (raw_url or "").strip().lower()
        with cls._lock:
            worker = cls._workers.get(key)
            if worker:
                return worker.get_diagnostics()

        # If worker is not active yet, run quick verification
        verification = verify_camera_connectivity(raw_url)
        return {
            "raw_url": raw_url,
            "status": verification.get("status", CameraHealthStatus.DISCONNECTED.value),
            "diagnostics": verification.get("diagnostics", {}),
            "fps": 0.0,
            "latency_ms": 0.0,
            "last_error": verification.get("error"),
            "safe_for_attendance": False,
        }


def _format_mjpeg_part(payload: bytes) -> bytes:
    return (
        b"--frame\r\n"
        b"Content-Type: image/jpeg\r\n"
        + f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii")
        + payload
        + b"\r\n"
    )


async def iter_mjpeg_frames(
    raw_url: str,
    is_disconnected: Callable[[], asyncio.Future | Any],
    target_fps: float = 20.0,
) -> AsyncIterator[bytes]:
    """Yield MJPEG multipart stream chunks directly from the worker buffer."""
    worker = CameraStreamRegistry.get_or_create(raw_url)
    frame_interval = 1.0 / max(1.0, target_fps)

    last_yielded_jpeg: Optional[bytes] = None
    try:
        while not await is_disconnected():
            t0 = time.monotonic()
            jpeg = worker.get_latest_jpeg()
            if jpeg is not None and jpeg != last_yielded_jpeg:
                last_yielded_jpeg = jpeg
                yield _format_mjpeg_part(jpeg)
            else:
                await asyncio.sleep(0.03)

            elapsed = time.monotonic() - t0
            if elapsed < frame_interval:
                await asyncio.sleep(frame_interval - elapsed)
    finally:
        # Note: Worker remains active in registry for attendance & diagnostics unless stopped
        pass
