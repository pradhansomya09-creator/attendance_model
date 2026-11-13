import { create } from "zustand"
import type {
  CctvAlertMessage,
  DetectionResult,
  HeadcountSummaryTelemetry,
  ImageQualityTelemetry,
  TrackedFace,
} from "@/components/main/types"
import type { ExtendedFaceRecognitionResponse } from "@/components/main/utils"

interface DetectionState {
  // Detection state
  currentDetections: DetectionResult | null

  // Recognition state
  currentRecognitionResults: Map<number, ExtendedFaceRecognitionResponse>

  // Tracking state
  trackedFaces: Map<string, TrackedFace>

  // Smart CCTV telemetry state
  imageQuality: ImageQualityTelemetry | null
  headcountSummary: HeadcountSummaryTelemetry | null
  cctvAlerts: CctvAlertMessage[]
  activeCctvCameraId: string | null

  // Actions
  setCurrentDetections: (detections: DetectionResult | null) => void
  setCurrentRecognitionResults: (
    results:
      | Map<number, ExtendedFaceRecognitionResponse>
      | ((
          prev: Map<number, ExtendedFaceRecognitionResponse>,
        ) => Map<number, ExtendedFaceRecognitionResponse>),
  ) => void
  setTrackedFaces: (
    faces:
      | Map<string, TrackedFace>
      | ((prev: Map<string, TrackedFace>) => Map<string, TrackedFace>),
  ) => void
  setImageQuality: (quality: ImageQualityTelemetry | null) => void
  setHeadcountSummary: (summary: HeadcountSummaryTelemetry | null) => void
  pushCctvAlert: (alert: CctvAlertMessage) => void
  dismissCctvAlert: (timestamp: number) => void
  setActiveCctvCameraId: (cameraId: string | null) => void
  resetDetectionState: () => void
}

export const useDetectionStore = create<DetectionState>((set, get) => ({
  // Initial state
  currentDetections: null,
  currentRecognitionResults: new Map(),
  trackedFaces: new Map(),
  imageQuality: null,
  headcountSummary: null,
  cctvAlerts: [],
  activeCctvCameraId: null,

  // Actions
  setCurrentDetections: (detections) => set({ currentDetections: detections }),
  setCurrentRecognitionResults: (results) => {
    const prevResults = get().currentRecognitionResults
    const newResults = typeof results === "function" ? results(prevResults) : results
    const mapResults = newResults instanceof Map ? newResults : new Map()
    set({ currentRecognitionResults: mapResults })
  },
  setTrackedFaces: (faces) => {
    const newFaces = typeof faces === "function" ? faces(get().trackedFaces) : faces
    const mapFaces = newFaces instanceof Map ? newFaces : new Map()
    set({ trackedFaces: mapFaces })
  },
  setImageQuality: (quality) => set({ imageQuality: quality }),
  setHeadcountSummary: (summary) => set({ headcountSummary: summary }),
  pushCctvAlert: (alert) =>
    set((state) => ({
      cctvAlerts: [alert, ...state.cctvAlerts.filter((a) => a.message !== alert.message)].slice(
        0,
        8,
      ),
    })),
  dismissCctvAlert: (timestamp) =>
    set((state) => ({
      cctvAlerts: state.cctvAlerts.filter((a) => a.timestamp !== timestamp),
    })),
  setActiveCctvCameraId: (cameraId) => set({ activeCctvCameraId: cameraId }),
  resetDetectionState: () =>
    set({
      currentDetections: null,
      currentRecognitionResults: new Map(),
      trackedFaces: new Map(),
      imageQuality: null,
      headcountSummary: null,
    }),
}))
