import { useEffect, useState, useCallback, type FormEvent } from "react"
import { Smartphone, X, Loader2, Activity, RefreshCw, CheckCircle2, AlertTriangle, AlertCircle } from "lucide-react"
import { Dropdown, Tooltip } from "@/components/shared"
import { formatCameraDevices } from "@/utils/cameraConstraints"
import { IP_CAMERA_DEVICE_ID } from "@/components/main/stores/cameraStore"
import type { ScanReadiness } from "@/components/main/utils/scanReadiness"
import { cctvService, type IpCameraDiagnostics } from "@/services/cctvService"

interface ControlBarProps {
  cameraDevices: MediaDeviceInfo[]
  selectedCamera: string
  setSelectedCamera: (deviceId: string) => void
  isStreaming: boolean
  startCamera: () => void
  stopCamera: (forceCleanup?: boolean) => void
  readiness: ScanReadiness
  ipCameraUrl?: string
  onConnectIpCamera?: (url: string) => Promise<void>
  onDisconnectIpCamera?: () => void
}

export function ControlBar({
  cameraDevices,
  selectedCamera,
  setSelectedCamera,
  isStreaming,
  startCamera,
  stopCamera,
  readiness,
  ipCameraUrl = "",
  onConnectIpCamera,
  onDisconnectIpCamera,
}: ControlBarProps) {
  const [isIpPopoverOpen, setIsIpPopoverOpen] = useState(false)
  const isMobileIpSelected = selectedCamera === IP_CAMERA_DEVICE_ID
  const [draftIpUrl, setDraftIpUrl] = useState(ipCameraUrl)
  const [ipConnectError, setIpConnectError] = useState<string | null>(null)
  const [isProbingIp, setIsProbingIp] = useState(false)
  const [diagnostics, setDiagnostics] = useState<IpCameraDiagnostics | null>(null)
  const [isTestingDiag, setIsTestingDiag] = useState(false)
  const [isReconnecting, setIsReconnecting] = useState(false)
  const [showDiagModal, setShowDiagModal] = useState(false)

  const fetchDiagnostics = useCallback(async (url: string) => {
    try {
      const data = await cctvService.getIpStreamDiagnostics(url)
      setDiagnostics(data)
      return data
    } catch {
      return null
    }
  }, [])

  useEffect(() => {
    setDraftIpUrl(ipCameraUrl)
  }, [ipCameraUrl])

  useEffect(() => {
    if (!isMobileIpSelected || !ipCameraUrl) {
      setDiagnostics(null)
      return
    }

    void fetchDiagnostics(ipCameraUrl)

    if (isStreaming) {
      const interval = setInterval(() => {
        void fetchDiagnostics(ipCameraUrl)
      }, 3000)
      return () => clearInterval(interval)
    }
  }, [isMobileIpSelected, ipCameraUrl, isStreaming, fetchDiagnostics])

  const handleTestConnection = async () => {
    const url = ipCameraUrl || draftIpUrl
    if (!url) return
    setIsTestingDiag(true)
    try {
      const res = await cctvService.getIpStreamDiagnostics(url)
      setDiagnostics(res)
      setShowDiagModal(true)
    } catch (err) {
      setIpConnectError(err instanceof Error ? err.message : "Diagnostics check failed")
    } finally {
      setIsTestingDiag(false)
    }
  }

  const handleReconnect = async () => {
    if (!ipCameraUrl) return
    setIsReconnecting(true)
    try {
      const res = await cctvService.reconnectIpStream(ipCameraUrl)
      setDiagnostics(res)
    } catch (err) {
      console.warn("Camera reconnect error:", err)
    } finally {
      setIsReconnecting(false)
    }
  }

  const getStatusBadge = (status?: string) => {
    switch (status) {
      case "CONNECTED":
        return {
          dot: "bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]",
          label: "CONNECTED",
          text: "text-emerald-300",
          border: "border-emerald-500/30",
          bg: "bg-emerald-950/40",
        }
      case "LOW_FRAME_RATE":
        return {
          dot: "bg-yellow-400",
          label: "LOW FPS",
          text: "text-yellow-300",
          border: "border-yellow-500/30",
          bg: "bg-yellow-950/40",
        }
      case "STREAM_FROZEN":
        return {
          dot: "bg-amber-400 animate-pulse",
          label: "STREAM FROZEN",
          text: "text-amber-300",
          border: "border-amber-500/30",
          bg: "bg-amber-950/40",
        }
      case "CONNECTING":
      case "RECONNECTING":
        return {
          dot: "bg-cyan-400 animate-pulse",
          label: status,
          text: "text-cyan-300",
          border: "border-cyan-500/30",
          bg: "bg-cyan-950/40",
        }
      case "NO_FRAMES_RECEIVED":
        return {
          dot: "bg-orange-400",
          label: "NO FRAMES",
          text: "text-orange-300",
          border: "border-orange-500/30",
          bg: "bg-orange-950/40",
        }
      case "CAMERA_ERROR":
      case "DISCONNECTED":
      default:
        return {
          dot: "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.85)]",
          label: status || "DISCONNECTED",
          text: "text-rose-300",
          border: "border-rose-500/30",
          bg: "bg-rose-950/40",
        }
    }
  }


  const handleIpSubmit = async (e: FormEvent) => {
    e.preventDefault()
    if (!onConnectIpCamera) return
    const trimmed = draftIpUrl.trim()
    if (!trimmed) {
      setIpConnectError("Enter your phone IP address or stream URL.")
      return
    }
    if (trimmed.includes("192.0.0.")) {
      setIpConnectError(
        "192.0.0.x is an internal cellular data IP. Turn OFF Mobile Data on your phone, restart IP Webcam to see your real Wi-Fi IP, or turn on Mobile Hotspot.",
      )
      return
    }
    setIsProbingIp(true)
    setIpConnectError(null)
    try {
      await onConnectIpCamera(trimmed)
      setIsIpPopoverOpen(false)
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Could not connect to Mobile IP camera."
      setIpConnectError(message)
    } finally {
      setIsProbingIp(false)
    }
  }
  const handlePrimaryAction = () => {
    if (isStreaming) {
      stopCamera()
    } else {
      startCamera()
    }
  }

  const getButtonState = () => {
    if (isStreaming) {
      return {
        label: "Stop",
        className:
          "border border-rose-500/30 bg-[#2a1216] font-semibold text-rose-200 hover:border-rose-500/50 hover:bg-[#3d181f] hover:text-white active:scale-95 transition-all tracking-wider",
        tooltip: undefined,
        enabled: true,
      }
    }

    if (!readiness.canStart) {
      return {
        label: readiness.reason === "loading" ? "Preparing…" : "Start scan",
        className:
          "bg-[#141518] border border-white/10 text-white/50 hover:bg-[#141518] hover:text-white/50",
        tooltip: readiness.tooltip,
        enabled: false,
      }
    }

    const cyanStyle =
      "border border-cyan-500/30 bg-[#0e2429] font-semibold text-cyan-200 hover:border-cyan-500/50 hover:bg-[#14353d] hover:text-white active:scale-95 transition-all tracking-wider"

    return {
      label: "Start scan",
      className: cyanStyle,
      tooltip: undefined,
      enabled: true,
    }
  }

  const buttonState = getButtonState()

  return (
    <div className="relative">
      {isIpPopoverOpen && (
        <div className="absolute bottom-full left-3 z-40 mb-2 w-80 rounded-xl border border-white/15 bg-[#111318]/95 p-3.5 shadow-2xl backdrop-blur-md">
          <div className="mb-2 flex items-center justify-between">
            <div className="flex items-center gap-2 text-xs font-semibold text-cyan-200">
              <Smartphone className="h-3.5 w-3.5" />
              <span>Connect Mobile IP Camera</span>
            </div>
            <button
              type="button"
              onClick={() => {
                setIsIpPopoverOpen(false)
                setIpConnectError(null)
              }}
              aria-label="Close Mobile IP popover"
              className="rounded p-0.5 text-white/50 hover:bg-white/10 hover:text-white">
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          <form onSubmit={handleIpSubmit} className="space-y-2.5">
            <input
              type="text"
              value={draftIpUrl}
              onChange={(e) => {
                setDraftIpUrl(e.target.value)
                if (ipConnectError) setIpConnectError(null)
              }}
              placeholder="192.168.1.10:8080 or http://.../video"
              aria-label="Mobile IP Camera URL"
              disabled={isProbingIp}
              autoFocus
              className="w-full rounded-lg border border-white/15 bg-black/50 px-3 py-2 text-xs text-white placeholder-white/35 focus:border-cyan-400/60 focus:outline-none disabled:opacity-50"
            />
            {draftIpUrl.includes("192.0.0.") && (
              <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1.5 text-[11px] text-amber-200 leading-snug">
                ⚠️ <strong>192.0.0.x is an internal Mobile Data IP</strong>. Turn <strong>OFF Mobile Data</strong> on your phone and restart IP Webcam to get your Wi-Fi address (or turn on <strong>Mobile Hotspot</strong>).
              </div>
            )}
            <p className="text-[11px] leading-relaxed text-white/50">
              Supports{" "}
              <span className="text-cyan-300/80 font-medium">IP Webcam</span> (Android · port 8080),{" "}
              <span className="text-cyan-300/80 font-medium">DroidCam</span> (port 4747), or RTSP
              URLs on the same Wi-Fi.
            </p>
            <ol className="text-[10px] leading-5 text-white/35 list-decimal list-inside space-y-0.5 pl-0.5">
              <li>Install <strong className="text-white/50">IP Webcam</strong> on your Android phone.</li>
              <li>Open the app → tap <strong className="text-white/50">Start server</strong>.</li>
              <li>Enter the IP shown on screen (e.g. <code className="text-cyan-400/70">192.168.x.x:8080</code>).</li>
              <li>Your phone &amp; PC must be on the <strong className="text-white/50">same Wi-Fi</strong>.</li>
            </ol>
            {ipConnectError && (
              <div className="rounded-md border border-rose-500/30 bg-rose-500/10 px-2.5 py-2 text-[11px] text-rose-200 space-y-1">
                <div className="font-semibold text-rose-300">Connection failed</div>
                <div className="leading-relaxed">{ipConnectError}</div>
              </div>
            )}
            <div className="flex items-center justify-between pt-0.5">
              <button
                type="button"
                disabled={isProbingIp || isTestingDiag}
                onClick={handleTestConnection}
                className="flex items-center gap-1.5 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs font-medium text-white/70 hover:bg-white/5 hover:text-white disabled:opacity-50">
                {isTestingDiag ?
                  <Loader2 className="h-3 w-3 animate-spin" />
                : <Activity className="h-3 w-3 text-cyan-400" />}
                <span>Test Connection</span>
              </button>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    setIsIpPopoverOpen(false)
                    setIpConnectError(null)
                  }}
                  disabled={isProbingIp}
                  className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-white/70 hover:bg-white/5 hover:text-white disabled:opacity-50">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isProbingIp}
                  className="flex items-center gap-1.5 rounded-lg border border-cyan-500/40 bg-[#0e2429] px-3 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-[#14353d] hover:text-white disabled:opacity-50">
                  {isProbingIp ?
                    <>
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                      <span>Connecting…</span>
                    </>
                  : <span>Connect</span>}
                </button>
              </div>
            </div>
          </form>
        </div>
      )}

      {/* Camera Diagnostics Modal */}
      {showDiagModal && diagnostics && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-2xl border border-white/15 bg-[#111318] p-5 shadow-2xl">
            <div className="mb-4 flex items-center justify-between border-b border-white/10 pb-3">
              <div className="flex items-center gap-2">
                <Activity className="h-4 w-4 text-cyan-400" />
                <h3 className="text-sm font-semibold text-white">Camera Diagnostics &amp; Health</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowDiagModal(false)}
                className="rounded p-1 text-white/50 hover:bg-white/10 hover:text-white">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex items-center justify-between rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                <span className="text-white/60">Connection Status</span>
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 font-bold ${
                    getStatusBadge(diagnostics.status).border
                  } ${getStatusBadge(diagnostics.status).bg} ${
                    getStatusBadge(diagnostics.status).text
                  }`}>
                  <span
                    className={`h-2 w-2 rounded-full ${getStatusBadge(diagnostics.status).dot}`}
                  />
                  {diagnostics.status}
                </span>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="text-[10px] text-white/50">Camera Host &amp; Port</div>
                  <div className="mt-0.5 font-mono text-cyan-200">
                    {diagnostics.camera_ip || "—"}:{diagnostics.camera_port || "—"}
                  </div>
                </div>
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="text-[10px] text-white/50">Subnet Match</div>
                  <div className="mt-0.5 flex items-center gap-1 font-medium">
                    {diagnostics.subnet_compatible ?
                      <span className="flex items-center gap-1 text-emerald-300">
                        <CheckCircle2 className="h-3 w-3" /> Compatible
                      </span>
                    : <span className="flex items-center gap-1 text-rose-300">
                        <AlertCircle className="h-3 w-3" /> Mismatch
                      </span>
                    }
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="text-[10px] text-white/50">Current FPS</div>
                  <div className="mt-0.5 font-mono font-semibold text-white">
                    {diagnostics.fps !== undefined ? `${diagnostics.fps} fps` : "0 fps"}
                  </div>
                </div>
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="text-[10px] text-white/50">Read Latency</div>
                  <div className="mt-0.5 font-mono font-semibold text-white">
                    {diagnostics.latency_ms !== undefined ? `${diagnostics.latency_ms} ms` : "—"}
                  </div>
                </div>
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="text-[10px] text-white/50">Reconnects</div>
                  <div className="mt-0.5 font-mono font-semibold text-white">
                    {diagnostics.reconnect_attempts ?? 0}
                  </div>
                </div>
              </div>

              <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                <div className="text-[10px] text-white/50">Resolved Stream Endpoint</div>
                <div className="mt-0.5 break-all font-mono text-[11px] text-cyan-300/90">
                  {diagnostics.resolved_url || diagnostics.raw_url || "—"}
                </div>
              </div>

              {diagnostics.host_ips && diagnostics.host_ips.length > 0 && (
                <div className="rounded-lg border border-white/5 bg-white/[0.02] p-2.5">
                  <div className="text-[10px] text-white/50">Host PC Local Network IPs</div>
                  <div className="mt-0.5 font-mono text-[11px] text-white/80">
                    {diagnostics.host_ips.join(", ")}
                  </div>
                </div>
              )}

              {diagnostics.last_error && (
                <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-2.5 text-rose-200">
                  <div className="flex items-center gap-1.5 font-semibold text-rose-300">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    <span>Last Connection Error</span>
                  </div>
                  <div className="mt-1 text-[11px] leading-relaxed">{diagnostics.last_error}</div>
                </div>
              )}
            </div>

            <div className="mt-5 flex items-center justify-between border-t border-white/10 pt-3">
              <button
                type="button"
                onClick={handleReconnect}
                disabled={isReconnecting}
                className="flex items-center gap-1.5 rounded-lg border border-cyan-500/30 bg-[#0e2429] px-3 py-1.5 text-xs font-semibold text-cyan-200 hover:bg-[#14353d] hover:text-white disabled:opacity-50">
                <RefreshCw className={`h-3 w-3 ${isReconnecting ? "animate-spin" : ""}`} />
                <span>{isReconnecting ? "Reconnecting…" : "Reconnect Camera"}</span>
              </button>
              <button
                type="button"
                onClick={() => setShowDiagModal(false)}
                className="rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-white/70 hover:bg-white/5 hover:text-white">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      <div className="flex min-h-16 items-center justify-between gap-4 rounded-lg p-3 pt-0">
        <div className="flex items-center space-x-3">
          {isMobileIpSelected ?
            <div className="flex items-center gap-2">
              <div className="flex items-center gap-2 rounded-lg border border-cyan-500/30 bg-cyan-950/40 px-3 py-2 text-sm font-medium text-cyan-100">
                <Smartphone className="h-4 w-4 shrink-0 text-cyan-300" />
                <span className="max-w-[180px] truncate" title={ipCameraUrl || "Mobile IP Camera"}>
                  {ipCameraUrl || "Mobile IP Camera"}
                </span>

                {diagnostics && (
                  <button
                    type="button"
                    onClick={() => setShowDiagModal(true)}
                    className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold transition hover:scale-105 ${
                      getStatusBadge(diagnostics.status).border
                    } ${getStatusBadge(diagnostics.status).bg} ${
                      getStatusBadge(diagnostics.status).text
                    }`}>
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${getStatusBadge(diagnostics.status).dot}`}
                    />
                    <span>{getStatusBadge(diagnostics.status).label}</span>
                    {diagnostics.fps !== undefined && diagnostics.fps > 0 && (
                      <span className="opacity-80">• {diagnostics.fps} FPS</span>
                    )}
                  </button>
                )}

                <button
                  type="button"
                  onClick={handleReconnect}
                  disabled={isReconnecting}
                  aria-label="Reconnect Camera"
                  title="Reconnect Camera"
                  className="rounded p-1 text-cyan-200/70 hover:bg-white/10 hover:text-white disabled:opacity-50">
                  <RefreshCw
                    className={`h-3 w-3 ${isReconnecting ? "animate-spin text-cyan-300" : ""}`}
                  />
                </button>

                {!isStreaming && onDisconnectIpCamera && (
                  <button
                    type="button"
                    onClick={onDisconnectIpCamera}
                    aria-label="Switch back to local camera"
                    title="Switch back to local webcam"
                    className="inline-flex items-center gap-1 rounded bg-white/10 px-2 py-0.5 text-[11px] font-medium text-cyan-200 hover:bg-white/20 hover:text-white transition">
                    <X className="size-3" />
                    <span>Use Webcam</span>
                  </button>
                )}
              </div>

              <button
                type="button"
                onClick={handleTestConnection}
                disabled={isTestingDiag}
                aria-label="Test Camera Connection"
                className="flex items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-2.5 py-2 text-xs font-medium text-white/80 hover:bg-white/10 hover:text-white disabled:opacity-50">
                <Activity className="h-3.5 w-3.5 text-cyan-400" />
                <span>{isTestingDiag ? "Testing…" : "Diagnostics"}</span>
              </button>
            </div>
          : cameraDevices.length === 1 ?
            <div className="flex items-center rounded-lg border border-white/5 bg-white/5 px-4 py-2 text-sm font-medium text-white/90">
              <span className="max-w-[200px] truncate">
                {formatCameraDevices(cameraDevices)[0]?.label || "Camera"}
              </span>
            </div>
          : cameraDevices.length > 1 ?
            <div className="flex flex-col items-start space-y-1">
              <div className="w-fit max-w-[260px]">
                <Dropdown
                  fit
                  menuWidth={200}
                  align="left"
                  options={formatCameraDevices(cameraDevices)}
                  value={selectedCamera}
                  onChange={(deviceId) => {
                    if (deviceId) setSelectedCamera(String(deviceId))
                  }}
                  placeholder="Select camera…"
                  emptyMessage="No cameras available"
                  disabled={isStreaming}
                  maxHeight={256}
                  buttonClassName="px-4 font-medium"
                  showPlaceholderOption={false}
                  allowClear={false}
                />
              </div>
            </div>
          : null}

          {onConnectIpCamera && (
            <button
              type="button"
              disabled={isStreaming}
              onClick={() => {
                setIpConnectError(null)
                setIsIpPopoverOpen((prev) => !prev)
              }}
              aria-label="Mobile IP Camera"
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-xs font-medium text-white/80 transition-colors hover:border-cyan-500/35 hover:bg-white/10 hover:text-white disabled:cursor-not-allowed disabled:opacity-45">
              <Smartphone className="h-3.5 w-3.5 text-cyan-300" />
              <span>{isMobileIpSelected ? "Change IP" : "Mobile IP"}</span>
            </button>
          )}
        </div>

        <div className="flex items-center gap-3">
          <Tooltip content={buttonState.tooltip}>
            <button
              onClick={handlePrimaryAction}
              disabled={!buttonState.enabled}
              aria-label={buttonState.label}
              className={`flex min-w-28 items-center justify-center gap-2 rounded-lg py-2.5 text-sm font-medium transition-all duration-200 ease-in-out disabled:cursor-not-allowed disabled:opacity-50 ${buttonState.className}`}>
              {buttonState.label}
            </button>
          </Tooltip>
        </div>
      </div>
    </div>
  )
}
