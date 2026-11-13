import { HttpClient } from "./attendance/HttpClient"
import type {
  CameraPreviewFrameResponse,
  CameraSpatialStateResponse,
  SpatialEvent,
  ValidationResponse,
  VLaserConfig,
  VirtualLine,
  VirtualZone,
} from "@/types/vlaser"

const API_BASE_URL = "http://127.0.0.1:7400"

export class VLaserService {
  private client = new HttpClient(API_BASE_URL)

  /** Fetch active or default V-LASER config for a camera */
  getConfig(cameraId: string) {
    return this.client.get<VLaserConfig>(`/cctv/vlaser/cameras/${cameraId}`)
  }

  /** Save V-LASER grid, lines, and zones configuration */
  saveConfig(cameraId: string, config: VLaserConfig) {
    return this.client.post<VLaserConfig>(`/cctv/vlaser/cameras/${cameraId}`, config)
  }

  /** Reset camera V-LASER config to default factory template */
  resetConfig(cameraId: string) {
    return this.client.delete<{ success: boolean; message: string; config: VLaserConfig }>(
      `/cctv/vlaser/cameras/${cameraId}`,
    )
  }

  /** Validate lines and zones geometry (e.g. self-intersection, duplicates) */
  validateGeometry(lines: VirtualLine[], zones: VirtualZone[]) {
    return this.client.post<ValidationResponse>("/cctv/vlaser/validate", {
      lines,
      zones,
    })
  }

  /** Fetch a preview frame from camera for the visual editor */
  getPreviewFrame(cameraId: string) {
    return this.client.get<CameraPreviewFrameResponse>(
      `/cctv/vlaser/cameras/${cameraId}/preview-frame`,
    )
  }

  /** Fetch active spatial tracking state, zone residency and headcount */
  getSpatialState(cameraId: string) {
    return this.client.get<CameraSpatialStateResponse>(
      `/cctv/vlaser/cameras/${cameraId}/spatial-state`,
    )
  }

  /** Fetch recent spatial events (entry, exit, transitions) */
  getSpatialEvents(cameraId: string, limit = 50) {
    return this.client.get<{ camera_id: string; count: number; events: SpatialEvent[] }>(
      `/cctv/vlaser/cameras/${cameraId}/events`,
      { limit: String(limit) },
    )
  }

  /** Fetch aggregated recent spatial events across all active CCTV cameras */
  getAllRecentEvents(limit = 50) {
    return this.client.get<{ count: number; events: SpatialEvent[] }>(
      "/cctv/vlaser/events/recent",
      { limit: String(limit) },
    )
  }
}

export const vlaserService = new VLaserService()

