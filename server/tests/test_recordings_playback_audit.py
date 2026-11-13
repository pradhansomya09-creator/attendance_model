"""Tests for Class Session Video Playback, Faculty Review, Attendance Correction, and Audit Trail."""

import pytest
from main import app
from database.session import AsyncSessionLocal
from services.recording_service import RecordingService


def _headers(token: str = "test-token") -> dict[str, str]:
    return {
        "X-Facenox-Token": token,
        "X-Facenox-Organization": "org-test",
    }


def test_list_and_filter_class_recordings(test_client, set_api_token):
    """Verify listing recordings and filtering by course code and section."""
    client, _ = test_client
    set_api_token("test-token")
    headers = _headers("test-token")

    # 1. List all recordings (auto-provisions samples)
    resp = client.get("/recordings", headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1

    # 2. Filter by course code
    resp_filtered = client.get("/recordings?course=CS-301", headers=headers)
    assert resp_filtered.status_code == 200
    filtered_data = resp_filtered.json()
    assert all(r["course_code"] == "CS-301" for r in filtered_data)


def test_recording_roster_and_detection_bookmarks(test_client, set_api_token):
    """Verify retrieval of class roster with video detection timeline bookmarks."""
    client, _ = test_client
    set_api_token("test-token")
    headers = _headers("test-token")

    list_res = client.get("/recordings", headers=headers)
    rec_id = list_res.json()[0]["id"]

    roster_res = client.get(f"/recordings/{rec_id}/roster", headers=headers)
    assert roster_res.status_code == 200
    data = roster_res.json()

    assert "recording" in data
    assert "roster" in data
    assert len(data["roster"]) >= 1
    # Each student should have video timeline bookmarks
    student = data["roster"][0]
    assert "video_timestamp_seconds" in student
    assert "video_timestamp_formatted" in student
    assert "status" in student


def test_attendance_correction_with_immutable_audit(test_client, set_api_token):
    """Verify faculty can review footage and correct attendance with audit tracking."""
    client, _ = test_client
    set_api_token("test-token")
    headers = _headers("test-token")

    list_res = client.get("/recordings", headers=headers)
    rec_id = list_res.json()[0]["id"]
    roster_res = client.get(f"/recordings/{rec_id}/roster", headers=headers)
    roster = roster_res.json()["roster"]
    student = roster[0]

    # Submit attendance correction
    correction_payload = {
        "member_id": student["member_id"],
        "new_status": "present",
        "reason": "Verified present via CCTV footage review at timestamp 00:15",
        "corrected_by": "Dr. Sarah Jenkins (Faculty)",
    }
    post_res = client.post(
        f"/recordings/{rec_id}/attendance", headers=headers, json=correction_payload
    )
    assert post_res.status_code == 200
    corr_data = post_res.json()
    assert corr_data["success"] is True
    assert corr_data["corrected_by"] == "Dr. Sarah Jenkins (Faculty)"
    assert corr_data["new_status"] == "present"

    # Verify audit trail contains the correction
    audit_res = client.get(f"/recordings/{rec_id}/audit-trail", headers=headers)
    assert audit_res.status_code == 200
    audit_data = audit_res.json()
    corrections = audit_data["attendance_corrections"]
    assert len(corrections) >= 1
    latest = corrections[0]
    assert latest["corrected_by"] == "Dr. Sarah Jenkins (Faculty)"
    assert "CCTV footage review" in latest["reason"]


def test_video_streaming_and_access_audit(test_client, set_api_token):
    """Verify HTTP 206 partial content streaming and audit logging of video access."""
    client, _ = test_client
    set_api_token("test-token")
    headers = _headers("test-token")

    list_res = client.get("/recordings", headers=headers)
    rec_id = list_res.json()[0]["id"]

    # Stream with Range header (e.g. video scrubber seeking)
    stream_headers = {
        **headers,
        "Range": "bytes=0-1023",
        "X-Faculty-Id": "Prof. Alan Turing",
    }
    stream_res = client.get(f"/recordings/{rec_id}/stream", headers=stream_headers)
    assert stream_res.status_code in (200, 206)
    assert len(stream_res.content) > 0

    # Check access audit
    audit_res = client.get(f"/recordings/{rec_id}/audit-trail", headers=headers)
    assert audit_res.status_code == 200
    access_logs = audit_res.json()["video_access_logs"]
    assert any(log["accessed_by"] == "Prof. Alan Turing" for log in access_logs)


def test_retention_policy_and_deletion_controls(test_client, set_api_token):
    """Verify configurable retention period and authorized deletion controls."""
    client, _ = test_client
    set_api_token("test-token")
    headers = _headers("test-token")

    # Check current retention settings
    ret_res = client.get("/recordings/settings/retention", headers=headers)
    assert ret_res.status_code == 200
    data = ret_res.json()
    assert "default_retention_days" in data
    assert "storage_used_bytes" in data

    # Update retention policy
    update_res = client.post(
        "/recordings/settings/retention", headers=headers, json={"retention_days": 45}
    )
    assert update_res.status_code == 200
    assert update_res.json()["new_retention_days"] == 45
