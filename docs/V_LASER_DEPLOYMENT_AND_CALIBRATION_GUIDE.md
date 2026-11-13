# V-LASER: Virtual Laser Grid & Intelligent Spatial Tracking System
## Comprehensive Architecture, Deployment, Calibration & Operations Guide

---

## 1. System Overview & Architecture

**V-LASER** is a software-based Virtual Laser Grid and Intelligent Spatial Tracking System integrated into the Smart CCTV Attendance System (Facenox). It simulates laser-like boundary lines, zones, and spatial grids on standard CCTV camera feeds without requiring any physical laser hardware, depth sensors, or specialized multi-camera rigs.

### High-Level Architecture Flow

```
+-------------------------------------------------------------------------------+
|                             CCTV Camera Video Feed                            |
|             (RTSP Stream / USB UVC / Mobile IP Camera / Simulated)             |
+-------------------------------------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                          Frame Acquisition & Enhancer                         |
|     (CLAHE, Infrared Night-Vision, Brightness/Contrast Assessment, cv2)       |
+-------------------------------------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                              Face Detection & Tracking                        |
|       - YuNet Face Detector (detector.onnx) -> 5-point facial landmarks       |
|       - ByteTrack Kinematic Multi-Object Tracker (Kalman Filter + LAP)         |
+-------------------------------------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                         V-LASER Virtual Grid Manager                          |
|   - Bottom-Center Bounding Box Anchor Extraction: (x + w/2, y + h)            |
|   - Normalized Coordinate Mapping: [0.0, 1.0]^2 resolution-independent        |
|   - Ray-Casting Point-in-Polygon Zone Classification (Student Seating, etc.)  |
|   - Directional Segment Intersection for Entry / Exit / Restricted Lines      |
|   - 2-Frame Zone Residence Hysteresis & 1.0s Cross-Line Jitter Debouncing     |
+-------------------------------------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                 Conservative Identity Association Gatekeeper                  |
|   - Case A (Clear face): Verified Identity State -> person_id bound           |
|   - Case B (Small/low quality/turned): Pending Verification (no forced match) |
|   - Case C (Face not visible): Spatially Tracked Only (NO clothes guessing)   |
|   - Gatekeeper: Attendance marked ONLY if (Verified ID AND Spatial Presence)  |
+-------------------------------------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                         Real-Time Event Distribution                          |
|   - Asynchronous WebSockets via notification_manager.broadcast                |
|   - REST API: /cctv/vlaser/events/recent & /cameras/{id}/spatial-state        |
+-------------------------------------------------------------------------------+
                                        |
                                        v
+-------------------------------------------------------------------------------+
|                        React 19 + Electron Dashboard UI                       |
|   - AdminCctvDashboard: Real-Time Spatial KPI Cards & Live Event Log          |
|   - VLaserEditorModal: Full Interactive SVG Laser Grid & Boundary Designer    |
+-------------------------------------------------------------------------------+
```

---

## 2. Technical Stack & Hardware Requirements

### Minimum Hardware
- **CPU**: Standard dual-core x86_64 or ARM64 processor (Intel Core i3 / AMD Ryzen 3 / Apple Silicon).
- **RAM**: 4 GB (8 GB recommended for concurrent multi-camera streams).
- **Cameras**: Any standard CCTV camera (RTSP, ONVIF), USB Webcam, or Mobile IP stream ($640 \times 360$ up to $1920 \times 1080$).
- **No Physical Lasers**: All laser lines, grids, and boundaries are 100% software-defined.

### Software Requirements
- **Python**: 3.11 – 3.14
- **Node.js**: 20 LTS or higher
- **Database**: SQLite (built-in) or PostgreSQL with SQLAlchemy Async and Alembic
- **Frameworks**: FastAPI, ONNX Runtime CPU, OpenCV, React 19, TypeScript, Electron 42, Vite, Tailwind CSS 4

---

## 3. Installation & Configuration Guide

### 3.1 Backend Setup
1. Activate the Python virtual environment:
   ```bash
   cd facenox/server
   ..\venv\Scripts\activate
   ```
2. Run database migrations to provision the `vlaser_camera_configs` table:
   ```bash
   alembic upgrade head
   ```
   *Verified single head: `v1w2x3y4z5a6`.*
3. Start the FastAPI backend server:
   ```bash
   python -m uvicorn main:app --host 127.0.0.1 --port 7400 --reload
   ```

### 3.2 Frontend & Desktop Setup
1. In the `app` directory, ensure dependencies are installed:
   ```bash
   cd facenox/app
   npm install
   ```
2. Start the development desktop client:
   ```bash
   npm run dev
   ```

---

## 4. Classroom Calibration Guide

### 4.1 Coordinate Space
V-LASER uses a normalized coordinate system:
$$\begin{aligned}
x &\in [0.0, 1.0] \quad (\text{left} \rightarrow \text{right}) \\
y &\in [0.0, 1.0] \quad (\text{top} \rightarrow \text{bottom})
\end{aligned}$$
This guarantees that lines and zones drawn on a preview frame remain perfectly aligned even if the camera stream changes resolution (e.g., from 720p to 1080p) or if the desktop window is resized.

