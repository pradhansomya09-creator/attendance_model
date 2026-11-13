# Tailscale Private Network, Subnet Routing & Security Architecture Guide

This guide details the network topology, identity-based access control, subnet routing, and institutional HTTPS reverse proxy architecture for **Facenox** and its **Smart CCTV & V-LASER Attendance Hub**.

---

## 1. Executive Summary & Design Principles

Facenox is engineered with **Local-First Privacy & Zero Trust Network Architecture (ZTNA)**:
1. **Local Face Processing & Biometric Isolation**:
   - Camera feeds, frame decodes, V-LASER spatial tracking, and ArcFace/InsightFace feature extractions remain **strictly local on the edge server/node**.
   - Raw face vectors are encrypted in PostgreSQL (`faces.embedding`). Biometric vectors and high-resolution enrollment faces are **never** transmitted across public endpoints or exposed in recorded playback streams.
2. **Stable Identity Over Hardcoded IPs**:
   - Colleges typically assign dynamic DHCP addresses or re-segment subnets across academic departments.
   - Using Tailscale **MagicDNS** (`facenox-core.tailnet.ts.net`), services bind to stable cryptographic node identities instead of brittle private IP addresses.
3. **Subnet Routing for College CCTV LANs**:
   - Institutional CCTV cameras and NVRs reside on isolated physical VLANs (e.g., `192.168.10.0/24`) without internet gateways.
   - A dedicated Facenox host acts as an authorized **Tailscale Subnet Router**, granting faculty and security auditors audited access without exposing cameras to the campus Wi-Fi or WAN.
4. **Institutional HTTPS Reverse Proxy**:
   - When faculty review sessions remotely outside the tailnet, all traffic passes through an institution-approved reverse proxy (Caddy / Nginx) enforcing TLS 1.3, strict RBAC JWT claims, and immutable access logging.

---

## 2. Tailscale Architecture & Mesh Topology

```
+-----------------------------------------------------------------------------------------+
|                                    COLLEGE NETWORK                                      |
|                                                                                         |
|   +-----------------------+                    +------------------------------------+   |
|   |  CCTV Subnet (VLAN)   |                    |       Facenox Edge Host Node       |   |
|   |  192.168.10.0/24      |                    |  (MagicDNS: facenox-core)          |   |
|   |  - LH-101 CAM (10.12) |                    |                                    |   |
|   |  - LH-102 CAM (10.13) | <================> |  - RTSP Ingestion Pipeline         |   |
|   |  - Entrance CAM       |  Isolated Switch   |  - V-LASER Spatial Tracker         |   |
|   +-----------------------+                    |  - Local PostgreSQL & H.264 Clips  |   |
|                                                |  - Tailscale Subnet Router         |   |
|                                                +-----------------+------------------+   |
+------------------------------------------------------------------|----------------------+
                                                                   |
                                              Tailscale Encrypted WireGuard Mesh
                                                                   |
                      +--------------------------------------------+--------------------------------------------+
                      |                                            |                                            |
                      v                                            v                                            v
        +---------------------------+                +---------------------------+                +---------------------------+
        |     Faculty Laptop        |                |     Department HOD        |                |  Institutional HTTPS Gateway
        |  faculty-laptop.tailnet   |                |   hod-desktop.tailnet     |                |  proxy.campus.edu (Caddy) |
        |  - Review Recorded Clips  |                |  - Audit Trail Review     |                |  - Strict RBAC & TLS 1.3  |
        |  - Correct Attendance     |                |  - System Health Checks   |                |  - Public/WAN Access      |
        +---------------------------+                +---------------------------+                +---------------------------+
```

---

## 3. Step-by-Step Tailscale Node & Subnet Router Setup

### Step 3.1: Install Tailscale on the Facenox Edge Server

