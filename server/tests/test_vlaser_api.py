"""Integration tests for V-LASER Virtual Grid, Lines & Zones API endpoints."""

from __future__ import annotations

import pytest


def _headers(org_id: str = "org-vlaser") -> dict[str, str]:
    return {
        "X-Facenox-Token": "vlaser-token",
        "X-Facenox-Organization": org_id,
    }


def test_vlaser_camera_config_lifecycle(test_client, set_api_token):
    client, _ = test_client
    set_api_token("vlaser-token")
    headers = _headers()

    # 1. Register a test CCTV camera
    cam_res = client.post(
        "/cctv/cameras",
        headers=headers,
        json={
            "name": "Classroom 101 Laser Cam",
            "camera_code": "CAM-LASER-101",
            "source_type": "simulated",
            "classroom": "LH-101",
            "department": "CSE",
        },
    )
    assert cam_res.status_code == 200, cam_res.text
    camera_id = cam_res.json()["id"]

    # 2. Query default V-LASER config for new camera
    get_res = client.get(f"/cctv/vlaser/cameras/{camera_id}", headers=headers)
    assert get_res.status_code == 200, get_res.text
    cfg = get_res.json()
    assert cfg["camera_id"] == camera_id
    assert cfg["classroom"] == "LH-101"
    assert cfg["grid_enabled"] is True
    assert len(cfg["lines"]) >= 2
    assert len(cfg["zones"]) >= 2

    # 3. Update V-LASER config with custom lines and polygon zones
    custom_cfg = {
        "camera_id": camera_id,
        "classroom": "LH-101",
        "grid_enabled": True,
        "grid_rows": 15,
        "grid_cols": 12,
        "grid_color": "#00f3ff",
        "grid_opacity": 0.35,
        "lines": [
            {
                "id": "line-entry-1",
                "name": "North Door Entry",
                "line_type": "entry",
                "direction": "forward",
                "p1": {"x": 0.1, "y": 0.9},
                "p2": {"x": 0.4, "y": 0.9},
                "color": "#10b981",
                "enabled": True,
            },
            {
                "id": "line-exit-1",
                "name": "South Door Exit",
                "line_type": "exit",
                "direction": "forward",
                "p1": {"x": 0.6, "y": 0.9},
                "p2": {"x": 0.9, "y": 0.9},
                "color": "#f97316",
                "enabled": True,
            },
        ],
        "zones": [
            {
                "id": "zone-seating-1",
                "name": "Lecture Seating Area",
                "zone_type": "student_seating",
                "polygon": [
                    {"x": 0.1, "y": 0.3},
                    {"x": 0.9, "y": 0.3},
                    {"x": 0.9, "y": 0.8},
                    {"x": 0.1, "y": 0.8},
                ],
                "color": "#22c55e",
                "opacity": 0.25,
                "enabled": True,
            }
        ],
        "is_active": True,
    }

    save_res = client.post(
        f"/cctv/vlaser/cameras/{camera_id}",
        headers=headers,
        json=custom_cfg,
    )
    assert save_res.status_code == 200, save_res.text
    saved = save_res.json()
    assert saved["grid_rows"] == 15
    assert saved["grid_cols"] == 12
    assert len(saved["lines"]) == 2
    assert saved["lines"][0]["name"] == "North Door Entry"

    # 4. Verify persistence by re-fetching
    fetch_again = client.get(f"/cctv/vlaser/cameras/{camera_id}", headers=headers)
    assert fetch_again.status_code == 200
    assert fetch_again.json()["grid_rows"] == 15

    # 5. Fetch preview frame
    prev_res = client.get(f"/cctv/vlaser/cameras/{camera_id}/preview-frame", headers=headers)
    assert prev_res.status_code == 200, prev_res.text
    preview_data = prev_res.json()
    assert preview_data["camera_id"] == camera_id
    assert "data:image/jpeg;base64," in preview_data["image_data_url"]
    assert preview_data["width"] > 0
    assert preview_data["height"] > 0

    # 6. Reset config to default
    del_res = client.delete(f"/cctv/vlaser/cameras/{camera_id}", headers=headers)
    assert del_res.status_code == 200, del_res.text
    assert del_res.json()["success"] is True

    # 7. Check that non-existent camera returns 404
    bad_res = client.get("/cctv/vlaser/cameras/non-existent-cam-id", headers=headers)
    assert bad_res.status_code == 404


