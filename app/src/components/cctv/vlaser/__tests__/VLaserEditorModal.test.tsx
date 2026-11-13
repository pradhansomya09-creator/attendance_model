import { render, screen, fireEvent, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { VLaserEditorModal } from "../VLaserEditorModal"
import { vlaserService } from "@/services/vlaserService"
import type { VLaserConfig } from "@/types/vlaser"

const mockConfig: VLaserConfig = {
  camera_id: "cam-test-1",
  classroom: "LH-101",
  grid_enabled: true,
  grid_rows: 10,
  grid_cols: 10,
  grid_color: "#00f3ff",
  grid_opacity: 0.25,
  lines: [
    {
      id: "line-1",
      name: "Main Entrance",
      line_type: "entry",
      direction: "forward",
      p1: { x: 0.1, y: 0.8 },
      p2: { x: 0.4, y: 0.8 },
      color: "#10b981",
      enabled: true,
    },
    {
      id: "line-2",
      name: "Exit Door",
      line_type: "exit",
      direction: "forward",
      p1: { x: 0.5, y: 0.8 },
      p2: { x: 0.8, y: 0.8 },
      color: "#f97316",
      enabled: true,
    },
  ],
  zones: [
    {
      id: "zone-1",
      name: "Seating Area",
      zone_type: "student_seating",
      polygon: [
        { x: 0.1, y: 0.2 },
        { x: 0.9, y: 0.2 },
        { x: 0.9, y: 0.7 },
        { x: 0.1, y: 0.7 },
      ],
      color: "#22c55e",
      opacity: 0.25,
      enabled: true,
    },
  ],
  is_active: true,
}

describe("V-LASER Virtual Grid & Zone Manager Modal", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(vlaserService, "getConfig").mockResolvedValue(mockConfig)
    vi.spyOn(vlaserService, "getPreviewFrame").mockResolvedValue({
      camera_id: "cam-test-1",
      width: 640,
      height: 360,
      image_data_url: "data:image/jpeg;base64,/9j/fake",
    })
    vi.spyOn(vlaserService, "validateGeometry").mockResolvedValue({
      valid: true,
      errors: [],
      warnings: [],
    })
    vi.spyOn(vlaserService, "saveConfig").mockImplementation(async (_, cfg) => cfg)
    vi.spyOn(vlaserService, "resetConfig").mockResolvedValue({
      success: true,
      message: "Reset OK",
      config: mockConfig,
    })
  })

  it("renders V-LASER title, camera name, and loads lines and zones", async () => {
    const onClose = vi.fn()
    render(
      <VLaserEditorModal
        cameraId="cam-test-1"
        cameraName="Front Camera 101"
        classroom="LH-101"
        isOpen={true}
        onClose={onClose}
      />,
    )

    expect(screen.getByText(/V-LASER • Virtual Grid & Boundary Manager/i)).toBeInTheDocument()
    expect(screen.getByText("Front Camera 101")).toBeInTheDocument()

    // Wait for lines and zones to load in inspector and canvas
    await waitFor(() => {
      expect(screen.getByText("Main Entrance")).toBeInTheDocument()
      expect(screen.getByText("Exit Door")).toBeInTheDocument()
      expect(screen.getAllByText("Seating Area").length).toBeGreaterThanOrEqual(1)
    })
  })

  it("allows selecting a line and updating its name and type", async () => {
    render(
      <VLaserEditorModal
        cameraId="cam-test-1"
        cameraName="Front Camera 101"
        classroom="LH-101"
        isOpen={true}
        onClose={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText("Main Entrance")).toBeInTheDocument()
    })

    // Click line to select it
    fireEvent.click(screen.getByText("Main Entrance"))

    expect(screen.getByText("Virtual Line Settings")).toBeInTheDocument()
    const nameInput = screen.getByDisplayValue("Main Entrance")
    fireEvent.change(nameInput, { target: { value: "Front Entrance Line" } })

    expect(screen.getByDisplayValue("Front Entrance Line")).toBeInTheDocument()
  })

  it("saves configuration and notifies callback", async () => {
    const onSaved = vi.fn()
    render(
      <VLaserEditorModal
        cameraId="cam-test-1"
        cameraName="Front Camera 101"
        classroom="LH-101"
        isOpen={true}
        onClose={vi.fn()}
        onSaved={onSaved}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText("Main Entrance")).toBeInTheDocument()
    })

    const saveBtn = screen.getByRole("button", { name: /Save Configuration/i })
    fireEvent.click(saveBtn)

    await waitFor(() => {
      expect(vlaserService.saveConfig).toHaveBeenCalledWith("cam-test-1", expect.any(Object))
      expect(onSaved).toHaveBeenCalled()
      expect(screen.getByText(/V-LASER configuration saved successfully!/i)).toBeInTheDocument()
    })
  })

  it("polls and renders live spatial telemetry and active track anchors", async () => {
    vi.spyOn(vlaserService, "getSpatialState").mockResolvedValue({
      camera_id: "cam-test-1",
      active_tracks_count: 2,
      active_tracks: [
        {
          track_id: 42,
          anchor: { x: 0.35, y: 0.65 },
          current_zone_id: "zone-1",
          current_zone_name: "Seating Area",
          frames_in_zone: 15,
          total_frames: 20,
          last_seen_seconds_ago: 0.2,
        },
      ],
      zone_headcounts: { "zone-1": 1, unassigned: 0 },
      recent_events: [
        {
          id: "ev-1",
          camera_id: "cam-test-1",
          track_id: 42,
          event_type: "entry",
          line_name: "Main Entrance",
          confidence: 0.98,
          timestamp: 1234567,
        },
      ],
    })

    render(
      <VLaserEditorModal
        cameraId="cam-test-1"
        cameraName="Front Camera 101"
        classroom="LH-101"
        isOpen={true}
        onClose={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText(/Live Spatial Tracking/i)).toBeInTheDocument()
      expect(screen.getByText("2 active")).toBeInTheDocument()
      expect(screen.getByText("ENTRY")).toBeInTheDocument()
      expect(screen.getByText("Line: Main Entrance")).toBeInTheDocument()
      expect(screen.getAllByText(/Track #42/i).length).toBeGreaterThanOrEqual(1)
    })
  })

  it("renders conservative identity status badges for active tracks", async () => {
    vi.spyOn(vlaserService, "getSpatialState").mockResolvedValue({
      camera_id: "cam-test-1",
      active_tracks_count: 2,
      active_tracks: [
        {
          track_id: 101,
          anchor: { x: 0.2, y: 0.4 },
          current_zone_id: "zone-1",
          current_zone_name: "Seating Area",
          frames_in_zone: 25,
          total_frames: 30,
          last_seen_seconds_ago: 0.1,
          identity_state: "identity_verified",
          person_id: "STU_101",
          student_name: "Emma Watson",
          attendance_eligible: true,
        },
        {
          track_id: 102,
          anchor: { x: 0.7, y: 0.8 },
          current_zone_id: null,
          current_zone_name: null,
          frames_in_zone: 2,
          total_frames: 4,
          last_seen_seconds_ago: 0.3,
          identity_state: "pending_verification",
          attendance_eligible: false,
        },
      ],
      zone_headcounts: { "zone-1": 1, unassigned: 1 },
      recent_events: [],
    })

    render(
      <VLaserEditorModal
        cameraId="cam-test-1"
        cameraName="Front Camera 101"
        classroom="LH-101"
        isOpen={true}
        onClose={vi.fn()}
      />,
    )

    await waitFor(() => {
      expect(screen.getByText("Emma Watson")).toBeInTheDocument()
      expect(screen.getByText("Verified")).toBeInTheDocument()
      expect(screen.getByText("Pending")).toBeInTheDocument()
      expect(screen.getByText("Attendance Ready")).toBeInTheDocument()
    })
  })
})
