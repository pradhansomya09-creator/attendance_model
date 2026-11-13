import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { AdminCctvDashboard } from "../AdminCctvDashboard"
import { cctvService } from "@/services/cctvService"
import { vlaserService } from "@/services/vlaserService"
import { useAttendanceStore } from "@/components/main/stores/attendanceStore"

describe("AdminCctvDashboard Real-Time Telemetry & V-LASER Integration", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    useAttendanceStore.setState({
      attendanceGroups: [{ id: "grp-1", name: "CSE 5-A" } as never],
      currentGroup: { id: "grp-1", name: "CSE 5-A" } as never,
    })

    vi.spyOn(cctvService, "getAdminOverview").mockResolvedValue({
      cameras: {
        total: 4,
        online: 3,
        offline: 1,
        unstable: 0,
        with_backup: 2,
        quality_green: 2,
        quality_yellow: 1,
        quality_red: 0,
        recording_failed: 0,
      },
      alerts: {
        open_camera_incidents: 1,
        pending_unknown_students: 1,
        open_section_mismatches: 0,
      },
      model_health: {
        detector_loaded: true,
        recognizer_loaded: true,
        liveness_loaded: true,
        enrolled_embeddings: 45,
      },
    })

    vi.spyOn(cctvService, "listCameras").mockResolvedValue([
      {
        id: "cam-1",
        name: "LH-101 Front Camera",
        camera_code: "CAM-LH1-01",
        source_type: "simulated",
        source_uri: "0",
        department: "CSE",
        classroom: "LH-101",
        status: "online",
        fps: 25.0,
        quality_status: "green",
        quality_score: 0.92,
        reconnect_attempts: 0,
        supports_ir: true,
        simulated_fault: null,
      } as never,
    ])

    vi.spyOn(cctvService, "listCameraLogs").mockResolvedValue([])

    vi.spyOn(vlaserService, "getAllRecentEvents").mockResolvedValue({
      count: 2,
      events: [
        {
          id: "ev-101",
          camera_id: "cam-1",
          track_id: 15,
          event_type: "entry",
          line_name: "Front Gate",
          confidence: 0.96,
          timestamp: 1700000000,
        },
        {
          id: "ev-102",
          camera_id: "cam-1",
          track_id: 18,
          event_type: "restricted_violation",
          to_zone_name: "Server Rack Area",
          confidence: 0.89,
          timestamp: 1700000010,
        },
      ],
    })

    vi.spyOn(vlaserService, "getConfig").mockResolvedValue({
      camera_id: "cam-1",
      classroom: "LH-101",
      grid_enabled: true,
      grid_rows: 10,
      grid_cols: 10,
      grid_color: "#00f3ff",
      grid_opacity: 0.2,
      lines: [],
      zones: [],
      is_active: true,
    })

    vi.spyOn(vlaserService, "getPreviewFrame").mockResolvedValue({
      camera_id: "cam-1",
      width: 640,
      height: 360,
      image_data_url: "data:image/jpeg;base64,dummy",
    })

    vi.spyOn(vlaserService, "getSpatialState").mockResolvedValue({
      camera_id: "cam-1",
      active_tracks_count: 0,
      active_tracks: [],
      zone_headcounts: {},
      recent_events: [],
    })
  })

  it("renders V-LASER Spatial Grid KPI card and recent event counts", async () => {
    render(<AdminCctvDashboard />)

    await waitFor(() => {
      expect(screen.getByText("V-LASER Spatial Grid")).toBeInTheDocument()
      expect(screen.getByText("2 Recent Events")).toBeInTheDocument()
      expect(screen.getByText(/Entries: 1 • Exits: 0 • Violations: 1/i)).toBeInTheDocument()
    })
  })

  it("displays live spatial activity feed with entry and violation tags", async () => {
    render(<AdminCctvDashboard />)

    await waitFor(() => {
      expect(
        screen.getByText("V-LASER Live Spatial Event Feed & Boundary Alerts"),
      ).toBeInTheDocument()
      expect(screen.getByText("ENTRY")).toBeInTheDocument()
      expect(screen.getByText("RESTRICTED VIOLATION")).toBeInTheDocument()
      expect(screen.getByText("Track #15")).toBeInTheDocument()
      expect(screen.getByText("Line: Front Gate")).toBeInTheDocument()
      expect(screen.getByText("Track #18")).toBeInTheDocument()
    })
  })

  it("opens V-LASER Virtual Grid modal on button click", async () => {
    render(<AdminCctvDashboard />)

    await waitFor(() => {
      expect(screen.getByText("V-LASER Grid")).toBeInTheDocument()
    })

    fireEvent.click(screen.getByText("V-LASER Grid"))

    await waitFor(() => {
      expect(screen.getByText(/V-LASER • Virtual Grid & Boundary Manager/i)).toBeInTheDocument()
    })
  })
})