def test_vlaser_geometry_validation_endpoint(test_client, set_api_token):
    client, _ = test_client
    set_api_token("vlaser-token")
    headers = _headers()

    # Valid payload
    valid_payload = {
        "lines": [
            {
                "id": "l1",
                "name": "Gate Entry",
                "line_type": "entry",
                "direction": "forward",
                "p1": {"x": 0.1, "y": 0.8},
                "p2": {"x": 0.4, "y": 0.8},
                "color": "#10b981",
                "enabled": True,
            },
            {
                "id": "l2",
                "name": "Gate Exit",
                "line_type": "exit",
                "direction": "forward",
                "p1": {"x": 0.5, "y": 0.8},
                "p2": {"x": 0.8, "y": 0.8},
                "color": "#f97316",
                "enabled": True,
            },
        ],
        "zones": [
            {
                "id": "z1",
                "name": "Seating Zone",
                "zone_type": "student_seating",
                "polygon": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.8, "y": 0.1},
                    {"x": 0.8, "y": 0.6},
                    {"x": 0.1, "y": 0.6},
                ],
                "color": "#22c55e",
                "opacity": 0.2,
                "enabled": True,
            }
        ],
    }

    val_res = client.post("/cctv/vlaser/validate", headers=headers, json=valid_payload)
    assert val_res.status_code == 200, val_res.text
    res_data = val_res.json()
    assert res_data["valid"] is True
    assert len(res_data["errors"]) == 0

    # Invalid: Duplicate line names
    dup_line_payload = {
        "lines": [
            {
                "id": "l1",
                "name": "Same Name",
                "line_type": "entry",
                "direction": "forward",
                "p1": {"x": 0.1, "y": 0.8},
                "p2": {"x": 0.4, "y": 0.8},
                "color": "#10b981",
                "enabled": True,
            },
            {
                "id": "l2",
                "name": "Same Name",
                "line_type": "exit",
                "direction": "forward",
                "p1": {"x": 0.5, "y": 0.8},
                "p2": {"x": 0.8, "y": 0.8},
                "color": "#f97316",
                "enabled": True,
            },
        ],
        "zones": [],
    }
    dup_res = client.post("/cctv/vlaser/validate", headers=headers, json=dup_line_payload)
    assert dup_res.status_code == 200
    assert dup_res.json()["valid"] is False
    assert any("Duplicate line name" in err for err in dup_res.json()["errors"])


def test_vlaser_spatial_state_and_events_api(test_client, set_api_token):
    client, _ = test_client
    set_api_token("vlaser-token")
    headers = _headers()

    # 1. Register camera
    cam = client.post(
        "/cctv/cameras",
        headers=headers,
        json={
            "name": "Spatial Room Cam",
            "camera_code": "CAM-SPATIAL-101",
            "source_type": "simulated",
            "classroom": "LH-301",
        },
    ).json()
    camera_id = cam["id"]

    # 2. Query spatial state (empty initially)
    st_res = client.get(f"/cctv/vlaser/cameras/{camera_id}/spatial-state", headers=headers)
    assert st_res.status_code == 200, st_res.text
    st_data = st_res.json()
    assert st_data["camera_id"] == camera_id
    assert st_data["active_tracks_count"] == 0
    assert "zone_headcounts" in st_data

    # 3. Simulate spatial frame processing via VLaserService
    from services.vlaser_service import VLaserService
    import asyncio

    faces = [
        {"track_id": 99, "bbox": {"x": 200, "y": 100, "width": 60, "height": 60}}
    ]
    asyncio.run(
        VLaserService.process_spatial_frame(
            camera_id=camera_id,
            tracked_objects=faces,
            frame_width=640,
            frame_height=360,
        )
    )

    # 4. Query spatial state again -> track 99 active
    st_res2 = client.get(f"/cctv/vlaser/cameras/{camera_id}/spatial-state", headers=headers)
    assert st_res2.status_code == 200
    st_data2 = st_res2.json()
    assert st_data2["active_tracks_count"] == 1
    assert st_data2["active_tracks"][0]["track_id"] == 99

    # 5. Query events endpoint
    ev_res = client.get(f"/cctv/vlaser/cameras/{camera_id}/events", headers=headers)
    assert ev_res.status_code == 200
    assert "events" in ev_res.json()

    # 6. Query aggregated recent events across all cameras
    all_ev_res = client.get("/cctv/vlaser/events/recent?limit=20", headers=headers)
    assert all_ev_res.status_code == 200
    assert "events" in all_ev_res.json()
    assert isinstance(all_ev_res.json()["events"], list)


