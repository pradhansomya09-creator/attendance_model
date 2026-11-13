import { create } from "zustand"
import { persistentSettings } from "@/services/PersistentSettingsService"

export const IP_CAMERA_DEVICE_ID = "mobile_ip_camera"
const IP_CAMERA_URL_STORAGE_KEY = "facenox.mobileIpCameraUrl"

interface CameraState {
  isStreaming: boolean
  isVideoLoading: boolean
  cameraActive: boolean
  websocketStatus: "disconnected" | "connecting" | "connected" | "error"
  cameraDevices: MediaDeviceInfo[]
  selectedCamera: string // The ACTIVE camera
  preferredCameraId: string | null // The USER'S CHOICE (persisted)
  preferredCameraLabel: string | null // SECONDARY MATCH (persisted)
  isPreferredCameraMissing: boolean
  ipCameraUrl: string
  activeIpStreamUrl: string | null
  setIsStreaming: (value: boolean) => void
  setIsVideoLoading: (value: boolean) => void
  setCameraActive: (value: boolean) => void
  setWebsocketStatus: (status: "disconnected" | "connecting" | "connected" | "error") => void
  setCameraDevices: (devices: MediaDeviceInfo[]) => void
  setSelectedCamera: (deviceId: string) => void
  setIpCameraUrl: (url: string) => void
  setActiveIpStreamUrl: (url: string | null) => void
}

export const useCameraStore = create<CameraState>((set, get) => ({
  isStreaming: false,
  isVideoLoading: false,
  cameraActive: false,
  websocketStatus: "disconnected",
  cameraDevices: [],
  selectedCamera: "",
  preferredCameraId: null,
  preferredCameraLabel: null,
  isPreferredCameraMissing: false,
  ipCameraUrl: "",
  activeIpStreamUrl: null,
  setIsStreaming: (value) => set({ isStreaming: value }),
  setIsVideoLoading: (value) => set({ isVideoLoading: value }),
  setCameraActive: (value) => set({ cameraActive: value }),
  setWebsocketStatus: (status) => set({ websocketStatus: status }),
  setIpCameraUrl: (url) => {
    const trimmed = url.trim()
    set({ ipCameraUrl: trimmed })
    try {
      if (typeof window !== "undefined" && window.localStorage) {
        if (trimmed) {
          window.localStorage.setItem(IP_CAMERA_URL_STORAGE_KEY, trimmed)
        } else {
          window.localStorage.removeItem(IP_CAMERA_URL_STORAGE_KEY)
        }
      }
    } catch {
      // Ignore storage failures
    }
  },
  setActiveIpStreamUrl: (url) => set({ activeIpStreamUrl: url }),
  setCameraDevices: (devices) => {
    const { preferredCameraId, preferredCameraLabel, selectedCamera, ipCameraUrl } = get()
    set({ cameraDevices: devices })

    if (
      (selectedCamera === IP_CAMERA_DEVICE_ID || preferredCameraId === IP_CAMERA_DEVICE_ID) &&
      ipCameraUrl
    ) {
      set({
        selectedCamera: IP_CAMERA_DEVICE_ID,
        isPreferredCameraMissing: false,
      })
      return
    }

    if (devices.length === 0) {
      set({ isPreferredCameraMissing: !!preferredCameraId })
      return
    }

    // Goal: Use preferred ID if available.
    const preferredIdExists = devices.some((d) => d.deviceId === preferredCameraId)

    if (preferredCameraId && preferredIdExists) {
      // EXACT ID MATCH (Auto-Recovery)
      if (selectedCamera !== preferredCameraId) {
        set({
          selectedCamera: preferredCameraId,
          isPreferredCameraMissing: false,
        })
      } else {
        set({ isPreferredCameraMissing: false })
      }
      return
    }

    // Tier 2: Search by LABEL if ID missing (Handles Device ID rotation)
    if (preferredCameraLabel) {
      const labelMatch = devices.find((d) => d.label === preferredCameraLabel)
      if (labelMatch) {
        // FOUND BY LABEL! Auto-Update the ID choice
        const newId = labelMatch.deviceId
        set({
          selectedCamera: newId,
          preferredCameraId: newId,
          isPreferredCameraMissing: false,
        })
        persistentSettings.setUIState({ selectedCamera: newId }).catch(console.error)
        return
      }
    }

    // Tier 3: PREFERRED IS MISSING (Fallback)
    if (preferredCameraId) {
      const fallbackId = devices[0].deviceId
      if (selectedCamera !== fallbackId) {
        set({
          selectedCamera: fallbackId,
          isPreferredCameraMissing: true,
        })
      } else {
        set({ isPreferredCameraMissing: true })
      }
    } else {
      // NO PREFERENCE (Fresh Start)
      if (!selectedCamera && devices.length > 0) {
        const firstId = devices[0].deviceId
        set({ selectedCamera: firstId })
      }
    }
  },
  setSelectedCamera: (deviceId) => {
    if (!deviceId) return
    const { cameraDevices, ipCameraUrl } = get()
    const device = cameraDevices.find((d) => d.deviceId === deviceId)
    const label =
      deviceId === IP_CAMERA_DEVICE_ID ?
        ipCameraUrl ? `Mobile IP (${ipCameraUrl})` : "Mobile IP Camera"
      : device?.label || null

    // Explicit selection sets the PREFERRED choice
    set({
      selectedCamera: deviceId,
      preferredCameraId: deviceId,
      preferredCameraLabel: label,
      isPreferredCameraMissing: false,
    })
    // Save preference to store
    persistentSettings
      .setUIState({
        selectedCamera: deviceId,
        selectedCameraLabel: label,
      })
      .catch(console.error)
  },
}))

// Load selectedCamera from store on initialization
if (typeof window !== "undefined") {
  let savedIpUrl = ""
  try {
    savedIpUrl = window.localStorage?.getItem(IP_CAMERA_URL_STORAGE_KEY) || ""
  } catch {
    savedIpUrl = ""
  }
  if (savedIpUrl) {
    useCameraStore.setState({ ipCameraUrl: savedIpUrl })
  }
  persistentSettings.getUIState().then((uiState) => {
    if (uiState.selectedCamera) {
      if (uiState.selectedCamera === IP_CAMERA_DEVICE_ID && !savedIpUrl) {
        return
      }
      useCameraStore.setState({
        selectedCamera: uiState.selectedCamera,
        preferredCameraId: uiState.selectedCamera,
        preferredCameraLabel: uiState.selectedCameraLabel,
      })
    }
  })
}