### 4.2 Drawing Virtual Lines
1. Navigate to **CCTV Admin Dashboard** in Facenox.
2. Click **V-LASER Grid** on any camera card.
3. Select **Add Line** in the top toolbar:
   - Click and drag on the camera preview to position the line.
   - Choose the line type:
     - **Entry Line**: Monitors incoming students entering the room.
     - **Exit Line**: Monitors students leaving the room.
     - **Internal Line**: Monitors movement between classroom sections.
     - **Restricted Boundary**: Alerts when unauthorized personnel cross into prohibited areas.
   - Set Direction: **Forward**, **Backward**, or **Bidirectional**.
4. Click **Save Configuration**.

### 4.3 Drawing Classroom Zones
1. In the modal toolbar, click **Add Zone**.
2. Select a Zone Type:
   - `Student Seating Area`: Designates where students sit. Presence here $\ge 5.0$ seconds satisfies spatial attendance criteria.
   - `Classroom Entrance`: Designates the doorway or foyer.
   - `Front Teaching Area`: Podium and whiteboard area.
   - `Teacher Area`: Teacher's desk.
   - `Restricted Area`: Equipment racks, stage wings, or hazardous zones.
3. Click on the canvas to place polygon vertices (3 to 12 points).
4. Double-click or click the first point to close the polygon.
5. Click **Validate Geometry** to confirm no self-intersections exist.
6. Click **Save Configuration**.

---

## 5. Database Migration & Rollback Strategy

### Forward Migration
To apply the V-LASER schema:
```bash
cd server
alembic upgrade head
```
This applies `v1w2x3y4z5a6_add_vlaser_camera_configs.py` which creates the `vlaser_camera_configs` table with:
- `camera_id` (Indexed foreign key)
- `lines_json` (Serialized line definitions)
- `zones_json` (Serialized polygon definitions)
- `grid_enabled`, `grid_rows`, `grid_cols`, `grid_color`, `grid_opacity`
- `is_active`, `organization_id`, `created_at`, `updated_at`

### Rollback Migration
If a rollback is required for maintenance or zero-downtime regression:
```bash
cd server
alembic downgrade u6v7w8x9y0z1
```
This cleanly drops the `vlaser_camera_configs` table without impacting cameras, members, attendance sessions, or facial embedding tables.

---

## 6. Conservative Identity Association Rules

V-LASER strictly adheres to the principle: **Kinematic Track ID $\neq$ Verified Student Identity**.

| Case | Scenario | Facial Observation | System Action | State |
|---|---|---|---|---|
| **Case A** | Clear frontal face | High quality ($\ge 0.38$), large ($\ge 48$px), frontal ($|\text{yaw}| \le 25^\circ$), real liveness, confident match ($\ge 0.36$) | Associate recognized identity with current track ID | `IDENTITY_VERIFIED` |
| **Case B** | Small, blurry, or turned | Face $< 48$px, low light, or severe head pose | Maintain spatial tracking without forced identity | `PENDING_VERIFICATION` |
| **Case C** | Face turned away / occluded | Face occluded or not detected | Maintain spatial tracking. Never guess identity from clothes/hair | `SPATIALLY_TRACKED` |
| **Unknown** | Unregistered individual | Real human face with no enrollment match | Flag unknown individual alert to dashboard | `UNKNOWN_PERSON` |

### Attendance Gatekeeper Rules
Entering the classroom or crossing an entry line does **NOT** automatically mark attendance. Attendance requires **BOTH**:
1. Verified biometric identity (`IDENTITY_VERIFIED`).
2. Verified spatial presence (either crossing an entry line OR remaining in the student seating zone for $\ge 5.0$ seconds).

---

## 7. Troubleshooting & Incident Recovery

### Issue 1: Camera Disconnect / Frozen Feed
- **Symptom**: Camera status changes to `offline` or `unstable`.
- **System Action**: Spatial tracker retains active tracks for 10 seconds before clean eviction. No synthetic crossings or phantom events are generated.
- **Recovery**: Click **Reconnect** or **Probe** on the CCTV dashboard. Once frames resume, the tracker automatically re-synchronizes.

### Issue 2: Low-Quality Image Spikes (Yellow/Red)
- **Symptom**: Poor lighting or lens smudge triggers image quality warning.
- **System Action**: Conservative gatekeeper sets affected tracks to `PENDING_VERIFICATION`. False present marks are strictly prevented.
- **Recovery**: Adjust classroom lighting or clean lens; system recovers instantly once image quality score $\ge 0.38$.

### Issue 3: Line Crossing Jitter
- **Symptom**: Person standing directly on an entry line generates rapid duplicate crossing events.
- **System Action**: V-LASER applies a $1.0$-second temporal debounce per line and requires opposite-side sign reversals ($\text{cross\_prod} \cdot \text{prev\_side} < 0$).

---

## 8. Production Verification Checklist

Before opening the system for production classroom attendance:

- [ ] Single Alembic migration head confirmed (`v1w2x3y4z5a6`).
- [ ] Database contains valid camera record (`POST /cctv/cameras`).
- [ ] V-LASER default configuration loaded (`GET /cctv/vlaser/cameras/{camera_id}`).
- [ ] Entry line and student seating zones configured and saved without geometry self-intersection warnings.
- [ ] Live preview frame loads successfully in the modal editor.
- [ ] Automated regression tests pass:
  ```bash
  pytest tests/test_vlaser* -v
  npm test -- src/components/cctv
  ```
- [ ] Real-time spatial event feed updates on `AdminCctvDashboard`.
- [ ] Crossing entry line shows student presence without prematurely marking attendance before verification.

