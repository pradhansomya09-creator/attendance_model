# Features

This page covers the shipped desktop feature set and the scope of the current Facenox Cloud integration.

## Desktop Features

### Local recognition pipeline

- Face detection runs on the local machine.
- Face recognition runs on the local machine.
- Anti-spoofing checks run in the local pipeline.
- The renderer sends image data as binary payloads to avoid unnecessary encoding overhead.

### Attendance workflows

- Create and manage groups.
- Create, edit, and remove members.
- Record attendance events and attendance sessions.
- Configure attendance timing behavior in settings.
- Review historical attendance data and export reports.

### V-LASER Virtual Grid & Intelligent Spatial Tracking

- **Software-Defined Laser Grids**: Simulates laser lines, grids, and polygon boundaries directly on CCTV footage without extra hardware.
- **Resolution-Independent Coordinates**: Normalized space $[0.0, 1.0]^2$ preserves boundary positions across resolution changes.
- **Bottom-Center Footprint Anchoring**: Tracks spatial positions based on person bottom-center grounding point $(x + w/2, y + h)$.
- **Classroom Zone Management**: Ray-casting point-in-polygon zone classification with 2-frame hysteresis.
- **Virtual Entry/Exit Lines**: Directional segment intersection with $1.0$-second jitter debouncing.
- **Conservative Identity Association**: Strict decoupling of kinematic tracking from biometric identification (Case A, Case B, Case C).
- **Dual-Criteria Attendance Gatekeeper**: Attendance requires both verified biometric identity and validated classroom presence.
- **Real-Time Visual Editor**: Interactive React/Electron SVG canvas with live reticles and boundary validation.

### Class Session Video Playback & Attendance Review

- **Multi-Filter Class Querying**: Authorized faculty filter recorded sessions by Course, Section, Date, and Session Timetable.
- **HTML5 Range Video Streaming (HTTP 206)**: Smooth seeking, forward/rewind (±5s), speed adjustments ($0.5\times - 2.0\times$), and fullscreen controls.
- **Timeline Detection Bookmarks**: Interactive timeline pins and roster bookmarks indicate exact video timestamps when students were seen by CCTV/V-LASER.
- **Audited Attendance Corrections**: Faculty can mark students Present, Late, or Absent with mandatory review justifications recorded to an immutable audit trail (`attendance_correction_audits`).
- **Comprehensive Video Access Audits**: Every video stream request logs the viewer identity, timestamp, byte ranges, and client IP address (`video_access_audits`).
- **Storage & Retention Governance**: Configurable retention limits (e.g. 30 days) with automated nightly cleanup of expired footage while preserving audit metadata.
- **Zero-Trust Tailscale Network Access**: Stable MagicDNS device naming (`facenox-core.tailnet.ts.net`), isolated CCTV VLAN subnet routing (`192.168.10.0/24`), granular ACL tags, and institutional HTTPS reverse proxy guidelines.

### Privacy-first biometric architecture

- Biometric enrollment via live camera capture or batch photo import.
- Raw camera frames are processed in-memory and never written to disk or transmitted to external servers.
- Embeddings are encrypted at rest locally and purged when a member is deleted.
- Settings explain local processing, Cloud template access, and organizational data-handling responsibilities.

### Local storage and portability

- The local database stores groups, members, attendance, settings, and audit data.
- Enrolled face data is encrypted at rest in the local store using AES-256.
- Backup exports create password-protected `.facenox` files that you can move to another computer.

### Operational features

- Audit logging for sensitive local actions
- Desktop settings for camera, attendance, updater, and sync behavior
- Offline-first operation for the core attendance workflow

## Facenox Cloud Integration

Facenox Cloud connects offline Facenox desktop kiosks to a unified cloud control plane for browser-based review of synced records, automated DTR reporting, and multi-location management.

### What the desktop app supports

- Store a custom Facenox Cloud server address (advanced)
- Redeem a short-lived 8-character pairing code from Facenox Cloud
- Connect a desktop instance to an organization and location
- Show pairing state, last sync state, and sync messages
- Run background auto-sync
- Run manual sync on demand
- Receive organization attendance policies and supported remote administration commands

### What gets synced

- Group metadata
- Member directory data needed for reports
- Attendance records
- Attendance sessions
- Device name and ID, app version, and sync activity

Cloud directory changes, including group/member updates and removals, are applied on connected computers through sync. Disconnected computers receive updates when they reconnect.

### What does not get synced

- Raw face photos
- Face matching decisions
- Remote-side recognition state
- Camera video, CPU or memory diagnostics, and exported health reports

### What gets synced (encrypted)

- **Enrolled face data (paid Cloud plans)**: AES-256-GCM encrypted before upload and stored encrypted for sync between paired computers at a location. Computers decrypt templates for local recognition. Cloud manages location keys and also decrypts/re-encrypts templates during transfers between locations.

### Remote administration

After pairing, authorized Cloud commands can wipe local Facenox data, reset the local admin PIN, or request an update check. Command results are returned to Cloud. Hosted deployments are responsible for administrator authorization, step-up protection for destructive actions, auditability, and retention.

## Not in Scope

These items are outside the current desktop repository scope:

- Remote-side face matching
- Two-way sync for attendance edits
- Direct payroll or HRIS integrations (DTR exports can feed payroll processing)
- Self-serve billing
- SSO or SCIM
- Public developer API
- Mobile app

If any of these ship later, they should be documented as separate capabilities instead of being implied here.