#### Windows Edge Host:
1. Download and install [Tailscale for Windows](https://tailscale.com/download/windows).
2. Open PowerShell as Administrator and enable IP forwarding:
```powershell
Set-NetIPInterface -Forwarding Enabled
```
3. Authenticate with your institution's Tailscale domain and advertise the CCTV subnet:
```powershell
tailscale up --advertise-routes=192.168.10.0/24 --accept-routes --hostname=facenox-core
```

#### Linux Edge Host (Ubuntu / Debian / Rocky):
1. Install Tailscale:
```bash
curl -fsSL https://tailscale.com/install.sh | sh
```
2. Enable IPv4 and IPv6 packet forwarding in `/etc/sysctl.d/99-tailscale.conf`:
```ini
net.ipv4.ip_forward = 1
net.ipv6.conf.all.forwarding = 1
```
Apply settings:
```bash
sudo sysctl -p /etc/sysctl.d/99-tailscale.conf
```
3. Start Tailscale advertising the CCTV subnet:
```bash
sudo tailscale up --advertise-routes=192.168.10.0/24 --accept-routes --hostname=facenox-core
```

---

### Step 3.2: Approve Subnet Routes in Tailscale Admin Console

1. Navigate to the **Tailscale Admin Console** > **Machines**.
2. Locate `facenox-core`.
3. In the machine options (`...`), click **Edit route settings...**.
4. Check the box for `192.168.10.0/24` to approve the subnet route.

---

### Step 3.3: MagicDNS & Device Identity Resolution

Instead of connecting to ephemeral IPs like `100.84.192.42`, configure Facenox services to communicate via MagicDNS:
- **Backend API**: `http://facenox-core.tailnet.ts.net:8000`
- **WebSocket Feed**: `ws://facenox-core.tailnet.ts.net:8000/api/v1/ws/live`
- **Classroom RTSP Streams**: `rtsp://facenox-core.tailnet.ts.net:8554/live/lh101`

---

## 4. Tailscale Access Control Lists (ACLs)

Define granular Zero-Trust ACLs in `Tailscale Admin > Access Controls`. This ensures that faculty can only access class recording review APIs, while only Network Admins can directly reach the CCTV camera web consoles.

```json
{
  "acls": [
    // 1. Facenox Core Server can reach all CCTV cameras on the physical subnet
    {
      "action": "accept",
      "src": ["tag:facenox-server"],
      "dst": ["192.168.10.0/24:*"]
    },

    // 2. Faculty devices can access Facenox Web App & Playback API on facenox-core
    {
      "action": "accept",
      "src": ["tag:faculty"],
      "dst": [
        "tag:facenox-server:8000",
        "tag:facenox-server:3000"
      ]
    },

    // 3. HOD & Campus Admins have full access to Facenox and CCTV diagnostics
    {
      "action": "accept",
      "src": ["tag:admin", "tag:hod"],
      "dst": [
        "tag:facenox-server:*",
        "192.168.10.0/24:80",
        "192.168.10.0/24:554"
      ]
    }
  ],

  "tagOwners": {
    "tag:facenox-server": ["admin@campus.edu"],
    "tag:faculty":        ["admin@campus.edu"],
    "tag:admin":          ["admin@campus.edu"],
    "tag:hod":            ["admin@campus.edu"]
  }
}
```

---

## 5. Institutional HTTPS Endpoint & Reverse Proxy (WAN Access)

When access is required outside Tailnet (e.g., faculty at home without Tailscale installed), deploy Facenox behind an approved **Caddy** or **Nginx** reverse proxy with automatic TLS and Role-Based Access Control.

### Option A: Caddy Configuration (`/etc/caddy/Caddyfile`)

```caddy
facenox.campus.edu {
    # Automatic TLS using Institutional Let's Encrypt / ACME CA
    tls admin@campus.edu

    # Security Headers
    header {
        Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"
        X-Content-Type-Options "nosniff"
        X-Frame-Options "DENY"
        Referrer-Policy "strict-origin-when-cross-origin"
        Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; media-src 'self' blob:; connect-src 'self' wss: https:;"
    }

    # Video Clips Range Streaming & Cache Control
    @video_streams path /api/v1/recordings/*/stream
    handle @video_streams {
        reverse_proxy facenox-core.tailnet.ts.net:8000 {
            header_up Host {host}
            header_up X-Real-IP {remote}
            header_up X-Forwarded-For {remote}
            header_up X-Forwarded-Proto {scheme}
        }
    }

    # API and WebSocket Routing
    handle /api/v1/* {
        reverse_proxy facenox-core.tailnet.ts.net:8000
    }

    # Frontend Single Page Application
    handle {
        reverse_proxy facenox-core.tailnet.ts.net:3000
    }
}
```

### Option B: Nginx Configuration (`/etc/nginx/sites-available/facenox.conf`)

```nginx
server {
    listen 443 ssl http2;
    server_name facenox.campus.edu;

    ssl_certificate /etc/ssl/certs/facenox.campus.edu.crt;
    ssl_certificate_key /etc/ssl/private/facenox.campus.edu.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # Maximum upload for high-res enrollment batches
    client_max_body_size 50M;

    # Video Range Streaming (HTTP 206 Partial Content)
    location ~ ^/api/v1/recordings/.*/stream$ {
        proxy_pass http://facenox-core.tailnet.ts.net:8000;
        proxy_http_version 1.1;
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_cache off;
    }

    # WebSocket Ingestion and Live Stream
    location /api/v1/ws/ {
        proxy_pass http://facenox-core.tailnet.ts.net:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "Upgrade";
        proxy_set_header Host $host;
    }

    # Standard API Endpoints
    location /api/ {
        proxy_pass http://facenox-core.tailnet.ts.net:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }

    # Frontend Assets
    location / {
        proxy_pass http://facenox-core.tailnet.ts.net:3000;
    }
}
```

---

## 6. Security & Audit Verification Matrix

| Requirement | Implementation Mechanism | Verification Check |
|---|---|---|
| **Private Mesh Access** | Tailscale WireGuard tunnels between approved faculty nodes | `tailscale status` shows peers online with encrypted WireGuard state. |
| **Stable Device Identity** | MagicDNS domain `*.tailnet.ts.net` | `ping facenox-core.tailnet.ts.net` resolves consistently regardless of DHCP changes. |
| **Subnet Routing for LAN Cameras** | `tailscale up --advertise-routes=192.168.10.0/24` | Faculty devices can ping `192.168.10.12` without camera internet exposure. |
| **Video Access Logging** | `video_access_audits` PostgreSQL table | Every stream request logs user identity, recording ID, range headers, and client IP. |
| **Attendance Edit Immutability** | `attendance_correction_audits` table | Faculty attendance adjustments require justification notes and record timestamp + previous/new status. |
| **Biometric Privacy** | Local ArcFace embeddings stored encrypted | Streaming and playback endpoints only serve encoded H.264 video frames; 512-d embeddings are never returned over HTTP. |
| **Configurable Retention** | Auto-pruning background task & manual purge | Recordings older than retention policy (e.g. 30 days) are deleted, preserving audit metadata. |

---

## 7. Troubleshooting & Common Commands

- **Check Tailscale Status**:
  ```bash
  tailscale status
  ```
- **Verify Subnet Routes Active**:
  ```bash
  tailscale route list
  ```
- **Check Facenox Core Connectivity from Faculty Device**:
  ```bash
  curl -I http://facenox-core.tailnet.ts.net:8000/api/v1/recordings
  ```
- **Check Video Streaming Range Request (HTTP 206)**:
  ```bash
  curl -i -H "Range: bytes=0-1048575" http://facenox-core.tailnet.ts.net:8000/api/v1/recordings/<RECORDING_ID>/stream
  ```

