import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"
import { ControlBar } from "./ControlBar"
import { IP_CAMERA_DEVICE_ID } from "@/components/main/stores/cameraStore"

const readyState = {
  canStart: true,
  reason: null,
  tooltip: undefined,
} as const

describe("ControlBar Mobile IP controls", () => {
  it("opens Mobile IP popover, validates empty URL, and calls onConnectIpCamera", async () => {
    const onConnectIpCamera = vi.fn().mockResolvedValue(undefined)

    render(
      <ControlBar
        cameraDevices={[]}
        selectedCamera=""
        setSelectedCamera={vi.fn()}
        isStreaming={false}
        startCamera={vi.fn()}
        stopCamera={vi.fn()}
        readiness={readyState}
        onConnectIpCamera={onConnectIpCamera}
      />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Mobile IP Camera" }))
    fireEvent.click(screen.getByRole("button", { name: "Connect" }))
    expect(screen.getByText("Enter your phone IP address or stream URL.")).toBeTruthy()
    expect(onConnectIpCamera).not.toHaveBeenCalled()

    const input = screen.getByLabelText("Mobile IP Camera URL")
    fireEvent.change(input, { target: { value: "192.168.1.25:8080" } })
    fireEvent.click(screen.getByRole("button", { name: "Connect" }))

    await waitFor(() => {
      expect(onConnectIpCamera).toHaveBeenCalledWith("192.168.1.25:8080")
    })
  })

  it("displays inline error if Mobile IP probe fails and supports switching back to webcam", async () => {
    const onConnectIpCamera = vi.fn().mockRejectedValue(new Error("Cannot reach phone IP"))
    const onDisconnectIpCamera = vi.fn()

    render(
      <ControlBar
        cameraDevices={[
          { deviceId: "cam-1", kind: "videoinput", label: "USB Cam", groupId: "g" } as MediaDeviceInfo,
        ]}
        selectedCamera={IP_CAMERA_DEVICE_ID}
        setSelectedCamera={vi.fn()}
        isStreaming={false}
        startCamera={vi.fn()}
        stopCamera={vi.fn()}
        readiness={readyState}
        ipCameraUrl="http://192.168.1.25:8080/video"
        onConnectIpCamera={onConnectIpCamera}
        onDisconnectIpCamera={onDisconnectIpCamera}
      />,
    )

    expect(screen.getByText("http://192.168.1.25:8080/video")).toBeTruthy()
    fireEvent.click(screen.getByRole("button", { name: "Switch back to local camera" }))
    expect(onDisconnectIpCamera).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole("button", { name: "Mobile IP Camera" }))
    fireEvent.click(screen.getByRole("button", { name: "Connect" }))
    expect(await screen.findByText("Cannot reach phone IP")).toBeTruthy()
  })

  it("renders health diagnostics badge and opens diagnostics modal", async () => {
    const { cctvService } = await import("@/services/cctvService")
    vi.spyOn(cctvService, "getIpStreamDiagnostics").mockResolvedValue({
      raw_url: "http://192.168.1.25:8080/video",
      status: "CONNECTED",
      camera_ip: "192.168.1.25",
      camera_port: 8080,
      subnet_compatible: true,
      fps: 24.5,
      latency_ms: 18.2,
      reconnect_attempts: 0,
      safe_for_attendance: true,
    })

    render(
      <ControlBar
        cameraDevices={[]}
        selectedCamera={IP_CAMERA_DEVICE_ID}
        setSelectedCamera={vi.fn()}
        isStreaming={true}
        startCamera={vi.fn()}
        stopCamera={vi.fn()}
        readiness={readyState}
        ipCameraUrl="http://192.168.1.25:8080/video"
      />,
    )

    expect(await screen.findByText("CONNECTED")).toBeTruthy()
    expect(screen.getByText(/24.5 FPS/)).toBeTruthy()

    fireEvent.click(screen.getByRole("button", { name: "Test Camera Connection" }))
    expect(await screen.findByText("Camera Diagnostics & Health")).toBeTruthy()
    expect(screen.getByText("192.168.1.25:8080")).toBeTruthy()
    expect(screen.getByText("24.5 fps")).toBeTruthy()
  })

  it("triggers camera reconnection when Reconnect Camera button is clicked", async () => {
    const { cctvService } = await import("@/services/cctvService")
    const reconnectSpy = vi.spyOn(cctvService, "reconnectIpStream").mockResolvedValue({
      raw_url: "http://192.168.1.25:8080/video",
      status: "CONNECTED",
      camera_ip: "192.168.1.25",
      fps: 25.0,
      reconnect_attempts: 1,
    })

    render(
      <ControlBar
        cameraDevices={[]}
        selectedCamera={IP_CAMERA_DEVICE_ID}
        setSelectedCamera={vi.fn()}
        isStreaming={false}
        startCamera={vi.fn()}
        stopCamera={vi.fn()}
        readiness={readyState}
        ipCameraUrl="http://192.168.1.25:8080/video"
      />,
    )

    const reconnectBtn = screen.getByRole("button", { name: "Reconnect Camera" })
    fireEvent.click(reconnectBtn)
    await waitFor(() => {
      expect(reconnectSpy).toHaveBeenCalledWith("http://192.168.1.25:8080/video")
    })
  })
})

